"""Form parameter dinamis, dibangun dari ParamSpec di registry aksi.

Dipakai bersama oleh editor rule dan panel tes manual, supaya menambah
aksi baru cukup dengan mendaftarkannya di registry - GUI ikut otomatis.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from app.actions.base import ActionSpec
from app.ui.theme import TEXT_DIM


class ParamForm(QWidget):
    """Bangun widget input sesuai spec, lalu baca nilainya kembali."""

    def __init__(self, spec: ActionSpec | None = None, values: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._widgets: dict[str, QWidget] = {}
        self.spec: ActionSpec | None = None
        self.set_spec(spec, values)

    def set_spec(self, spec: ActionSpec | None, values: dict[str, Any] | None = None) -> None:
        # Bersihkan form lama.
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._widgets.clear()
        self.spec = spec
        values = values or {}

        if spec is None:
            return

        if spec.help:
            hint = QLabel(spec.help)
            hint.setWordWrap(True)
            hint.setProperty("class", "hint")
            self._layout.addRow("", hint)

        for p in spec.params:
            current = values.get(p.name, p.default)
            widget: QWidget

            if p.kind == "bool":
                widget = QCheckBox()
                widget.setChecked(bool(current))
            elif p.kind == "choice":
                widget = QComboBox()
                widget.addItems(p.choices)
                text = str(current if current is not None else "")
                index = widget.findText(text)
                widget.setCurrentIndex(index if index >= 0 else 0)
            elif p.kind == "int":
                widget = QSpinBox()
                widget.setRange(
                    p.minimum if p.minimum is not None else -1_000_000,
                    p.maximum if p.maximum is not None else 1_000_000,
                )
                try:
                    widget.setValue(int(current))
                except (TypeError, ValueError):
                    widget.setValue(0)
            elif p.kind == "float":
                widget = QDoubleSpinBox()
                widget.setRange(-1_000_000.0, 1_000_000.0)
                widget.setDecimals(2)
                widget.setSingleStep(0.1)
                try:
                    widget.setValue(float(current))
                except (TypeError, ValueError):
                    widget.setValue(0.0)
            else:
                widget = QLineEdit(str(current) if current is not None else "")
                if p.help:
                    widget.setPlaceholderText(p.help)

            if p.help and p.kind not in ("str", "file"):
                widget.setToolTip(p.help)

            self._widgets[p.name] = widget
            self._layout.addRow(f"{p.label}:", widget)

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, widget in self._widgets.items():
            if isinstance(widget, QCheckBox):
                out[name] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                out[name] = widget.currentText()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                out[name] = widget.value()
            elif isinstance(widget, QLineEdit):
                out[name] = widget.text()
        return out
