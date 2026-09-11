"""Panel device: daftar adb device + tes aksi manual."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.actions.base import HANDLERS, coerce_params, get_spec, specs_by_category

# Label kategori supaya jelas aksi berjalan di mana.
CATEGORY_PREFIX = {"adb": "[HP]", "game": "[GAME]", "host": "[PC]"}
from app.ui.param_form import ParamForm
from app.ui.theme import DANGER, OK, TEXT_DIM


class DevicesPanel(QWidget):
    serial_changed = Signal(str)

    def __init__(self, adb, queue, settings: dict) -> None:
        super().__init__()
        self.adb = adb
        self.queue = queue
        self.settings = settings

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- daftar device
        dev_box = QGroupBox("Device ADB")
        dev_layout = QVBoxLayout(dev_box)

        bar = QHBoxLayout()
        self.adb_label = QLabel()
        self.adb_label.setProperty("class", "hint")
        bar.addWidget(self.adb_label, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        bar.addWidget(refresh)
        dev_layout.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Serial", "Status", "Model"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(160)
        self.table.itemSelectionChanged.connect(self._on_selection)
        dev_layout.addWidget(self.table)

        self.active_label = QLabel("Device aktif: -")
        self.active_label.setStyleSheet("font-weight:bold;")
        dev_layout.addWidget(self.active_label)

        root.addWidget(dev_box)

        # ---- tes aksi manual
        test_box = QGroupBox("Tes aksi manual (langsung, tanpa antrian rule)")
        test_layout = QVBoxLayout(test_box)

        pick = QHBoxLayout()
        pick.addWidget(QLabel("Aksi:"))
        self.action_combo = QComboBox()
        self._fill_actions()
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        pick.addWidget(self.action_combo, 1)

        self.run_button = QPushButton("Jalankan")
        self.run_button.clicked.connect(self._run)
        pick.addWidget(self.run_button)
        test_layout.addLayout(pick)

        self.form = ParamForm()
        test_layout.addWidget(self.form)

        self.result_label = QLabel("-")
        self.result_label.setWordWrap(True)
        test_layout.addWidget(self.result_label)

        root.addWidget(test_box)

        root.addStretch(1)

        self._on_action_changed()

    # ---------------------------------------------------------------- helper

    def _fill_actions(self) -> None:
        self.action_combo.clear()
        for category, specs in sorted(specs_by_category().items()):
            for spec in specs:
                prefix = CATEGORY_PREFIX.get(category, "[PC]")
                warn = " (!)" if spec.dangerous else ""
                self.action_combo.addItem(f"{prefix} {spec.label}{warn}", spec.type)

    def refresh(self) -> None:
        if not self.adb.available:
            self.adb_label.setText("adb TIDAK DITEMUKAN - isi adb.path di config/settings.yaml")
            self.adb_label.setStyleSheet(f"color:{DANGER};")
            self.table.setRowCount(0)
            return

        self.adb_label.setText(f"adb: {self.adb.adb_path}")
        devices = self.adb.list_devices()
        self.table.setRowCount(len(devices))
        for row, dev in enumerate(devices):
            self.table.setItem(row, 0, QTableWidgetItem(dev["serial"]))
            self.table.setItem(row, 1, QTableWidgetItem(dev["state"]))
            self.table.setItem(row, 2, QTableWidgetItem(dev.get("model") or dev.get("device") or ""))
            if dev["serial"] == self.adb.serial:
                self.table.selectRow(row)

        self._update_active()
        if not devices:
            self.result_label.setText("Tidak ada device terhubung. Cek kabel USB / adb connect.")

    def _update_active(self) -> None:
        self.active_label.setText(f"Device aktif: {self.adb.serial or '(otomatis, device pertama)'}")

    def _on_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item and item.text() != self.adb.serial:
            self.serial_changed.emit(item.text())
            self._update_active()

    def _on_action_changed(self) -> None:
        spec = get_spec(self.action_combo.currentData())
        self.form.set_spec(spec)

    def _run(self) -> None:
        action_type = self.action_combo.currentData()
        spec = get_spec(action_type)
        if spec is None:
            return

        # Tes manual sengaja melewati antrian & rule, tapi tetap lewat
        # safety gate supaya PANIC tetap berlaku.
        allowed, reason = self.queue.safety.check_action(action_type)
        if not allowed:
            self.result_label.setText(f"Ditolak: {reason}")
            self.result_label.setStyleSheet(f"color:{DANGER};")
            return

        params = coerce_params(action_type, self.form.values())
        target = self.queue.adb if spec.category == "adb" else self.queue.host
        try:
            result = HANDLERS[action_type](target, params)
        except Exception as exc:                     # noqa: BLE001
            self.result_label.setText(f"Error: {exc}")
            self.result_label.setStyleSheet(f"color:{DANGER};")
            return

        if result.ok:
            self.queue.safety.note_action(action_type)
        self.result_label.setText(
            f"{'OK' if result.ok else 'GAGAL'}: {result.message} ({result.duration_ms}ms)"
        )
        self.result_label.setStyleSheet(f"color:{OK if result.ok else DANGER};")
