// SPDX-License-Identifier: GPL-3.0-or-later
// PCE addition to melonDS 1.1. Copies bounded RAM ranges after RunFrame.
// No debugger, network listener, RAM write, input injection or save modification.
#pragma once

#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSaveFile>
#include <QString>

#include "NDS.h"
#include "NDSCart.h"
#include "Platform.h"
#include "PCEProfiles.h"

namespace PCEBridge
{
inline void PublishFrame(const melonDS::NDS& nds, int instanceID)
{
    // The application starts one process per run. Other local multiplayer
    // instances must never be allowed to impersonate its cartridge/session.
    if (instanceID != 0)
        return;
    static const QString directory = qEnvironmentVariable("PCE_BRIDGE_DIR");
    static const QString session = qEnvironmentVariable("PCE_BRIDGE_SESSION");
    static const bool enabled = QFileInfo(directory).isAbsolute()
        && QFileInfo(directory).isDir()
        && QRegularExpression("^[0-9a-f]{32}$").match(session).hasMatch();
    if (!enabled)
        return;
    static QElapsedTimer timer;
    static quint64 sequence = 0;
    if (timer.isValid() && timer.elapsed() < 200)
        return;
    timer.start();
    if (QFileInfo::exists(QDir(directory).filePath("stop")))
        return;
    const auto* cart = nds.GetNDSCart();
    if (!cart || cart->GetROMLength() < 512 || !nds.MainRAM)
        return;
    const auto* rom = cart->GetROM();
    const auto* ram = nds.MainRAM;
    const auto ramMask = nds.MainRAMMask;
    const QString code = QString::fromLatin1(reinterpret_cast<const char*>(rom + 12), 4);
    const QString ramCode = QString::fromLatin1(
        reinterpret_cast<const char*>(ram + (0x027FFE0C & ramMask)), 4);
    const int revision = rom[30];
    const int ramRevision = ram[0x027FFE1E & ramMask];
    const Profile* profile = nullptr;
    for (const auto& candidate : Profiles)
        if (code == QLatin1String(candidate.code) && revision == candidate.revision)
            profile = &candidate;

    QJsonObject frame {
        {"bridge_version", "1.1-pce.1"},
        {"source_revision", "b86390e4428bf38ce4c1ce0e9ca446d6d25955e8"},
        {"session_id", session}, {"sequence", static_cast<double>(++sequence)},
        {"timestamp", static_cast<double>(QDateTime::currentSecsSinceEpoch())},
        {"console_type", nds.ConsoleType}, {"rom_code", code}, {"rom_revision", revision},
        {"ram_code", ramCode}, {"ram_revision", ramRevision},
        {"memory_profile", profile ? QJsonValue(profile->id) : QJsonValue()},
        {"party_count", QJsonValue()}, {"party_hex", QJsonValue()},
        {"map_id", QJsonValue()}, {"status", "unsupported"}
    };
    // MainRAMMask is a source-defined guest-address mirror; no host offset or
    // pointer scanning is involved. DSi layouts are deliberately not supported.
    if (profile && nds.ConsoleType == 0 && ramMask == 0x003FFFFF
        && code == ramCode && revision == ramRevision)
    {
        const int count = ram[profile->countAddress & ramMask];
        frame["party_count"] = count;
        if (count == 0)
            frame["status"] = "not_ready";
        else if (count > 6)
            frame["status"] = "invalid_data";
        else
        {
            frame["status"] = "ok";
            const QByteArray party(reinterpret_cast<const char*>(ram + (profile->partyAddress & ramMask)), count * 220);
            frame["party_hex"] = QString::fromLatin1(party.toHex());
            if (profile->mapAddress)
            {
                const auto offset = profile->mapAddress & ramMask;
                frame["map_id"] = ram[offset] | (ram[offset + 1] << 8);
            }
        }
    }
    QSaveFile output(QDir(directory).filePath("melonds-frame.json"));
    // A failed atomic replace must not degrade to overwriting a visible file.
    output.setDirectWriteFallback(false);
    const auto data = QJsonDocument(frame).toJson(QJsonDocument::Compact);
    if (!output.open(QIODevice::WriteOnly) || output.write(data) != data.size() || !output.commit())
        melonDS::Platform::Log(melonDS::Platform::LogLevel::Warn, "PCE: unable to publish frame snapshot\n");
}
}
