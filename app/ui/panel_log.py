"""Panel log: feed event TikTok (kiri) dan hasil eksekusi aksi (kanan)."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.models import ActionResult, Job, LiveEvent
from app.ui.theme import DANGER, OK, TEXT_DIM

MAX_ROWS = 500          # buang baris lama supaya memori tidak terus naik

_EVENT_COLORS = {
    "gift": "#ff4d94",
    "comment": "#4dd2ff",
    "follow": "#7cff87",
    "share": "#ffd24d",
    "like": "#c58cff",
    "join": "#9e9e9e",
}


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


class LogPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- toolbar
        bar = QHBoxLayout()
        self.autoscroll_check = QCheckBox("Auto-scroll")
        self.autoscroll_check.setChecked(True)
        bar.addWidget(self.autoscroll_check)

        self.show_join_check = QCheckBox("Tampilkan event join")
        self.show_join_check.setChecked(False)
        bar.addWidget(self.show_join_check)

        self.show_like_check = QCheckBox("Tampilkan event like")
        self.show_like_check.setChecked(False)
        bar.addWidget(self.show_like_check)

        bar.addStretch(1)
        clear_button = QPushButton("Bersihkan")
        clear_button.clicked.connect(self._clear)
        bar.addWidget(clear_button)
        root.addLayout(bar)

        # ---- dua kolom
        splitter = QSplitter(Qt.Horizontal)

        left_box = QGroupBox("Event masuk")
        left_layout = QVBoxLayout(left_box)
        self.event_list = QListWidget()
        left_layout.addWidget(self.event_list)
        splitter.addWidget(left_box)

        right_box = QGroupBox("Aksi & sistem")
        right_layout = QVBoxLayout(right_box)
        self.action_list = QListWidget()
        right_layout.addWidget(self.action_list)
        splitter.addWidget(right_box)

        splitter.setSizes([440, 480])
        root.addWidget(splitter, 1)

    # ------------------------------------------------------------- helpers

    def _append(self, widget: QListWidget, text: str, color: str | None = None) -> None:
        item = QListWidgetItem(text)
        if color:
            item.setForeground(QColor(color))
        widget.addItem(item)
        while widget.count() > MAX_ROWS:
            widget.takeItem(0)
        if self.autoscroll_check.isChecked():
            widget.scrollToBottom()

    def _clear(self) -> None:
        self.event_list.clear()
        self.action_list.clear()

    # ------------------------------------------------------------------ API

    def add_event(self, event: LiveEvent) -> None:
        if event.kind == "join" and not self.show_join_check.isChecked():
            return
        if event.kind == "like" and not self.show_like_check.isChecked():
            return
        self._append(
            self.event_list,
            f"[{_stamp()}] {event.display()}",
            _EVENT_COLORS.get(event.kind),
        )

    def add_result(self, job: Job, index: int, result: ActionResult) -> None:
        icon = "OK  " if result.ok else "GAGAL"
        color = OK if result.ok else DANGER
        step = f"{index + 1}/{len(job.rule.actions)}"
        self._append(
            self.action_list,
            f"[{_stamp()}] {icon} [{job.rule.name} {step}] {result.action_type}: "
            f"{result.message} ({result.duration_ms}ms)",
            color,
        )

    def add_system(self, message: str, error: bool = False) -> None:
        self._append(
            self.action_list,
            f"[{_stamp()}] {'!' if error else '*'} {message}",
            DANGER if error else TEXT_DIM,
        )
