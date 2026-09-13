"""Panel koneksi: username, status live, dan pengaturan dasar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QMessageBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import QThread

from app.live.client import (
    STATE_CONNECTING,
    STATE_DISCONNECTED,
    STATE_ERROR,
    STATE_LIVE,
    clean_username,
)

from app.i18n import tr
from app.i18n import available_languages, current_language, tr
from app.live.signcheck import fetch_rate_limits, format_rate_limits, is_exhausted
from app.ui.theme import ACCENT, DANGER, OK, TEXT_DIM

_COLORS = {
    STATE_DISCONNECTED: (TEXT_DIM, "Belum terhubung"),
    STATE_CONNECTING: ("#e0a52e", "Menyambung..."),
    STATE_LIVE: (OK, "● LIVE"),
    STATE_ERROR: (DANGER, "Error"),
}


class QuotaWorker(QThread):
    """Cek kuota sign server tanpa membekukan GUI."""

    done = Signal(str, bool)        # pesan, habis?
    failed = Signal(str)

    def __init__(self, api_key: str = "") -> None:
        super().__init__()
        self.api_key = api_key

    def run(self) -> None:
        try:
            data = fetch_rate_limits(self.api_key)
        except Exception as exc:                    # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.done.emit(format_rate_limits(data), is_exhausted(data))


class ConnectPanel(QWidget):
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    settings_changed = Signal()

    def __init__(self, settings: dict) -> None:
        super().__init__()
        self.settings = settings
        self._connected = False
        self._quota_worker: QuotaWorker | None = None

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- koneksi
        box = QGroupBox(tr("Koneksi TikTok LIVE"))
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.username_edit = QLineEdit(settings["tiktok"]["username"])
        self.username_edit.setPlaceholderText(tr("nama akun TikTok \u2014 boleh tempel link profilnya"))
        self.username_edit.returnPressed.connect(self._toggle)
        # Rapikan begitu user selesai mengetik, supaya dia melihat sendiri
        # bentuk yang benar-benar dipakai.
        self.username_edit.editingFinished.connect(self._tidy_username)
        row.addWidget(self.username_edit, 1)

        self.connect_button = QPushButton(tr("Connect"))
        self.connect_button.setMinimumWidth(130)
        self.connect_button.clicked.connect(self._toggle)
        row.addWidget(self.connect_button)
        form.addRow(tr("Username:"), row)

        self.status_dot = QLabel(tr("Belum terhubung"))
        self.status_dot.setProperty("class", "status-big")
        self.status_dot.setStyleSheet(f"color:{TEXT_DIM};")
        form.addRow(tr("Status:"), self.status_dot)

        self.detail_label = QLabel("-")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(f"color:{TEXT_DIM};")
        form.addRow(tr("Info:"), self.detail_label)

        self.viewer_label = QLabel("-")
        form.addRow(tr("Penonton / like:"), self.viewer_label)

        self.events_label = QLabel("0")
        self.events_label.setStyleSheet(f"color:{ACCENT}; font-weight:bold;")
        form.addRow(tr("Event diterima:"), self.events_label)

        root.addWidget(box)

        # ---- pengaturan
        opt_box = QGroupBox(tr("Pengaturan"))
        opt_form = QFormLayout(opt_box)

        self.language_combo = QComboBox()
        for code, name in available_languages().items():
            self.language_combo.addItem(name, code)
        index = self.language_combo.findData(current_language())
        self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        opt_form.addRow(tr("Bahasa:"), self.language_combo)

        self.backend_combo = QComboBox()
        self.backend_combo.addItem(tr("Otomatis (pakai API key kalau ada)"), "auto")
        self.backend_combo.addItem(tr("EulerStream - butuh API key"), "eulerstream")
        self.backend_combo.addItem(tr("TikTokLive - koneksi langsung"), "tiktoklive")
        idx = self.backend_combo.findData(settings["tiktok"].get("backend", "auto"))
        self.backend_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.backend_combo.currentIndexChanged.connect(self._emit_settings_changed)
        opt_form.addRow(tr("Backend:"), self.backend_combo)

        self.sign_key_edit = QLineEdit(settings["tiktok"]["sign_api_key"])
        self.sign_key_edit.setPlaceholderText(tr("opsional - EulerStream API key untuk naikkan rate limit"))
        self.sign_key_edit.setEchoMode(QLineEdit.Password)
        self.sign_key_edit.editingFinished.connect(self.settings_changed.emit)
        opt_form.addRow(tr("Sign API key:"), self.sign_key_edit)

        self.reconnect_check = QCheckBox(tr("Sambung ulang otomatis kalau terputus"))
        self.reconnect_check.setChecked(bool(settings["tiktok"]["auto_reconnect"]))
        self.reconnect_check.toggled.connect(self._emit_settings_changed)
        opt_form.addRow("", self.reconnect_check)

        self.max_queue_spin = QSpinBox()
        self.max_queue_spin.setRange(1, 500)
        self.max_queue_spin.setValue(int(settings["safety"]["max_queue"]))
        self.max_queue_spin.valueChanged.connect(self._emit_settings_changed)
        opt_form.addRow(tr("Maks antrian:"), self.max_queue_spin)

        self.reboot_cap_spin = QSpinBox()
        self.reboot_cap_spin.setRange(0, 20)
        self.reboot_cap_spin.setValue(int(settings["safety"]["reboot_max_per_hour"]))
        self.reboot_cap_spin.valueChanged.connect(self._emit_settings_changed)
        opt_form.addRow(tr("Maks reboot / jam:"), self.reboot_cap_spin)

        quota_row = QHBoxLayout()
        self.quota_label = QLabel("-")
        self.quota_label.setProperty("class", "hint")
        quota_row.addWidget(self.quota_label, 1)
        self.quota_button = QPushButton(tr("Cek kuota"))
        self.quota_button.clicked.connect(self.check_quota)
        quota_row.addWidget(self.quota_button)
        opt_form.addRow(tr("Sign server:"), quota_row)

        note = QLabel(
            tr("Batas reboot adalah pengaman keras - rule tidak bisa melewatinya.\nPerubahan berlaku setelah aplikasi dijalankan ulang.")
        )
        note.setProperty("class", "hint")
        opt_form.addRow("", note)

        root.addWidget(opt_box)
        root.addStretch(1)

    # ------------------------------------------------------------------ API

    def _on_language_changed(self, *_args) -> None:
        """Bahasa dipasang saat widget dibuat, jadi perubahannya baru
        terlihat setelah aplikasi dijalankan ulang."""
        code = self.language_combo.currentData()
        if not code or code == current_language():
            return
        self.settings["language"] = code
        self.settings_changed.emit()
        QMessageBox.information(
            self,
            tr("Bahasa"),
            tr("Bahasa akan berubah setelah aplikasi dijalankan ulang."),
        )

    def _tidy_username(self) -> None:
        cleaned = clean_username(self.username_edit.text())
        if cleaned != self.username_edit.text():
            self.username_edit.setText(cleaned)

    def _emit_settings_changed(self, *_args) -> None:
        """Penampung untuk sinyal Qt yang membawa argumen (int/bool).

        settings_changed sengaja tanpa argumen; menyambungkannya langsung ke
        currentIndexChanged/toggled/valueChanged memicu TypeError saat sinyal
        itu benar-benar dipancarkan.
        """
        self.settings_changed.emit()

    def _toggle(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit(clean_username(self.username_edit.text()))

    def set_connecting(self) -> None:
        self.set_state(STATE_CONNECTING, "Menyambung...")

    def set_state(self, state: str, message: str) -> None:
        color, label = _COLORS.get(state, _COLORS[STATE_DISCONNECTED])
        self.status_dot.setText(label)
        self.status_dot.setStyleSheet(f"color:{color};")
        self.detail_label.setText(message or "-")

        self._connected = state in (STATE_LIVE, STATE_CONNECTING)
        self.connect_button.setText(tr("Disconnect") if self._connected else "Connect")
        self.username_edit.setEnabled(not self._connected)

    def set_event_count(self, count: int) -> None:
        self.events_label.setText(f"{count:,}".replace(",", "."))

    def set_viewer_count(self, count: int) -> None:
        self.viewer_label.setText(f"{count:,}".replace(",", "."))

    def check_quota(self) -> None:
        if self._quota_worker is not None and self._quota_worker.isRunning():
            return
        self.quota_button.setEnabled(False)
        self.quota_label.setText("mengecek...")

        self._quota_worker = QuotaWorker(self.sign_key_edit.text().strip())
        self._quota_worker.done.connect(self._on_quota)
        self._quota_worker.failed.connect(
            lambda msg: self.quota_label.setText(tr("gagal cek: {sebab}", sebab=msg[:60]))
        )
        self._quota_worker.finished.connect(lambda: self.quota_button.setEnabled(True))
        self._quota_worker.start()

    def _on_quota(self, message: str, exhausted: bool) -> None:
        self.quota_label.setText(message)
        self.quota_label.setStyleSheet(
            f"color:{DANGER if exhausted else TEXT_DIM};"
        )

    def closeEvent(self, event) -> None:
        if self._quota_worker is not None and self._quota_worker.isRunning():
            self._quota_worker.wait(3000)
        super().closeEvent(event)

    def apply_to_settings(self, settings: dict) -> None:
        settings["language"] = self.language_combo.currentData() or "id"
        settings["tiktok"]["username"] = clean_username(self.username_edit.text())
        settings["tiktok"]["sign_api_key"] = self.sign_key_edit.text().strip()
        settings["tiktok"]["auto_reconnect"] = self.reconnect_check.isChecked()
        settings["tiktok"]["backend"] = self.backend_combo.currentData()
        settings["safety"]["max_queue"] = self.max_queue_spin.value()
        settings["safety"]["reboot_max_per_hour"] = self.reboot_cap_spin.value()
