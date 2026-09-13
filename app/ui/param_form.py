"""Form parameter dinamis, dibangun dari ParamSpec di registry aksi.

Dipakai bersama oleh editor rule dan panel tes manual, supaya menambah
aksi baru cukup dengan mendaftarkannya di registry - GUI ikut otomatis.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt

from PySide6.QtWidgets import (
    QCheckBox,
    QCompleter,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from app.actions.base import ActionSpec
from app.i18n import tr
from app.ui.theme import TEXT_DIM


# Penyedia daftar aplikasi di HP. MainWindow mengisinya saat start supaya
# form tidak perlu tahu apa-apa soal adb.
_package_provider: "Callable[[], list[str]] | None" = None


def set_package_provider(provider) -> None:
    global _package_provider
    _package_provider = provider


# Penyedia daftar tombol game dari profil yang sedang aktif.
_button_provider: "Callable[[], list[tuple[str, str]]] | None" = None


def set_button_provider(provider) -> None:
    global _button_provider
    _button_provider = provider


def available_buttons() -> list[tuple[str, str]]:
    """[(nama, label tampilan)] tombol game dari profil aktif."""
    if _button_provider is None:
        return []
    try:
        return _button_provider()
    except Exception:                               # noqa: BLE001
        return []


def available_packages() -> list[str]:
    if _package_provider is None:
        return []
    try:
        return _package_provider()
    except Exception:                               # noqa: BLE001
        return []


def _select_button(combo: QComboBox, name: str) -> None:
    if not name:
        if combo.count():
            combo.setCurrentIndex(0)
        return
    for row in range(combo.count()):
        if combo.itemData(row) == name:
            combo.setCurrentIndex(row)
            return
    combo.setCurrentText(name)          # tombol tak dikenal, tetap dipakai


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
            hint = QLabel(tr(spec.help))
            hint.setWordWrap(True)
            hint.setProperty("class", "hint")
            # Satu argumen = membentang dua kolom. Kalau dimasukkan ke
            # kolom kanan, teksnya terjepit dan sulit dibaca.
            self._layout.addRow(hint)

        for p in spec.params:
            current = values.get(p.name, p.default)
            widget: QWidget

            if p.kind == "bool":
                widget = QCheckBox()
                widget.setChecked(bool(current))
            elif p.kind == "game_button":
                # Ambil dari profil di tab Game supaya tidak perlu
                # menghafal nama tombol hasil kalibrasi.
                widget = QComboBox()
                widget.setEditable(True)
                widget.setInsertPolicy(QComboBox.NoInsert)
                buttons = available_buttons()
                model = widget.model()
                for name, label in buttons:
                    widget.addItem(label, name)
                    if not name:
                        # Baris pemisah kelompok - tidak bisa dipilih.
                        item = model.item(widget.count() - 1)
                        if item is not None:
                            item.setEnabled(False)
                if buttons:
                    completer = QCompleter([b[1] for b in buttons if b[0]], widget)
                    completer.setCaseSensitivity(Qt.CaseInsensitive)
                    completer.setFilterMode(Qt.MatchContains)
                    widget.setCompleter(completer)
                else:
                    widget.lineEdit().setPlaceholderText(
                        tr("kalibrasi dulu di tab Game"))
                _select_button(widget, str(current) if current else "")
            elif p.kind == "package":
                # Daftar aplikasi terpasang, tapi tetap bisa diketik sendiri
                # kalau aplikasinya belum terpasang saat rule dibuat.
                widget = QComboBox()
                widget.setEditable(True)
                widget.setInsertPolicy(QComboBox.NoInsert)
                packages = available_packages()
                widget.addItem("")
                widget.addItems(packages)
                if packages:
                    completer = QCompleter(packages, widget)
                    completer.setCaseSensitivity(Qt.CaseInsensitive)
                    completer.setFilterMode(Qt.MatchContains)
                    widget.setCompleter(completer)
                    widget.lineEdit().setPlaceholderText(f"{len(packages)} aplikasi terdeteksi")
                else:
                    widget.lineEdit().setPlaceholderText(tr("mis. com.mobile.legends"))
                widget.setCurrentText(str(current) if current else "")
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
                    widget.setPlaceholderText(tr(p.help))

            if p.help and p.kind not in ("str", "file"):
                widget.setToolTip(tr(p.help))

            self._widgets[p.name] = widget
            self._layout.addRow(f"{tr(p.label)}:", widget)

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, widget in self._widgets.items():
            if isinstance(widget, QCheckBox):
                out[name] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                text = widget.currentText().strip()
                index = widget.findText(text)
                data = widget.itemData(index) if index >= 0 else None
                # Item tombol game menyimpan nama asli di data; teksnya
                # bisa berisi keterangan seperti "skill1  (= mobility)".
                out[name] = str(data) if data else text
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                out[name] = widget.value()
            elif isinstance(widget, QLineEdit):
                out[name] = widget.text()
        return out
