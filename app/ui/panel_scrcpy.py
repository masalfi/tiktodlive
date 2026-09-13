"""Tab scrcpy: atur mirroring lewat UI, tanpa terminal."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.scrcpy.bridge import (
    BITRATE_CHOICES,
    CODEC_CHOICES,
    FPS_CHOICES,
    MAX_SIZE_CHOICES,
    ORIENTATION_CHOICES,
    ScrcpyOptions,
    disconnect_wireless,
    enable_wireless,
    preview_command,
)
from app.scrcpy.manager import (
    download_scrcpy,
    find_scrcpy,
    platform_label,
    remove_vendor,
)

from app.i18n import tr
from app.scrcpy.runner import ScrcpyRunner
from app.ui.theme import ACCENT, DANGER, OK, TEXT_DIM


class DownloadWorker(QThread):
    """Unduh scrcpy tanpa membekukan UI."""

    progress = Signal(str, int)
    done = Signal(str)          # path
    failed = Signal(str)

    def run(self) -> None:
        try:
            info = download_scrcpy(lambda m, p: self.progress.emit(m, p))
        except Exception as exc:                    # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.done.emit(info.path)


class WirelessWorker(QThread):
    """adb tcpip + connect butuh beberapa detik, jadi di thread terpisah."""

    done = Signal(bool, str)

    def __init__(self, adb, port: int) -> None:
        super().__init__()
        self.adb = adb
        self.port = port

    def run(self) -> None:
        ok, message = enable_wireless(self.adb, self.port)
        self.done.emit(ok, message)


class ScrcpyPanel(QWidget):
    serial_changed = Signal(str)        # saat wireless tersambung
    settings_changed = Signal()
    tools_installed = Signal()          # scrcpy + adb bawaannya baru terpasang

    def __init__(self, adb, settings: dict) -> None:
        super().__init__()
        self.adb = adb
        self.settings = settings
        self.runner = ScrcpyRunner()
        self.options = ScrcpyOptions.from_dict(settings.get("scrcpy", {}).get("options"))

        self._dl_worker: DownloadWorker | None = None
        self._wifi_worker: WirelessWorker | None = None

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        root.addWidget(self._build_status())
        root.addWidget(self._build_tabs(), 1)
        root.addWidget(self._build_launch())

        self.refresh_status()
        self._update_preview()

    # ------------------------------------------------------------ status

    def _build_status(self) -> QWidget:
        box = QGroupBox("scrcpy")
        layout = QHBoxLayout(box)

        self.status_label = QLabel("memeriksa...")
        layout.addWidget(self.status_label, 1)

        self.download_button = QPushButton(tr("Unduh scrcpy"))
        self.download_button.clicked.connect(self._download)
        layout.addWidget(self.download_button)

        self.redownload_button = QPushButton(tr("Unduh ulang"))
        self.redownload_button.clicked.connect(self._redownload)
        layout.addWidget(self.redownload_button)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(200)
        layout.addWidget(self.progress)

        return box

    def refresh_status(self) -> None:
        info = find_scrcpy(self.settings.get("scrcpy", {}).get("path", ""))
        self.scrcpy_path = info.path

        if info.available:
            version = info.version or "terpasang"
            self.status_label.setText(f"{version}  ({info.source})")
            self.status_label.setStyleSheet(f"color:{OK};")
            self.download_button.setVisible(False)
            self.redownload_button.setVisible(info.source == "vendor")
        else:
            self.status_label.setText(
                tr("Belum tersedia untuk {os} - klik 'Unduh scrcpy' (sekali saja)", os=platform_label())
            )
            self.status_label.setStyleSheet(f"color:{TEXT_DIM};")
            self.download_button.setVisible(True)
            self.redownload_button.setVisible(False)

        if hasattr(self, "launch_button"):
            self.launch_button.setEnabled(info.available)
        self._update_preview()

    def _download(self) -> None:
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        self.download_button.setEnabled(False)
        self.redownload_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)

        self._dl_worker = DownloadWorker()
        self._dl_worker.progress.connect(self._on_progress)
        self._dl_worker.done.connect(self._on_downloaded)
        self._dl_worker.failed.connect(self._on_download_failed)
        self._dl_worker.finished.connect(self._on_download_finished)
        self._dl_worker.start()

    def _redownload(self) -> None:
        confirm = QMessageBox.question(
            self, tr("Unduh ulang"),
            tr("Hapus scrcpy yang ada lalu unduh versi terbaru?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.runner.stop_all()
        remove_vendor()
        self.refresh_status()
        self._download()

    def _on_progress(self, message: str, percent: int) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color:{ACCENT};")
        if percent >= 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
        else:
            self.progress.setRange(0, 0)            # tak tentu

    def _on_downloaded(self, path: str) -> None:
        self.settings.setdefault("scrcpy", {})["path"] = ""    # biar auto-detect
        self.settings_changed.emit()
        self.refresh_status()
        # scrcpy membawa adb sendiri; beri tahu agar path adb dipakai ulang.
        self.tools_installed.emit()

    def _on_download_failed(self, message: str) -> None:
        self.status_label.setText(tr("Gagal: {sebab}", sebab=message[:120]))
        self.status_label.setStyleSheet(f"color:{DANGER};")
        QMessageBox.warning(self, tr("Unduhan gagal"), message)

    def _on_download_finished(self) -> None:
        self.progress.setVisible(False)
        self.download_button.setEnabled(True)
        self.redownload_button.setEnabled(True)

    # -------------------------------------------------------------- tabs

    def _build_tabs(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._tab_display(), tr("Tampilan"))
        tabs.addTab(self._tab_window(), tr("Jendela"))
        tabs.addTab(self._tab_device(), tr("Device"))
        tabs.addTab(self._tab_wireless(), tr("Wireless"))
        return tabs

    def _combo(self, choices: list[str], current: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(choices)
        index = combo.findText(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(self._collect)
        return combo

    def _check(self, label: str, checked: bool) -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(checked)
        box.toggled.connect(self._collect)
        return box

    def _tab_display(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        o = self.options

        self.max_size_combo = self._combo(MAX_SIZE_CHOICES, o.max_size)
        form.addRow(tr("Resolusi maks:"), self.max_size_combo)

        self.fps_combo = self._combo(FPS_CHOICES, o.max_fps)
        form.addRow(tr("FPS maks:"), self.fps_combo)

        self.bitrate_combo = self._combo(BITRATE_CHOICES, o.bitrate)
        form.addRow(tr("Bitrate:"), self.bitrate_combo)

        self.codec_combo = self._combo(CODEC_CHOICES, o.codec)
        form.addRow(tr("Codec video:"), self.codec_combo)

        self.orientation_combo = self._combo(ORIENTATION_CHOICES, o.orientation)
        form.addRow(tr("Rotasi tangkapan:"), self.orientation_combo)

        self.crop_edit = QLineEdit(o.crop)
        self.crop_edit.setPlaceholderText(tr("mis. 1224:1440:0:0 (lebar:tinggi:x:y)"))
        self.crop_edit.editingFinished.connect(self._collect)
        form.addRow(tr("Crop:"), self.crop_edit)

        self.no_audio_check = self._check(tr("Tanpa audio (disarankan)"), o.no_audio)
        form.addRow("", self.no_audio_check)

        hint = QLabel(tr("Resolusi & bitrate lebih kecil = lebih ringan dan tidak patah-patah."))
        hint.setProperty("class", "hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return page

    def _tab_window(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        o = self.options

        self.title_edit = QLineEdit(o.window_title)
        self.title_edit.editingFinished.connect(self._collect)
        form.addRow(tr("Judul jendela:"), self.title_edit)

        self.ontop_check = self._check(tr("Selalu di atas jendela lain"), o.always_on_top)
        form.addRow("", self.ontop_check)

        self.fullscreen_check = self._check(tr("Layar penuh"), o.fullscreen)
        form.addRow("", self.fullscreen_check)

        self.borderless_check = self._check(tr("Tanpa bingkai (untuk OBS)"), o.borderless)
        form.addRow("", self.borderless_check)

        size_row = QHBoxLayout()
        self.win_w_spin = QSpinBox(); self.win_w_spin.setRange(0, 4000)
        self.win_w_spin.setValue(o.window_width); self.win_w_spin.setSpecialValueText(tr("otomatis"))
        self.win_w_spin.valueChanged.connect(self._collect)
        self.win_h_spin = QSpinBox(); self.win_h_spin.setRange(0, 4000)
        self.win_h_spin.setValue(o.window_height); self.win_h_spin.setSpecialValueText(tr("otomatis"))
        self.win_h_spin.valueChanged.connect(self._collect)
        size_row.addWidget(self.win_w_spin); size_row.addWidget(QLabel("x")); size_row.addWidget(self.win_h_spin)
        size_row.addStretch(1)
        form.addRow(tr("Ukuran jendela:"), size_row)

        pos_row = QHBoxLayout()
        self.win_x_spin = QSpinBox(); self.win_x_spin.setRange(-1, 4000)
        self.win_x_spin.setValue(o.window_x); self.win_x_spin.setSpecialValueText(tr("otomatis"))
        self.win_x_spin.valueChanged.connect(self._collect)
        self.win_y_spin = QSpinBox(); self.win_y_spin.setRange(-1, 4000)
        self.win_y_spin.setValue(o.window_y); self.win_y_spin.setSpecialValueText(tr("otomatis"))
        self.win_y_spin.valueChanged.connect(self._collect)
        pos_row.addWidget(self.win_x_spin); pos_row.addWidget(QLabel(",")); pos_row.addWidget(self.win_y_spin)
        pos_row.addStretch(1)
        form.addRow(tr("Posisi jendela:"), pos_row)
        return page

    def _tab_device(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        o = self.options

        self.screen_off_check = self._check(tr("Matikan layar HP saat mulai"), o.turn_screen_off)
        form.addRow("", self.screen_off_check)

        self.stay_awake_check = self._check(tr("Cegah HP tidur"), o.stay_awake)
        form.addRow("", self.stay_awake_check)

        self.show_touches_check = self._check(tr("Tampilkan sentuhan di layar HP"), o.show_touches)
        form.addRow("", self.show_touches_check)

        self.power_off_check = self._check(tr("Matikan layar HP saat scrcpy ditutup"), o.power_off_on_close)
        form.addRow("", self.power_off_check)

        self.no_control_check = self._check(tr("Hanya lihat (tidak bisa dikontrol dari PC)"), o.no_control)
        form.addRow("", self.no_control_check)

        self.no_video_check = self._check(tr("Tanpa tampilan (kontrol saja)"), o.no_video)
        form.addRow("", self.no_video_check)

        self.record_edit = QLineEdit(o.record_file)
        self.record_edit.setPlaceholderText(tr("kosongkan kalau tidak merekam, mis. rekaman.mp4"))
        self.record_edit.editingFinished.connect(self._collect)
        form.addRow(tr("Rekam ke file:"), self.record_edit)

        self.extra_edit = QLineEdit(o.extra_args)
        self.extra_edit.setPlaceholderText(tr("argumen scrcpy tambahan, mis. --no-cleanup"))
        self.extra_edit.editingFinished.connect(self._collect)
        form.addRow(tr("Argumen tambahan:"), self.extra_edit)
        return page

    def _tab_wireless(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        info = QLabel(
            tr("Sambungkan HP lewat WiFi supaya tidak perlu kabel.\n\n1. Colok HP dengan kabel USB dulu (sekali saja)\n2. Pastikan HP dan komputer ini satu jaringan WiFi\n3. Klik 'Aktifkan Wireless' di bawah\n4. Setelah tersambung, kabel USB boleh dicabut")
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{TEXT_DIM};")
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Port:")))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(int(self.settings.get("scrcpy", {}).get("wireless_port", 5555)))
        self.port_spin.valueChanged.connect(self._collect)
        row.addWidget(self.port_spin)

        self.wifi_button = QPushButton(tr("Aktifkan Wireless"))
        self.wifi_button.clicked.connect(self._enable_wireless)
        row.addWidget(self.wifi_button)

        self.wifi_disconnect_button = QPushButton(tr("Putuskan"))
        self.wifi_disconnect_button.clicked.connect(self._disconnect_wireless)
        row.addWidget(self.wifi_disconnect_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.wifi_status = QLabel("-")
        self.wifi_status.setWordWrap(True)
        self.wifi_status.setStyleSheet(f"color:{TEXT_DIM};")
        layout.addWidget(self.wifi_status)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ launch

    def _build_launch(self) -> QWidget:
        box = QGroupBox(tr("Jalankan"))
        layout = QVBoxLayout(box)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setProperty("class", "mono")
        layout.addWidget(self.preview_label)

        row = QHBoxLayout()
        self.launch_button = QPushButton(tr("Jalankan scrcpy"))
        self.launch_button.setStyleSheet("font-weight:bold;")
        self.launch_button.clicked.connect(self._launch)
        row.addWidget(self.launch_button)

        self.stop_button = QPushButton(tr("Hentikan"))
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.launch_status = QLabel("-")
        self.launch_status.setWordWrap(True)
        layout.addWidget(self.launch_status)
        return box

    def _collect(self, *_args) -> None:
        """Baca semua widget ke options, lalu simpan + perbarui pratinjau."""
        o = self.options
        o.max_size = self.max_size_combo.currentText()
        o.max_fps = self.fps_combo.currentText()
        o.bitrate = self.bitrate_combo.currentText()
        o.codec = self.codec_combo.currentText()
        o.orientation = self.orientation_combo.currentText()
        o.crop = self.crop_edit.text()
        o.no_audio = self.no_audio_check.isChecked()

        o.window_title = self.title_edit.text()
        o.always_on_top = self.ontop_check.isChecked()
        o.fullscreen = self.fullscreen_check.isChecked()
        o.borderless = self.borderless_check.isChecked()
        o.window_width = self.win_w_spin.value()
        o.window_height = self.win_h_spin.value()
        o.window_x = self.win_x_spin.value()
        o.window_y = self.win_y_spin.value()

        o.turn_screen_off = self.screen_off_check.isChecked()
        o.stay_awake = self.stay_awake_check.isChecked()
        o.show_touches = self.show_touches_check.isChecked()
        o.power_off_on_close = self.power_off_check.isChecked()
        o.no_control = self.no_control_check.isChecked()
        o.no_video = self.no_video_check.isChecked()
        o.record_file = self.record_edit.text()
        o.extra_args = self.extra_edit.text()

        self.settings.setdefault("scrcpy", {})["options"] = o.to_dict()
        self.settings["scrcpy"]["wireless_port"] = self.port_spin.value()
        self.settings_changed.emit()
        self._update_preview()

    def _update_preview(self) -> None:
        if not hasattr(self, "preview_label"):
            return
        command = preview_command(
            getattr(self, "scrcpy_path", "") or "scrcpy", self.options, self.adb.serial
        )
        self.preview_label.setText(command)

    def _launch(self) -> None:
        self._collect()
        ok, message = self.runner.start(
            getattr(self, "scrcpy_path", ""), self.options, self.adb.serial, self.adb.adb_path or ""
        )
        self.launch_status.setText(message)
        self.launch_status.setStyleSheet(f"color:{OK if ok else DANGER};")

    def _stop(self) -> None:
        stopped = self.runner.stop(self.adb.serial)
        self.launch_status.setText(tr("scrcpy dihentikan.") if stopped else tr("Tidak ada yang berjalan."))
        self.launch_status.setStyleSheet(f"color:{TEXT_DIM};")

    # ---------------------------------------------------------- wireless

    def _enable_wireless(self) -> None:
        if not self.adb.available:
            self.wifi_status.setText(tr("adb tidak ditemukan."))
            self.wifi_status.setStyleSheet(f"color:{DANGER};")
            return
        if self._wifi_worker is not None and self._wifi_worker.isRunning():
            return

        self.wifi_button.setEnabled(False)
        self.wifi_status.setText(tr("Mengaktifkan... (butuh beberapa detik)"))
        self.wifi_status.setStyleSheet(f"color:{ACCENT};")

        self._wifi_worker = WirelessWorker(self.adb, self.port_spin.value())
        self._wifi_worker.done.connect(self._on_wireless)
        self._wifi_worker.finished.connect(lambda: self.wifi_button.setEnabled(True))
        self._wifi_worker.start()

    def _on_wireless(self, ok: bool, message: str) -> None:
        if ok:
            self.wifi_status.setText(
                tr("Tersambung: {pesan}\nKabel USB sudah boleh dicabut.", pesan=message)
            )
            self.wifi_status.setStyleSheet(f"color:{OK};")
            self.serial_changed.emit(message)
            self._update_preview()
        else:
            self.wifi_status.setText(message)
            self.wifi_status.setStyleSheet(f"color:{DANGER};")

    def _disconnect_wireless(self) -> None:
        serial = self.adb.serial
        if ":" not in (serial or ""):
            self.wifi_status.setText(tr("Device aktif bukan koneksi wireless."))
            self.wifi_status.setStyleSheet(f"color:{TEXT_DIM};")
            return
        ok, message = disconnect_wireless(self.adb, serial)
        self.wifi_status.setText(message)
        self.wifi_status.setStyleSheet(f"color:{OK if ok else DANGER};")

    def shutdown(self) -> None:
        self.runner.stop_all()
        for worker in (self._dl_worker, self._wifi_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)
