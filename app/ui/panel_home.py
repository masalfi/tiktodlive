"""Tab Mulai: daftar langkah persiapan.

Aplikasi ini punya banyak tab, dan pengguna baru tidak tahu harus mulai
dari mana. Tab ini menjawab satu pertanyaan: "apa yang perlu saya lakukan
sekarang?" - lengkap dengan tombol yang langsung membuka tab terkait.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import ACCENT, DANGER, OK, TEXT_DIM, WARN

# Status tiap langkah
SIAP = "siap"
PERLU = "perlu"
OPSIONAL = "opsional"

_ICON = {SIAP: "✓", PERLU: "!", OPSIONAL: "○"}
_COLOR = {SIAP: OK, PERLU: WARN, OPSIONAL: TEXT_DIM}


@dataclass
class Step:
    """Satu baris langkah persiapan."""

    number: int
    title: str
    tab: str                       # nama tab yang dibuka tombolnya
    check: Callable[[], tuple[str, str]]     # -> (status, keterangan)


class StepRow(QWidget):
    open_tab = Signal(str)

    def __init__(self, step: Step) -> None:
        super().__init__()
        self.step = step

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 5, 4, 5)
        layout.setSpacing(10)

        self.icon = QLabel()
        self.icon.setFixedWidth(20)
        self.icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon)

        title = QLabel(f"{step.number}. {step.title}")
        title.setMinimumWidth(190)
        layout.addWidget(title)

        self.detail = QLabel("-")
        self.detail.setWordWrap(False)
        self.detail.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.detail, 1)

        button = QPushButton("Buka")
        button.setToolTip(f"Buka tab {step.tab}")
        button.clicked.connect(lambda: self.open_tab.emit(step.tab))
        layout.addWidget(button)

    def refresh(self) -> str:
        try:
            status, detail = self.step.check()
        except Exception as exc:                    # noqa: BLE001
            status, detail = PERLU, f"tidak bisa diperiksa ({exc})"

        self.icon.setText(_ICON.get(status, "?"))
        self.icon.setStyleSheet(f"color:{_COLOR.get(status, TEXT_DIM)}; font-weight:bold;")
        self.detail.setText(detail)
        self.detail.setStyleSheet(f"color:{_COLOR.get(status, TEXT_DIM)};")
        return status


class HomePanel(QWidget):
    open_tab = Signal(str)

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        # ---- ringkasan
        summary_box = QGroupBox("Status")
        summary_layout = QVBoxLayout(summary_box)
        self.summary = QLabel("memeriksa...")
        self.summary.setProperty("class", "status-big")
        summary_layout.addWidget(self.summary)
        self.summary_hint = QLabel("")
        self.summary_hint.setProperty("class", "hint")
        self.summary_hint.setWordWrap(True)
        summary_layout.addWidget(self.summary_hint)
        root.addWidget(summary_box)

        # ---- langkah
        steps_box = QGroupBox("Langkah persiapan")
        steps_layout = QVBoxLayout(steps_box)
        steps_layout.setSpacing(0)

        self.rows: list[StepRow] = []
        for index, step in enumerate(self._steps()):
            if index:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet(f"color:{TEXT_DIM};")
                steps_layout.addWidget(line)
            row = StepRow(step)
            row.open_tab.connect(self.open_tab.emit)
            steps_layout.addWidget(row)
            self.rows.append(row)
        root.addWidget(steps_box)

        # ---- bantuan singkat
        help_box = QGroupBox("Cara kerjanya")
        help_layout = QVBoxLayout(help_box)
        help_text = QLabel(
            "Penonton mengirim gift atau komentar di TikTok LIVE → aplikasi "
            "mencocokkannya dengan aturan yang kamu buat → aksi dijalankan "
            "di HP (tap, tombol game, reboot) atau di komputer (suara, efek "
            "overlay untuk OBS).\n\n"
            "Tombol merah PANIC di kanan bawah menghentikan semua aksi seketika."
        )
        help_text.setWordWrap(True)
        help_text.setProperty("class", "hint")
        help_layout.addWidget(help_text)
        root.addWidget(help_box)

        root.addStretch(1)
        self.refresh()

    # ------------------------------------------------------------ langkah

    def _steps(self) -> list[Step]:
        return [
            Step(1, "Sambungkan HP Android", "Devices", self._check_device),
            Step(2, "Siapkan scrcpy (opsional)", "scrcpy", self._check_scrcpy),
            Step(3, "Isi akun TikTok", "Koneksi", self._check_account),
            Step(4, "Buat aturan gift", "Rules", self._check_rules),
            Step(5, "Pasang overlay di OBS (opsional)", "Overlay", self._check_overlay),
            Step(6, "Kalibrasi tombol game (opsional)", "Game", self._check_game),
        ]

    def _check_device(self) -> tuple[str, str]:
        w = self.window
        if not w.adb.available:
            return PERLU, "adb belum ada — unduh scrcpy dulu (langkah 2)"
        devices = w.adb.list_devices()
        ready = [d for d in devices if d.get("state") == "device"]
        if not ready:
            if devices:
                return PERLU, "HP terdeteksi tapi belum diizinkan — cek dialog di layar HP"
            return PERLU, "belum ada HP — colok kabel USB & nyalakan USB debugging"
        active = w.adb.serial or ready[0]["serial"]
        model = next((d.get("model") or "" for d in ready if d["serial"] == active), "")
        label = f"{model} ({active})" if model else active
        return SIAP, f"{label.replace('_', ' ')}"

    def _check_scrcpy(self) -> tuple[str, str]:
        path = getattr(self.window.scrcpy_panel, "scrcpy_path", "")
        if not path:
            return PERLU, "belum diunduh — sekali klik, adb ikut di dalamnya"
        return SIAP, "terpasang, siap untuk mirroring layar"

    def _check_account(self) -> tuple[str, str]:
        name = str(self.window.settings["tiktok"]["username"] or "").strip()
        if not name:
            return PERLU, "belum diisi — masukkan nama akun TikTok kamu"
        key = str(self.window.settings["tiktok"]["sign_api_key"] or "").strip()
        if not key:
            return SIAP, f"@{name} — tanpa API key koneksi sering ditolak"
        return SIAP, f"@{name} (API key terpasang)"

    def _check_rules(self) -> tuple[str, str]:
        rules = self.window.rules
        active = [r for r in rules if r.enabled]
        if not rules:
            return PERLU, "belum ada aturan — buat minimal satu"
        if not active:
            return PERLU, f"{len(rules)} aturan, tapi semuanya nonaktif"
        return SIAP, f"{len(active)} aktif dari {len(rules)} aturan"

    def _check_overlay(self) -> tuple[str, str]:
        overlay = self.window.overlay
        if not overlay.running:
            return PERLU, f"server mati: {overlay.error or 'tidak aktif'}"
        count = overlay.client_count
        if not count:
            return OPSIONAL, "server jalan, belum ada Browser Source di OBS"
        channels = ", ".join(sorted(overlay.channels()))
        return SIAP, f"{count} overlay terbuka ({channels})"

    def _check_game(self) -> tuple[str, str]:
        profile = self.window.game_panel.current_profile()
        name = profile.get("name", "?")
        if not profile.get("calibrated"):
            return OPSIONAL, f"{name}: posisi tombol masih perkiraan"
        return SIAP, f"{name}: tombol sudah dikalibrasi"

    # ----------------------------------------------------------- refresh

    def refresh(self) -> None:
        statuses = [row.refresh() for row in self.rows]
        # Langkah wajib = yang bukan opsional dalam judulnya.
        blocking = [
            row.step.title
            for row, status in zip(self.rows, statuses)
            if status == PERLU and "opsional" not in row.step.title.lower()
        ]

        if not blocking:
            self.summary.setText("● Siap dipakai")
            self.summary.setStyleSheet(f"color:{OK};")
            self.summary_hint.setText(
                "Buka tab Koneksi lalu klik Connect untuk mulai menerima gift."
            )
        else:
            self.summary.setText(f"● Perlu {len(blocking)} langkah lagi")
            self.summary.setStyleSheet(f"color:{WARN};")
            self.summary_hint.setText("Yang belum: " + ", ".join(blocking).lower() + ".")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
