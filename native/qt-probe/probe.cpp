// Read-only Qt metadata probe. No invocation, property reads, or input injection.
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QFile>
#include <QGenericPlugin>
#include <QGuiApplication>
#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaMethod>
#include <QMetaProperty>
#include <QQueue>
#include <QSaveFile>
#include <QSet>
#include <QTcpServer>
#include <QTcpSocket>
#include <QThread>
#include <QTimer>
#include <QWindow>

namespace {
constexpr int MaxRequest = 8192;
QJsonObject failure(const QString &code) { return {{"ok", false}, {"error", code}}; }

class Probe : public QObject {
    QTcpServer server;
    QByteArray token;
    QString fingerprint;
public:
    explicit Probe(QObject *parent = nullptr) : QObject(parent) {
        token = qgetenv("DCC_CAPCUT_PROBE_TOKEN");
        QFile binary(QCoreApplication::applicationFilePath());
        if (token.size() < 32 || !binary.open(QIODevice::ReadOnly)) return;
        QCryptographicHash hash(QCryptographicHash::Sha256);
        if (!hash.addData(&binary)) return;
        fingerprint = QString::fromLatin1(hash.result().toHex());
        if (fingerprint != qEnvironmentVariable("DCC_CAPCUT_PROBE_EXE_SHA256")
            || QByteArray(qVersion()) != QByteArray(QT_VERSION_STR)) return;
        if (!server.listen(QHostAddress::LocalHost, 0)) return;
        connect(&server, &QTcpServer::newConnection, this, [this] {
            while (server.hasPendingConnections()) {
                auto socket = server.nextPendingConnection();
                socket->setReadBufferSize(MaxRequest + 1);
                auto timer = new QTimer(socket);
                timer->setSingleShot(true);
                connect(timer, &QTimer::timeout, socket, &QTcpSocket::abort);
                timer->start(3000);
                connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
                connect(socket, &QTcpSocket::readyRead, this, [this, socket] {
                    if (socket->property("handled").toBool()) return;
                    if (socket->bytesAvailable() > MaxRequest) { socket->abort(); return; }
                    if (!socket->canReadLine()) return;
                    socket->setProperty("handled", true);
                    QJsonParseError error;
                    const auto doc = QJsonDocument::fromJson(socket->readLine(), &error);
                    QJsonObject response;
                    if (error.error != QJsonParseError::NoError || !doc.isObject())
                        response = failure("invalid_request");
                    else response = handle(doc.object());
                    socket->write(QJsonDocument(response).toJson(QJsonDocument::Compact) + '\n');
                    socket->disconnectFromHost();
                });
            }
        });
        const auto path = qEnvironmentVariable("DCC_CAPCUT_PROBE_ENDPOINT");
        if (path.isEmpty()) { server.close(); return; }
        QSaveFile file(path);
        if (!file.open(QIODevice::WriteOnly)) { server.close(); return; }
        file.write(QJsonDocument(QJsonObject{{"protocol", 1},
            {"port", server.serverPort()}, {"pid", double(QCoreApplication::applicationPid())},
            {"exe_sha256", fingerprint}, {"qt_version", qVersion()}}).toJson());
        if (!file.commit()) server.close();
    }

    QJsonObject handle(const QJsonObject &request) {
        if (request.value("token").toString().toUtf8() != token) return failure("unauthorized");
        if (request.value("protocol").toInt() != 1
            || request.value("pid").toDouble() != double(QCoreApplication::applicationPid()))
            return failure("host_mismatch");
        if (QThread::currentThread() != QCoreApplication::instance()->thread())
            return failure("wrong_thread");
        const auto operation = request.value("operation").toString();
        QJsonObject result{{"ok", true}, {"protocol", 1}, {"backend", "qt-probe"},
            {"pid", double(QCoreApplication::applicationPid())}, {"exe_sha256", fingerprint},
            {"qt_version", qVersion()}, {"verification_scope", "qt_metadata"}};
        if (operation == "host.describe") {
            result.insert("capabilities", QJsonArray{"host.describe", "qt.inspect"});
            return result;
        }
        if (operation != "qt.inspect") return failure("unsupported_operation");
        const int limit = request.value("max_nodes").toInt(500);
        const int depthLimit = request.value("max_depth").toInt(8);
        if (limit < 1 || limit > 5000 || depthLimit < 0 || depthLimit > 20)
            return failure("invalid_limits");
        struct Entry { QObject *object; int parent; int depth; };
        QQueue<Entry> queue;
        for (auto window : QGuiApplication::allWindows()) queue.enqueue({window, -1, 0});
        QSet<QObject *> seen;
        QJsonArray nodes;
        bool truncated = false;
        while (!queue.isEmpty() && nodes.size() < limit) {
            const auto entry = queue.dequeue();
            auto object = entry.object;
            if (seen.contains(object)) continue;
            seen.insert(object);
            // No event processing or getters: objects cannot disappear during traversal.
            const auto meta = object->metaObject();
            QJsonArray methods, properties;
            for (int i = 0; i < qMin(meta->methodCount(), 128); ++i)
                methods.append(QString::fromLatin1(meta->method(i).methodSignature()));
            for (int i = 0; i < qMin(meta->propertyCount(), 128); ++i)
                properties.append(QString::fromLatin1(meta->property(i).name()));
            const int index = nodes.size();
            nodes.append(QJsonObject{{"id", index}, {"parent", entry.parent},
                {"class_name", QString::fromLatin1(meta->className())},
                {"object_name", object->objectName().left(256)},
                {"methods", methods}, {"properties", properties},
                {"metadata_truncated", meta->methodCount() > 128 || meta->propertyCount() > 128}});
            if (entry.depth < depthLimit) {
                for (auto child : object->children()) {
                    if (queue.size() + nodes.size() >= limit) { truncated = true; break; }
                    queue.enqueue({child, index, entry.depth + 1});
                }
            } else if (!object->children().isEmpty()) truncated = true;
        }
        result.insert("nodes", nodes);
        result.insert("truncated", truncated || !queue.isEmpty());
        return result;
    }
};
}

class ProbePlugin : public QGenericPlugin {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.qt-project.Qt.QGenericPluginFactoryInterface" FILE "probe.json")
public:
    QObject *create(const QString &key, const QString &) override {
        if (key.compare("dcc-capcut-probe", Qt::CaseInsensitive) != 0) return nullptr;
        auto owner = new QObject;
        QTimer::singleShot(0, owner, [owner] { new Probe(owner); });
        return owner;
    }
};
#include "probe.moc"
