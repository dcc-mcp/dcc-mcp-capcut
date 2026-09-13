#include <QGuiApplication>
#include <QWindow>
#include <QTimer>

int main(int argc, char **argv) {
    QGuiApplication app(argc, argv);
    QWindow window;
    window.setObjectName("probeFixtureWindow");
    QObject track(&window);
    track.setObjectName("fixtureTrack");
    QTimer::singleShot(60000, &app, &QCoreApplication::quit);
    return app.exec();
}
