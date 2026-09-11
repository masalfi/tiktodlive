"""Dialog editor rule: kondisi dinamis + daftar aksi yang bisa diurutkan."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.actions.base import get_spec, specs_by_category

# Label kategori supaya jelas aksi berjalan di mana.
CATEGORY_PREFIX = {"adb": "[HP]", "game": "[GAME]", "host": "[PC]"}
from app.engine.rules import COMMON_CONDITIONS, CONDITION_SPECS
from app.models import Action, Rule
from app.ui.gift_picker import GiftPicker
from app.ui.param_form import ParamForm
from app.ui.theme import DANGER, OK, TEXT_DIM

EVENT_LABELS = {
    "gift": "Gift",
    "comment": "Komentar",
    "like": "Like",
    "follow": "Follow",
    "share": "Share",
    "join": "Join (penonton masuk)",
}


class RuleEditor(QDialog):
    def __init__(self, rule: Rule | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Rule" if rule else "Rule Baru")
        self.resize(900, 620)

        # Salin supaya batal tidak mengubah rule asli.
        self.rule = copy.deepcopy(rule) if rule else Rule(name="Rule baru")
        self._cond_widgets: dict[str, QWidget] = {}

        root = QVBoxLayout(self)

        # ---- identitas
        head = QGroupBox("Rule")
        head_form = QFormLayout(head)

        self.name_edit = QLineEdit(self.rule.name)
        head_form.addRow("Nama:", self.name_edit)

        self.enabled_check = QCheckBox("Aktif")
        self.enabled_check.setChecked(self.rule.enabled)
        head_form.addRow("", self.enabled_check)

        self.event_combo = QComboBox()
        for kind, label in EVENT_LABELS.items():
            self.event_combo.addItem(label, kind)
        index = self.event_combo.findData(self.rule.event_kind)
        self.event_combo.setCurrentIndex(index if index >= 0 else 0)
        self.event_combo.currentIndexChanged.connect(self._rebuild_conditions)
        head_form.addRow("Event:", self.event_combo)

        root.addWidget(head)

        # ---- kondisi | aksi
        splitter = QSplitter(Qt.Horizontal)

        cond_box = QGroupBox("Kondisi (kosongkan = selalu cocok)")
        cond_outer = QVBoxLayout(cond_box)
        self.cond_widget = QWidget()
        self.cond_form = QFormLayout(self.cond_widget)
        cond_outer.addWidget(self.cond_widget)
        cond_outer.addStretch(1)
        splitter.addWidget(cond_box)

        action_box = QGroupBox("Aksi (dijalankan berurutan)")
        action_layout = QVBoxLayout(action_box)

        self.action_list = QListWidget()
        self.action_list.setMinimumHeight(110)
        self.action_list.currentRowChanged.connect(self._on_action_selected)
        action_layout.addWidget(self.action_list, 1)

        btn_row = QHBoxLayout()
        for label, slot in (
            ("Tambah", self._add_action),
            ("Hapus", self._remove_action),
            ("Naik", lambda: self._move_action(-1)),
            ("Turun", lambda: self._move_action(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            btn_row.addWidget(button)
        action_layout.addLayout(btn_row)

        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel("Tipe:"))
        self.action_type_combo = QComboBox()
        self._fill_action_types()
        self.action_type_combo.currentIndexChanged.connect(self._on_type_changed)
        pick_row.addWidget(self.action_type_combo, 1)
        action_layout.addLayout(pick_row)

        self.param_form = ParamForm()
        action_layout.addWidget(self.param_form)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Jeda setelah aksi ini (detik):"))
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 60.0)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.valueChanged.connect(self._save_current_action)
        delay_row.addWidget(self.delay_spin)
        delay_row.addStretch(1)
        action_layout.addLayout(delay_row)

        splitter.addWidget(action_box)
        splitter.setSizes([380, 560])
        root.addWidget(splitter, 1)

        # ---- pengaman
        safe_box = QGroupBox("Pengaman")
        safe_form = QFormLayout(safe_box)

        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0.0, 3600.0)
        self.cooldown_spin.setSingleStep(1.0)
        self.cooldown_spin.setValue(self.rule.cooldown_sec)
        self.cooldown_spin.setSpecialValueText("tanpa cooldown")
        safe_form.addRow("Cooldown (detik):", self.cooldown_spin)

        self.max_hour_spin = QSpinBox()
        self.max_hour_spin.setRange(0, 1000)
        self.max_hour_spin.setValue(self.rule.max_per_hour or 0)
        self.max_hour_spin.setSpecialValueText("tanpa batas")
        safe_form.addRow("Maks per jam:", self.max_hour_spin)

        self.confirm_check = QCheckBox("Minta konfirmasi untuk aksi berbahaya (reboot, shell, script)")
        self.confirm_check.setChecked(self.rule.require_confirm)
        safe_form.addRow("", self.confirm_check)

        root.addWidget(safe_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._rebuild_conditions()
        self._reload_action_list()

    # ------------------------------------------------------------- kondisi

    def _rebuild_conditions(self) -> None:
        """Form kondisi mengikuti jenis event yang dipilih."""
        while self.cond_form.count():
            item = self.cond_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cond_widgets.clear()

        kind = self.event_combo.currentData()
        specs = CONDITION_SPECS.get(kind, []) + COMMON_CONDITIONS
        current = self.rule.conditions or {}

        if not specs:
            label = QLabel("Event ini tidak punya kondisi tambahan.")
            label.setStyleSheet("color:#888;")
            self.cond_form.addRow("", label)
            return

        for name, label, ctype in specs:
            value = current.get(name)
            widget: QWidget
            if ctype == "bool":
                widget = QCheckBox()
                widget.setChecked(bool(value))
            elif ctype == "int":
                widget = QSpinBox()
                widget.setRange(-1, 100_000_000)
                widget.setSpecialValueText("(tidak dipakai)")
                widget.setValue(int(value) if value is not None else -1)
            elif ctype.startswith("choice:"):
                widget = QComboBox()
                widget.addItems(ctype.split(":", 1)[1].split(","))
                index = widget.findText(str(value or ""))
                widget.setCurrentIndex(index if index >= 0 else 0)
            elif ctype == "gift":
                # Dropdown gift dari katalog TikTok - tidak perlu ketik manual.
                widget = GiftPicker(str(value) if value is not None else "")
            else:
                widget = QLineEdit(str(value) if value is not None else "")
            self._cond_widgets[name] = widget
            self.cond_form.addRow(f"{label}:", widget)

    def _collect_conditions(self) -> dict[str, Any]:
        """Hanya simpan kondisi yang benar-benar diisi."""
        out: dict[str, Any] = {}
        for name, widget in self._cond_widgets.items():
            if isinstance(widget, GiftPicker):
                text = widget.value()
                if text:
                    out[name] = text
            elif isinstance(widget, QCheckBox):
                if widget.isChecked():
                    out[name] = True
            elif isinstance(widget, QSpinBox):
                if widget.value() >= 0:
                    out[name] = widget.value()
            elif isinstance(widget, QComboBox):
                text = widget.currentText().strip()
                # gift_name_mode hanya relevan kalau gift_name diisi.
                if text and not (name == "gift_name_mode" and not self._cond_widgets.get("gift_name")):
                    out[name] = text
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                if text:
                    out[name] = text
        # Buang mode kalau nama gift kosong.
        if "gift_name" not in out:
            out.pop("gift_name_mode", None)
        return out

    # ---------------------------------------------------------------- aksi

    def _fill_action_types(self) -> None:
        self.action_type_combo.clear()
        for category, specs in sorted(specs_by_category().items()):
            for spec in specs:
                prefix = CATEGORY_PREFIX.get(category, "[PC]")
                warn = " (!)" if spec.dangerous else ""
                self.action_type_combo.addItem(f"{prefix} {spec.label}{warn}", spec.type)

    def _reload_action_list(self, select: int | None = None) -> None:
        self.action_list.blockSignals(True)
        self.action_list.clear()
        for i, action in enumerate(self.rule.actions):
            spec = get_spec(action.type)
            label = spec.label if spec else action.type
            detail = ", ".join(f"{k}={v}" for k, v in action.params.items() if v not in ("", None))
            suffix = f" +{action.delay_after}s" if action.delay_after else ""
            self.action_list.addItem(QListWidgetItem(f"{i + 1}. {label}{suffix}  [{detail}]"))
        self.action_list.blockSignals(False)

        if self.rule.actions:
            row = select if select is not None else 0
            self.action_list.setCurrentRow(max(0, min(row, len(self.rule.actions) - 1)))
        else:
            self.param_form.set_spec(None)

    def _current_index(self) -> int:
        return self.action_list.currentRow()

    def _on_action_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.rule.actions):
            return
        action = self.rule.actions[row]
        index = self.action_type_combo.findData(action.type)

        self.action_type_combo.blockSignals(True)
        self.action_type_combo.setCurrentIndex(index if index >= 0 else 0)
        self.action_type_combo.blockSignals(False)

        self.param_form.set_spec(get_spec(action.type), action.params)

        self.delay_spin.blockSignals(True)
        self.delay_spin.setValue(action.delay_after)
        self.delay_spin.blockSignals(False)

    def _on_type_changed(self) -> None:
        row = self._current_index()
        if row < 0 or row >= len(self.rule.actions):
            return
        new_type = self.action_type_combo.currentData()
        self.rule.actions[row].type = new_type
        self.rule.actions[row].params = {}
        self.param_form.set_spec(get_spec(new_type))
        self._reload_action_list(row)

    def _save_current_action(self) -> None:
        """Simpan isi form ke aksi yang sedang dipilih."""
        row = self._current_index()
        if row < 0 or row >= len(self.rule.actions):
            return
        self.rule.actions[row].params = self.param_form.values()
        self.rule.actions[row].delay_after = self.delay_spin.value()

    def _add_action(self) -> None:
        self._save_current_action()
        action_type = self.action_type_combo.currentData() or "adb.tap"
        self.rule.actions.append(Action(type=action_type, params={}))
        self._reload_action_list(len(self.rule.actions) - 1)

    def _remove_action(self) -> None:
        row = self._current_index()
        if 0 <= row < len(self.rule.actions):
            del self.rule.actions[row]
            self._reload_action_list(max(0, row - 1))

    def _move_action(self, delta: int) -> None:
        self._save_current_action()
        row = self._current_index()
        target = row + delta
        if 0 <= row < len(self.rule.actions) and 0 <= target < len(self.rule.actions):
            actions = self.rule.actions
            actions[row], actions[target] = actions[target], actions[row]
            self._reload_action_list(target)

    # -------------------------------------------------------------- simpan

    def _accept(self) -> None:
        self._save_current_action()

        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Nama kosong", "Beri nama untuk rule ini.")
            return
        if not self.rule.actions:
            QMessageBox.warning(self, "Tanpa aksi", "Tambahkan minimal satu aksi.")
            return

        self.rule.name = name
        self.rule.enabled = self.enabled_check.isChecked()
        self.rule.event_kind = self.event_combo.currentData()
        self.rule.conditions = self._collect_conditions()
        self.rule.cooldown_sec = self.cooldown_spin.value()
        self.rule.max_per_hour = self.max_hour_spin.value() or None
        self.rule.require_confirm = self.confirm_check.isChecked()
        self.accept()

    def result_rule(self) -> Rule:
        return self.rule
