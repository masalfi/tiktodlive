"""Entry point TikTok Live Controller."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.config import load_settings
from app.i18n import load_language
from app.ui.main_window import MainWindow
from app.ui.theme import apply_font, build_stylesheet


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # TikTokLive cukup berisik di level INFO.
    logging.getLogger("TikTokLive").setLevel(logging.WARNING)

    # Kebijakan DPI harus diset SEBELUM QApplication dibuat, kalau tidak
    # diabaikan. PassThrough menjaga skala pecahan (mis. 125%/150% di
    # Windows) tetap tajam, bukan dibulatkan jadi kabur.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    # Bahasa dimuat sebelum jendela dibangun, karena teksnya dipasang
    # saat widget dibuat.
    load_language(str(load_settings().get("language") or "id"))

    app.setApplicationName("TikTok Live Controller")
    app.setApplicationDisplayName("TikTok Live Controller")

    # Fusion memberi dasar yang identik di macOS & Windows. Tanpa ini, style
    # bawaan tiap OS menimpa sebagian stylesheet dengan cara berbeda.
    app.setStyle("Fusion")

    apply_font(app)
    # Dibangun setelah font terpasang supaya ukurannya sesuai platform.
    app.setStyleSheet(build_stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
