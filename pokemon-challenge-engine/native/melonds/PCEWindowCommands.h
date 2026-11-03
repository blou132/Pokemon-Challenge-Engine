// SPDX-License-Identifier: GPL-3.0-or-later
// Included at the end of Window.cpp; uses the same native actions as its menus.
#include "PCECommands.h"
#include <QCryptographicHash>
#include <memory>

void MainWindow::startPCECommands() {
    if (windowID != 0 || emuInstance->getInstanceID() != 0) return;
    auto mailbox = std::make_shared<PCECommands::Mailbox>();
    if (!mailbox->enabled()) return;
    auto timer = new QTimer(this);
    // Pin the first active cartridge. Changing cartridge requires a new PCE session.
    struct Identity { const melonDS::NDSCart::CartCommon* cart = nullptr; QString hash; std::string name; unsigned long long generation = 0; QString states; bool pulseStarted = false; };
    auto identity = std::make_shared<Identity>();
    connect(timer, &QTimer::timeout, this, [this, mailbox, identity]() {
        if (!mailbox->enabled() || !emuThread->emuIsActive()) return;
        auto* nds = emuInstance->getNDS();
        auto* cart = nds ? nds->GetNDSCart() : nullptr;
        if (!cart || nds->ConsoleType != 0) return;
        if (!identity->cart) {
            identity->cart = cart;
            identity->name = emuInstance->baseROMDir + emuInstance->baseROMName;
            identity->hash = emuInstance->pceRomHash;
            identity->generation = emuInstance->pceCartGeneration;
            identity->states = localCfg.GetQString("SavestatePath");
        }
        const bool sameCart = identity->cart == cart && identity->generation == emuInstance->pceCartGeneration
            && identity->name == emuInstance->baseROMDir + emuInstance->baseROMName;
        QJsonObject keyboard;
        for (int i = 0; i < 12; ++i)
            keyboard[emuInstance->buttonNames[i]] = localCfg.GetInt(std::string("Keyboard.") + emuInstance->buttonNames[i]);
        QJsonObject status {{"rom_sha256", identity->hash}, {"available", sameCart},
            {"state_directory", identity->states}, {"keyboard", keyboard}, {"screen_layout", windowCfg.GetInt("ScreenLayout")},
            {"capabilities", QJsonArray {"speed", "save_state", "load_state", "input_settings", "video_settings", "screen_layout", "input_pulse"}}};
        mailbox->poll(status, [this, sameCart, identity](QString command, QJsonObject args) -> QJsonObject {
            auto failure = [](const char* reason) { return QJsonObject {{"ok", false}, {"error", reason}}; };
            auto success = []() { return QJsonObject {{"ok", true}, {"error", QJsonValue()}}; };
            if (!sameCart) return failure("cartridge_changed");
            if (localCfg.GetQString("SavestatePath") != identity->states) return failure("state_directory_changed");
            // Do not change settings or nest dialogs while a native dialog is open.
            if (QApplication::activeModalWidget()) return failure("dialog_open");
            if (command == "input_pulse") {
                const int mask = args["mask"].toInt(-1), frames = args["frames"].toInt(-1);
                if (args.size() != 2 || mask < 1 || mask > 4095 || frames < 1 || frames > 60
                    || args["mask"].toDouble() != mask || args["frames"].toDouble() != frames
                    || (mask & 48) == 48 || (mask & 192) == 192) return failure("invalid_input");
                auto& pulse = emuInstance->pceInputPulse;
                if (!identity->pulseStarted) {
                    emuThread->emuPause(false);
                    pulse.begin(mask, frames, SDL_GetTicks64());
                    emuThread->emuUnpause(false);
                    identity->pulseStarted = true;
                }
                if (!pulse.finished && SDL_GetTicks64() >= pulse.deadline) {
                    emuThread->emuPause(false);
                    pulse.remaining = 0;
                    pulse.expired = true;
                    pulse.finished = true;
                    emuThread->emuUnpause(false);
                }
                if (!pulse.finished) return QJsonObject {{"pending", true}};
                identity->pulseStarted = false;
                if (pulse.expired) return failure("input_expired");
                auto result = success(); result["frames"] = static_cast<int>(pulse.completed); return result;
            }
            if (command == "speed") {
                const auto speed = args["value"].toString();
                if (args.size() != 1 || (speed != "x1" && speed != "x2" && speed != "x4" && speed != "MAX")) return failure("invalid_speed");
                emuThread->emuPause(false);
                emuInstance->targetFPS = 60.0;
                emuInstance->fastForwardFPS = speed == "x2" ? 120.0 : speed == "x4" ? 240.0 : 1000.0;
                emuInstance->fastForwardToggled = speed != "x1";
                emuInstance->slowmoToggled = false;
                emuInstance->doLimitFPS = speed != "MAX";
                actLimitFramerate->setChecked(emuInstance->doLimitFPS);
                emuThread->emuUnpause(false);
                auto result = success(); result["speed"] = speed; return result;
            }
            if (command == "input_settings" || command == "video_settings") {
                if (!args.isEmpty()) return failure("invalid_parameters");
                if (command == "input_settings") onOpenInputConfig();
                else onOpenVideoSettings();
                raise(); activateWindow();
                return success();
            }
            if (command == "screen_layout") {
                const int layout = args["value"].toInt(-1);
                if (args.size() != 1 || layout < 0 || layout >= screenLayout_MAX || args["value"].toDouble() != layout) return failure("invalid_layout");
                actScreenLayout[layout]->trigger();
                return success();
            }
            if (command != "save_state" && command != "load_state") return failure("unsupported_command");
            const int slot = args["slot"].toInt(-1);
            if (args.size() != 1 || slot < 1 || slot > 8 || args["slot"].toDouble() != slot) return failure("invalid_slot");
            if (globalCfg.GetBool("Savestate.RelocSRAM")) return failure("sram_relocation_enabled");
            const QString filename = QString::fromStdString(emuInstance->getSavestateName(slot));
            const QString directory = localCfg.GetQString("SavestatePath");
            if (!PCECommands::PlainPath(filename) || !QFileInfo(directory).isDir()
                || QFileInfo(filename).absolutePath() != QDir(directory).absolutePath()) return failure("unsafe_state_path");
            if (command == "load_state") {
                if (!QFileInfo(filename).isFile() || QFileInfo(filename).size() > 256 * 1024 * 1024) return failure("state_missing_or_invalid");
                if (!emuThread->loadState(filename)) return failure("state_load_failed");
                actUndoStateLoad->setEnabled(true);
                return success();
            }
            // Native serialization first; atomic replacement preserves the prior slot on failure.
            const QString temporary = filename + ".pce-" + QUuid::createUuid().toString(QUuid::Id128);
            if (!emuThread->saveState(temporary)) { QFile::remove(temporary); return failure("state_save_failed"); }
            QFile input(temporary);
            QSaveFile output(filename); output.setDirectWriteFallback(false);
            bool ok = input.open(QIODevice::ReadOnly) && output.open(QIODevice::WriteOnly);
            while (ok && !input.atEnd()) { const auto data = input.read(1024 * 1024); ok = !data.isEmpty() && output.write(data) == data.size(); }
            ok = ok && input.error() == QFileDevice::NoError && output.commit();
            input.close(); QFile::remove(temporary);
            if (!ok) return failure("state_commit_failed");
            actLoadState[slot]->setEnabled(true);
            return success();
        });
    });
    timer->start(200);
}
