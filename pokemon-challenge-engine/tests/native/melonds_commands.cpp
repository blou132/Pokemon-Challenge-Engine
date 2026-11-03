// Tests the shipped transport and input accumulator without an emulator or ROM.
#include "PCECommands.h"
#include "PCEInputPulse.h"
#include <QTemporaryDir>
#include <cassert>
#include <iostream>

int main(int argc, char** argv) {
    QCoreApplication app(argc, argv);
    QTemporaryDir directory;
    assert(directory.isValid());
    qputenv("PCE_BRIDGE_DIR", directory.path().toUtf8());
    qputenv("PCE_BRIDGE_SESSION", QByteArray(32, 'a'));
    PCECommands::Mailbox mailbox;
    QJsonObject status {{"rom_sha256", QString(64, 'c')}, {"available", true}};
    int calls = 0;
    auto execute = [&](QString, QJsonObject) { ++calls; return QJsonObject {{"ok", true}, {"error", QJsonValue()}}; };
    auto path = [&](const char* name) { return directory.filePath(name); };
    auto read = [&](const char* name) { QFile file(path(name)); assert(file.open(QIODevice::ReadOnly)); return QJsonDocument::fromJson(file.readAll()).object(); };
    mailbox.poll(status, execute);
    const auto handshake = read("melonds-controls.json");
    QJsonObject request {{"version", 1}, {"session_id", QString(32, 'a')}, {"instance_id", handshake["instance_id"]},
        {"pid", static_cast<double>(QCoreApplication::applicationPid())}, {"rom_sha256", QString(64, 'c')}, {"sequence", 1},
        {"expires_ms", static_cast<double>(QDateTime::currentMSecsSinceEpoch() + 5000)},
        {"command", "speed"}, {"parameters", QJsonObject {{"value", "x2"}}}};
    auto send = [&](QJsonObject value) { assert(PCECommands::Write(path("melonds-command.json"), value)); mailbox.poll(status, execute); };
    auto wrong = request; wrong["pid"] = -1; send(wrong); assert(calls == 0);
    wrong = request; wrong["session_id"] = QString(32, 'd'); send(wrong); assert(calls == 0);
    wrong = request; wrong["instance_id"] = QString(32, 'e'); send(wrong); assert(calls == 0);
    wrong = request; wrong["rom_sha256"] = QString(64, 'f'); send(wrong); assert(calls == 0);
    wrong = request; wrong["expires_ms"] = 1; send(wrong); assert(calls == 0);
    assert(read("melonds-command-result.json")["error"] == "expired");
    send(request); assert(calls == 0); // expired sequences are consumed, never replayed
    request["sequence"] = 2; send(request); assert(calls == 1);
    assert(read("melonds-command-result.json")["ok"].toBool());
    send(request); assert(calls == 1);
    request["sequence"] = 3;
    assert(PCECommands::Write(path("melonds-command.json"), request));
    int checks = 0;
    auto pending = [&](QString, QJsonObject) { ++checks; return checks == 1 ? QJsonObject {{"pending", true}} : QJsonObject {{"ok", true}}; };
    mailbox.poll(status, pending);
    assert(read("melonds-command-result.json")["sequence"].toInt() == 2);
    mailbox.poll(status, pending);
    assert(read("melonds-command-result.json")["sequence"].toInt() == 3);
    // A transient output failure must not lose an acknowledgement or replay
    // the native action. A directory reliably simulates a blocked replacement.
    assert(QFile::remove(path("melonds-command-result.json")));
    assert(QDir().mkdir(path("melonds-command-result.json")));
    request["sequence"] = 4; send(request); assert(calls == 2);
    mailbox.poll(status, execute); assert(calls == 2);
    assert(QDir().rmdir(path("melonds-command-result.json")));
    mailbox.poll(status, execute); assert(calls == 2);
    assert(read("melonds-command-result.json")["sequence"].toInt() == 4);
    assert(read("melonds-command-result.json")["ok"].toBool());
    QFile stop(path("stop")); assert(stop.open(QIODevice::WriteOnly)); stop.close();
    request["sequence"] = 5; send(request); assert(calls == 2);

    PCEInputPulse pulse;
    pulse.begin(1, 2, 100); // A for two executed frames
    assert(pulse.apply(0xFFD, 100) == 0xFFC); // Physical B remains pressed
    pulse.afterFrame(); assert(pulse.completed == 1 && !pulse.finished);
    assert(pulse.apply(0xFFF, 110) == 0xFFE);
    pulse.afterFrame(); assert(pulse.completed == 2 && !pulse.finished);
    assert(pulse.apply(0xFFD, 120) == 0xFFD); // Virtual A released, physical B preserved
    pulse.afterFrame(); assert(pulse.finished && !pulse.expired);
    pulse.begin(8, 60, 1000);
    assert(pulse.apply(0xFFF, 3000) == 0xFFF);
    pulse.afterFrame(); assert(pulse.finished && pulse.expired && pulse.completed == 0);
    std::cout << "native commands and input pulse ok\n";
}
