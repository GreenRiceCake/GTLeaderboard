import sys
import argparse

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from .application import configure_app
from .ui import MainWindow


def main():
    parser = argparse.ArgumentParser(description="GTLeaderboard")
    parser.add_argument("--self-test", metavar="REPORT_JSON")
    parser.add_argument("--ocr-images", nargs="*", default=[])
    parser.add_argument('league_file', nargs='?', help='실행 시 열 PNG 또는 GTLB')
    args = parser.parse_args()
    app = QApplication(sys.argv)
    configure_app(app)
    if args.self_test:
        from .diagnostics import self_test
        return self_test(app, args.self_test, args.ocr_images)
    window = MainWindow()
    window.enable_session()
    if args.league_file:
        window.load_path(args.league_file, check_save=False)
    window.show()
    from .update_ui import StartupUpdateCheck
    window.update_check = StartupUpdateCheck(window)
    app.aboutToQuit.connect(window.update_check.stop)
    def startup():
        if not args.league_file:
            window.offer_recovery()
        window.update_check.schedule()
    QTimer.singleShot(0, startup)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
