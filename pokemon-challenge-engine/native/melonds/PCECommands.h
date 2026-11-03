// SPDX-License-Identifier: GPL-3.0-or-later
// Bounded command mailbox. Only the launched session's first window polls it.
#pragma once
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSaveFile>
#include <QUuid>
#include <functional>
#ifdef _WIN32
#include <windows.h>
#endif

namespace PCECommands {
inline bool PlainPath(const QString& path) {
    QFileInfo item(path);
    if (!item.isAbsolute()) return false;
    while (true) {
        if (item.isSymLink()) return false;
#ifdef _WIN32
        const auto attrs = GetFileAttributesW(reinterpret_cast<LPCWSTR>(item.absoluteFilePath().utf16()));
        if (attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_REPARSE_POINT)) return false;
        if (attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY)) {
            HANDLE handle = CreateFileW(reinterpret_cast<LPCWSTR>(item.absoluteFilePath().utf16()), FILE_READ_ATTRIBUTES,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            if (handle == INVALID_HANDLE_VALUE) return false;
            BY_HANDLE_FILE_INFORMATION info;
            const bool regular = GetFileInformationByHandle(handle, &info) && info.nNumberOfLinks == 1
                && !(info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT);
            CloseHandle(handle);
            if (!regular) return false;
        }
#endif
        const QString parent = item.absolutePath();
        if (parent == item.absoluteFilePath()) break;
        item.setFile(parent);
    }
    return true;
}
inline bool Write(const QString& path, const QJsonObject& object) {
    if (!PlainPath(path)) return false;
    QSaveFile file(path);
    file.setDirectWriteFallback(false);
    const auto data = QJsonDocument(object).toJson(QJsonDocument::Compact);
    return file.open(QIODevice::WriteOnly) && file.write(data) == data.size() && file.commit();
}
class Mailbox {
    const QString directory = qEnvironmentVariable("PCE_BRIDGE_DIR");
    const QString session = qEnvironmentVariable("PCE_BRIDGE_SESSION");
    const QString instance = QUuid::createUuid().toString(QUuid::Id128);
    qint64 lastSequence = 0;
    QJsonObject pendingRequest;
    QJsonObject pendingResult;
public:
    bool enabled() const {
        return PlainPath(directory) && QFileInfo(directory).isDir()
            && QRegularExpression("^[0-9a-f]{32}$").match(session).hasMatch()
            && !QFileInfo::exists(QDir(directory).filePath("stop"));
    }
    void poll(QJsonObject status, const std::function<QJsonObject(QString,QJsonObject)>& execute) {
        if (!enabled()) return;
        const auto path = [&](const char* name) { return QDir(directory).filePath(name); };
        status["version"] = 1;
        status["session_id"] = session;
        status["instance_id"] = instance;
        status["pid"] = static_cast<double>(QCoreApplication::applicationPid());
        status["timestamp_ms"] = static_cast<double>(QDateTime::currentMSecsSinceEpoch());
        Write(path("melonds-controls.json"), status);
        // Windows can transiently deny atomic replacement while a client reads
        // the previous reply. Retry delivery, never the already executed action.
        if (!pendingResult.isEmpty()) {
            if (!Write(path("melonds-command-result.json"), pendingResult)) return;
            pendingResult = QJsonObject();
        }
        auto request = pendingRequest;
        const bool continuing = !request.isEmpty();
        if (!continuing) {
        QFile file(path("melonds-command.json"));
        if (!PlainPath(file.fileName()) || !file.exists() || file.size() > 4096 || !file.open(QIODevice::ReadOnly)) return;
        const auto raw = file.read(4097);
        file.close();
        QJsonParseError parseError;
        const auto document = QJsonDocument::fromJson(raw, &parseError);
        if (parseError.error != QJsonParseError::NoError || !document.isObject()) return;
        request = document.object();
        }
        const auto sequence = request["sequence"].toDouble(-1);
        const auto expires = request["expires_ms"].toDouble(-1);
        const auto now = QDateTime::currentMSecsSinceEpoch();
        if (request.size() != 9 || request["version"].toInt() != 1
            || request["session_id"].toString() != session || request["instance_id"].toString() != instance
            || request["pid"].toDouble() != QCoreApplication::applicationPid()
            || sequence < 1 || sequence > 9007199254740991.0 || sequence != static_cast<qint64>(sequence)
            || (!continuing && sequence <= lastSequence) || request["rom_sha256"] != status["rom_sha256"]
            || !request["parameters"].isObject() || !request["command"].isString()) return;
        lastSequence = static_cast<qint64>(sequence);
        QJsonObject result {{"ok", false}, {"error", "expired"}};
        if (continuing || (expires >= now && expires <= now + 10000))
            result = execute(request["command"].toString(), request["parameters"].toObject());
        if (result["pending"].toBool()) { pendingRequest = request; return; }
        pendingRequest = QJsonObject();
        result["version"] = 1;
        result["session_id"] = session;
        result["instance_id"] = instance;
        result["pid"] = static_cast<double>(QCoreApplication::applicationPid());
        result["sequence"] = sequence;
        result["command"] = request["command"];
        result["timestamp_ms"] = static_cast<double>(QDateTime::currentMSecsSinceEpoch());
        pendingResult = result;
        if (Write(path("melonds-command-result.json"), pendingResult))
            pendingResult = QJsonObject();
    }
};
}
