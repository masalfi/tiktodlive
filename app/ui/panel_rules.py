"""Panel rules: tabel rule + tombol kelola."""

from __future__ import annotations

import copy
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr

from app.models import Rule
from app.ui.rule_editor import EVENT_LABELS, RuleEditor
from app.ui.theme import TEXT_DIM

COLUMNS = ["Aktif", "Nama", "Event", "Kondisi", "Aksi", "Cooldown", "Maks/jam"]


class RulesPanel(QWidget):
    rules_changed = Signal(list)
    test_requested = Signal(object)

    def __init__(self, rules: list[Rule]) -> None:
        super().__init__()
        self.rules = rules

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        bar = QHBoxLayout()
        for label, slot in (
            ("Tambah", self._add),
            ("Edit", self._edit),
            ("Duplikat", self._duplicate),
            ("Hapus", self._delete),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            bar.addWidget(button)

        bar.addSpacing(20)
        self.toggle_button = QPushButton(tr("Aktif / Nonaktif"))
        self.toggle_button.clicked.connect(self._toggle)
        bar.addWidget(self.toggle_button)

        self.test_button = QPushButton(tr("Test Run"))
        self.test_button.setStyleSheet("font-weight:bold;")
        self.test_button.clicked.connect(self._test)
        bar.addWidget(self.test_button)

        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._edit)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(self.table, 1)

        hint = QLabel(
            tr("Klik dua kali untuk mengedit. Test Run menjalankan rule memakai event contoh, jadi bisa dicek tanpa menunggu gift asli.")
        )
        hint.setProperty("class", "hint")
        root.addWidget(hint)

        self.reload()

    # -------------------------------------------------------------- tabel

    def reload(self) -> None:
        self.table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            values = [
                tr("ya") if rule.enabled else "-",
                rule.name,
                tr(EVENT_LABELS.get(rule.event_kind, rule.event_kind)),
                rule.summary_conditions(),
                str(len(rule.actions)),
                f"{rule.cooldown_sec:g}s" if rule.cooldown_sec else "-",
                str(rule.max_per_hour) if rule.max_per_hour else "-",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if not rule.enabled:
                    item.setForeground(QColor(TEXT_DIM))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _commit(self) -> None:
        self.reload()
        self.rules_changed.emit(self.rules)

    # -------------------------------------------------------------- aksi

    def _add(self) -> None:
        editor = RuleEditor(parent=self)
        if editor.exec() == RuleEditor.Accepted:
            self.rules.append(editor.result_rule())
            self._commit()

    def _edit(self) -> None:
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, tr("Pilih rule"), tr("Pilih rule yang mau diedit."))
            return
        editor = RuleEditor(self.rules[row], parent=self)
        if editor.exec() == RuleEditor.Accepted:
            self.rules[row] = editor.result_rule()
            self._commit()

    def _duplicate(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        clone = copy.deepcopy(self.rules[row])
        clone.id = uuid.uuid4().hex[:8]      # id baru supaya cooldown terpisah
        clone.name = tr("{nama} (salinan)", nama=clone.name)
        self.rules.insert(row + 1, clone)
        self._commit()

    def _delete(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        rule = self.rules[row]
        confirm = QMessageBox.question(
            self, tr("Hapus rule"), tr("Hapus rule '{nama}'?", nama=rule.name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            del self.rules[row]
            self._commit()

    def _toggle(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        self.rules[row].enabled = not self.rules[row].enabled
        self._commit()

    def _test(self) -> None:
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, tr("Pilih rule"), tr("Pilih rule yang mau dites."))
            return
        self.test_requested.emit(self.rules[row])
