"""Dropdown pemilih aksi dengan judul kelompok.

Daftar 39 aksi dalam satu combo datar sulit ditelusuri. Di sini aksi
dikelompokkan (Overlay, Kontrol HP, Aplikasi, Game, Komputer) dengan
baris judul yang tidak bisa dipilih sebagai pemisah.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox

from app.actions.base import grouped_specs
from app.i18n import tr
from app.ui.theme import ACCENT, TEXT_DIM

# Peran data: menyimpan tipe aksi di tiap baris
TYPE_ROLE = Qt.UserRole + 1


def fill_action_combo(combo: QComboBox) -> None:
    """Isi combo dengan aksi berkelompok. Baris judul tidak bisa dipilih."""
    model = QStandardItemModel(combo)

    header_font = QFont(combo.font())
    header_font.setBold(True)

    for title, specs in grouped_specs():
        header = QStandardItem(tr(title).upper())
        header.setFlags(Qt.NoItemFlags)             # tidak bisa dipilih
        header.setFont(header_font)
        header.setForeground(Qt.GlobalColor.gray)
        model.appendRow(header)

        for spec in specs:
            label = f"    {tr(spec.label)}"
            if spec.dangerous:
                label += "  ⚠"                  # tanda aksi berbahaya
            item = QStandardItem(label)
            item.setData(spec.type, TYPE_ROLE)
            if spec.help:
                item.setToolTip(tr(spec.help))
            model.appendRow(item)

    combo.setModel(model)
    select_action(combo, first_action_type(combo))


def first_action_type(combo: QComboBox) -> str:
    for row in range(combo.count()):
        value = combo.itemData(row, TYPE_ROLE)
        if value:
            return str(value)
    return ""


def current_action_type(combo: QComboBox) -> str:
    value = combo.itemData(combo.currentIndex(), TYPE_ROLE)
    return str(value) if value else ""


def select_action(combo: QComboBox, action_type: str) -> bool:
    """Pilih baris untuk sebuah tipe aksi. False kalau tidak ditemukan."""
    if not action_type:
        return False
    for row in range(combo.count()):
        if combo.itemData(row, TYPE_ROLE) == action_type:
            combo.setCurrentIndex(row)
            return True
    return False
