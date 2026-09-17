import os
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase


def configure_app(app):
    app.setApplicationName("GTLeaderboard")
    app.setStyle("Fusion")
    # The offscreen Windows backend doesn't discover system fonts automatically.
    directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("malgun.ttf", "malgunbd.ttf"):
        path = directory / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Malgun Gothic", 10))
