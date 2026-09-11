"""Tab Game: kalibrasi posisi tombol dengan mengklik screenshot device.

Koordinat tombol game tidak bisa ditebak dari internet - Mobile Legends
mengizinkan pemain memindahkan tombolnya, dan posisinya berubah mengikuti
resolusi. Jadi cara paling andal: ambil screenshot layar HP saat game
terbuka, lalu klik tombolnya di sini.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config import active_profile, load_games, save_games
from app.ui.theme import ACCENT, DANGER, OK, TEXT_DIM, WARN


class ScreenshotWorker(QThread):
    """Ambil screenshot lewat adb tanpa membekukan UI."""

    done = Signal(bytes)
    failed = Signal(str)

    def __init__(self, adb) -> None:
        super().__init__()
        self.adb = adb

    def run(self) -> None:
        try:
            proc = self.adb.run(["exec-out", "screencap", "-p"], binary=True, timeout=25)
        except Exception as exc:                    # noqa: BLE001
            self.failed.emit(str(exc))
            return
        if proc.returncode != 0 or not proc.stdout:
            self.failed.emit((proc.stderr or b"").decode(errors="replace")[:200] or "screencap gagal")
            return
        self.done.emit(bytes(proc.stdout))


class ScreenView(QLabel):
    """Menampilkan screenshot dan melaporkan klik sebagai persentase."""

    clicked = Signal(float, float)      # x, y dalam 0.0-1.0

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(240)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setText("Klik 'Ambil Screenshot' saat game sudah terbuka di HP.")
        self._pixmap: QPixmap | None = None
        self._markers: dict[str, tuple[float, float]] = {}
        self._highlight = ""

    def set_image(self, data: bytes) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return False
        self._pixmap = pixmap
        self.update()
        return True

    def image_size(self):
        """Ukuran screenshot. Ini mencerminkan rotasi NYATA layar HP,
        berbeda dengan `wm size` yang selalu melaporkan ukuran fisik."""
        if self._pixmap is None or self._pixmap.isNull():
            return None
        return self._pixmap.width(), self._pixmap.height()

    def set_markers(self, markers: dict[str, tuple[float, float]], highlight: str = "") -> None:
        self._markers = markers
        self._highlight = highlight
        self.update()

    def _draw_rect(self) -> QRect | None:
        """Area gambar sesungguhnya di dalam label (menjaga rasio)."""
        if self._pixmap is None or self._pixmap.isNull():
            return None
        scaled = self._pixmap.size().scaled(self.size(), Qt.KeepAspectRatio)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return QRect(QPoint(x, y), scaled)

    def paintEvent(self, event) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            super().paintEvent(event)
            return

        rect = self._draw_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(rect, self._pixmap)

        # Tombol yang posisinya sama (mis. skill3 & ultimate) akan
        # bertumpuk; label digeser ke bawah supaya keduanya tetap terbaca.
        seen: dict[tuple[int, int], int] = {}
        highlight_last = sorted(self._markers.items(), key=lambda kv: kv[0] == self._highlight)

        for name, (px, py) in highlight_last:
            cx = rect.x() + int(px * rect.width())
            cy = rect.y() + int(py * rect.height())
            active = name == self._highlight
            color = QColor(ACCENT) if active else QColor(255, 255, 255, 190)
            radius = 14 if active else 10

            painter.setPen(QPen(color, 3 if active else 2))
            painter.drawEllipse(QPoint(cx, cy), radius, radius)

            key = (cx // 8, cy // 8)
            stack = seen.get(key, 0)
            seen[key] = stack + 1

            metrics = painter.fontMetrics()
            text_w = metrics.horizontalAdvance(name)
            # Dekat tepi kanan, tulis label di sebelah kiri lingkaran.
            if cx + radius + 6 + text_w > rect.right():
                tx = cx - radius - 6 - text_w
            else:
                tx = cx + radius + 6
            ty = cy + 4 + stack * (metrics.height() + 1)
            painter.drawText(tx, ty, name)
        painter.end()

    def mousePressEvent(self, event) -> None:
        rect = self._draw_rect()
        if rect is None or not rect.contains(event.pos()):
            return
        px = (event.pos().x() - rect.x()) / max(1, rect.width())
        py = (event.pos().y() - rect.y()) / max(1, rect.height())
        self.clicked.emit(round(px, 4), round(py, 4))


class GamePanel(QWidget):
    profile_changed = Signal()

    def __init__(self, adb, queue) -> None:
        super().__init__()
        self.adb = adb
        self.queue = queue
        self.games = load_games()
        self._worker: ScreenshotWorker | None = None

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        root.addWidget(self._build_top())
        root.addWidget(self._build_guide())

        body = QHBoxLayout()
        body.addWidget(self._build_buttons(), 0)
        body.addWidget(self._build_view(), 1)
        root.addLayout(body, 1)

        self.result_label = QLabel("-")
        self.result_label.setWordWrap(True)
        root.addWidget(self.result_label)

        self._reload_profiles()

    # --------------------------------------------------------------- atas

    def _build_top(self) -> QWidget:
        box = QGroupBox("Profil game")
        layout = QHBoxLayout(box)

        layout.addWidget(QLabel("Game:"))
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        layout.addWidget(self.profile_combo, 1)

        self.shot_button = QPushButton("Ambil Screenshot")
        self.shot_button.setToolTip("Buka game di HP dulu, lalu klik ini")
        self.shot_button.clicked.connect(self._take_screenshot)
        layout.addWidget(self.shot_button)

        self.open_button = QPushButton("Buka game")
        self.open_button.setToolTip("Jalankan game di HP lewat adb")
        self.open_button.clicked.connect(self._open_game)
        layout.addWidget(self.open_button)

        self.status_label = QLabel("-")
        layout.addWidget(self.status_label)
        return box

    def _build_guide(self) -> QWidget:
        box = QGroupBox("Cara kalibrasi")
        layout = QVBoxLayout(box)
        layout.setSpacing(4)

        steps = QLabel(
            "1. Buka game di HP sampai MASUK PERTANDINGAN (layar mendatar)\n"
            "2. Klik Ambil Screenshot  →  3. Pilih tombol di kiri  →  "
            "4. Klik posisinya di gambar  →  5. Tes tekan  →  6. Simpan"
        )
        steps.setWordWrap(True)
        steps.setProperty("class", "hint")
        layout.addWidget(steps)

        self.orientation_label = QLabel("-")
        layout.addWidget(self.orientation_label)
        return box

    # ------------------------------------------------------------ tombol

    def _build_buttons(self) -> QWidget:
        box = QGroupBox("Tombol")
        box.setMaximumWidth(260)
        layout = QVBoxLayout(box)

        self.button_list = QListWidget()
        self.button_list.currentItemChanged.connect(self._on_button_selected)
        layout.addWidget(self.button_list, 1)

        hint = QLabel("Pilih tombol, lalu klik posisinya di screenshot.")
        hint.setWordWrap(True)
        hint.setProperty("class", "hint")
        layout.addWidget(hint)

        row = QHBoxLayout()
        test = QPushButton("Tes tekan")
        test.setToolTip("Kirim tap ke HP untuk memastikan posisinya benar")
        test.clicked.connect(self._test_button)
        row.addWidget(test)

        save = QPushButton("Simpan")
        save.clicked.connect(self._save_profile)
        row.addWidget(save)
        layout.addLayout(row)
        return box

    def _build_view(self) -> QWidget:
        box = QGroupBox("Layar HP")
        layout = QVBoxLayout(box)
        self.view = ScreenView()
        self.view.clicked.connect(self._on_view_clicked)
        layout.addWidget(self.view, 1)
        return box

    # ------------------------------------------------------------- profil

    def _reload_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for key, profile in (self.games.get("profiles") or {}).items():
            self.profile_combo.addItem(profile.get("name", key), key)
        index = self.profile_combo.findData(self.games.get("active"))
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)
        self._on_profile_changed()

    def current_key(self) -> str:
        return self.profile_combo.currentData() or ""

    def current_profile(self) -> dict:
        return (self.games.get("profiles") or {}).get(self.current_key(), {})

    def _on_profile_changed(self, *_args) -> None:
        self.games["active"] = self.current_key()
        profile = self.current_profile()

        self.button_list.blockSignals(True)
        self.button_list.clear()
        for name in sorted(profile.get("buttons") or {}):
            self.button_list.addItem(QListWidgetItem(name))
        self.button_list.blockSignals(False)
        if self.button_list.count():
            self.button_list.setCurrentRow(0)

        calibrated = bool(profile.get("calibrated"))
        if calibrated:
            self.status_label.setText("sudah dikalibrasi")
            self.status_label.setStyleSheet(f"color:{OK};")
        else:
            self.status_label.setText("belum dikalibrasi (posisi masih perkiraan)")
            self.status_label.setStyleSheet(f"color:{WARN};")

        self._refresh_markers()
        self.refresh_orientation()
        self.profile_changed.emit()

    def refresh_orientation(self) -> None:
        """Tunjukkan orientasi HP sekarang vs orientasi profil.

        Ketidakcocokan di sini adalah penyebab tersering tap meleset -
        `wm size` tidak menunjukkannya, jadi harus ditampilkan terang.
        """
        if not hasattr(self, "orientation_label"):
            return
        if not self.adb.available:
            self.orientation_label.setText("adb belum tersedia.")
            self.orientation_label.setStyleSheet(f"color:{TEXT_DIM};")
            return

        from app.actions.game import current_rotation, screen_awake

        rotation = current_rotation(self.adb)
        if rotation is None:
            self.orientation_label.setText("HP tidak terbaca — cek koneksi di tab Devices.")
            self.orientation_label.setStyleSheet(f"color:{DANGER};")
            return

        now_landscape = rotation in (1, 3)
        want_landscape = bool(self.current_profile().get("landscape", True))
        now_text = "mendatar" if now_landscape else "tegak"
        want_text = "mendatar" if want_landscape else "tegak"

        if screen_awake(self.adb) is False:
            self.orientation_label.setText(
                "Layar HP mati / terkunci — buka kuncinya dulu."
            )
            self.orientation_label.setStyleSheet(f"color:{WARN};")
        elif now_landscape == want_landscape:
            self.orientation_label.setText(f"HP sekarang {now_text} — cocok dengan profil.")
            self.orientation_label.setStyleSheet(f"color:{OK};")
        else:
            self.orientation_label.setText(
                f"HP sekarang {now_text}, profil ini untuk layar {want_text}. "
                f"Putar HP atau buka gamenya dulu."
            )
            self.orientation_label.setStyleSheet(f"color:{WARN};")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_orientation()

    def _refresh_markers(self) -> None:
        buttons = self.current_profile().get("buttons") or {}
        markers = {
            name: (float(v.get("x", 0)), float(v.get("y", 0)))
            for name, v in buttons.items()
            if isinstance(v, dict)
        }
        item = self.button_list.currentItem()
        self.view.set_markers(markers, item.text() if item else "")

    def _on_button_selected(self, *_args) -> None:
        self._refresh_markers()

    # -------------------------------------------------------- screenshot

    def _take_screenshot(self) -> None:
        if not self.adb.available:
            self._report(False, "adb tidak ditemukan.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.shot_button.setEnabled(False)
        self._report(True, "Mengambil screenshot...")

        self._worker = ScreenshotWorker(self.adb)
        self._worker.done.connect(self._on_screenshot)
        self._worker.failed.connect(lambda m: self._report(False, f"Gagal: {m}"))
        self._worker.finished.connect(lambda: self.shot_button.setEnabled(True))
        self._worker.start()

    def _on_screenshot(self, data: bytes) -> None:
        if not self.view.set_image(data):
            self._report(False, "Screenshot tidak bisa dibaca.")
            return
        self._refresh_markers()

        shot = self.view.image_size()
        orientation = "mendatar" if shot and shot[0] > shot[1] else "tegak"
        notes = [f"Screenshot {shot[0]}x{shot[1]} ({orientation})." if shot else "Screenshot diambil."]

        # Game MOBA dimainkan mendatar; kalibrasi dari layar tegak hampir
        # pasti salah, jadi peringatkan sebelum user menghabiskan waktu.
        if shot and shot[0] <= shot[1]:
            notes.append(
                "HP sedang TEGAK - kalau ini game mendatar, buka gamenya dulu "
                "sampai masuk pertandingan, baru ambil screenshot lagi."
            )
        notes.append("Pilih tombol di kiri, lalu klik posisinya.")
        self._report(True, " ".join(notes))
        self.refresh_orientation()

    def _open_game(self) -> None:
        package = str(self.current_profile().get("package") or "").strip()
        if not package:
            self._report(False, "Profil ini belum punya nama package.")
            return
        try:
            proc = self.adb.run(
                ["shell", "monkey", "-p", package, "-c",
                 "android.intent.category.LAUNCHER", "1"], timeout=20)
        except Exception as exc:                    # noqa: BLE001
            self._report(False, f"Gagal membuka game: {exc}")
            return
        ok = proc.returncode == 0
        self._report(ok, f"{package} dibuka" if ok else "Gagal membuka game (package benar?)")

    # -------------------------------------------------------- kalibrasi

    def _on_view_clicked(self, px: float, py: float) -> None:
        item = self.button_list.currentItem()
        if item is None:
            self._report(False, "Pilih dulu tombol yang mau dikalibrasi di daftar kiri.")
            return
        name = item.text()
        profile = self.current_profile()
        profile.setdefault("buttons", {})[name] = {"x": px, "y": py}
        profile["calibrated"] = True
        # Orientasi diambil dari SCREENSHOT, bukan `wm size`. `wm size`
        # selalu melaporkan ukuran fisik (mis. 1080x2280) walau HP sedang
        # mendatar, sehingga profil bisa tersimpan dengan orientasi salah
        # dan semua tap meleset.
        shot = self.view.image_size()
        if shot:
            profile["landscape"] = shot[0] > shot[1]
            profile["calib_size"] = f"{shot[0]}x{shot[1]}"

        self._refresh_markers()
        self._report(True, f"'{name}' disetel ke {px:.3f}, {py:.3f} — klik Simpan untuk menyimpan.")

    def _screen_size(self):
        from app.actions.game import screen_size

        return screen_size(self.adb)

    def _test_button(self) -> None:
        item = self.button_list.currentItem()
        if item is None:
            self._report(False, "Pilih tombol dulu.")
            return
        from app.actions.base import HANDLERS, coerce_params
        from app.actions.game import screen_awake

        # Layar mati / HP terkunci = tap terkirim tapi tidak ada efeknya.
        # Tanpa peringatan ini, aksinya terlihat "berhasil" padahal tidak.
        if screen_awake(self.adb) is False:
            self._report(False,
                         "Layar HP mati atau terkunci - buka kuncinya dulu, "
                         "kalau tidak tap tidak akan terlihat efeknya.")
            return

        # Pakai profil yang sedang diedit, bukan yang tersimpan di disk.
        self.adb.game_profile = self.current_profile()
        result = HANDLERS["game.tap_button"](
            self.adb, coerce_params("game.tap_button", {"button": item.text()})
        )
        self._report(result.ok, result.message)

    def _save_profile(self) -> None:
        try:
            save_games(self.games)
        except OSError as exc:
            self._report(False, f"Gagal menyimpan: {exc}")
            return
        self._report(True, "Profil disimpan ke config/game_profiles.yaml")
        self.profile_changed.emit()

    def _report(self, ok: bool, message: str) -> None:
        self.result_label.setText(message)
        self.result_label.setStyleSheet(f"color:{OK if ok else DANGER};")

    def shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
