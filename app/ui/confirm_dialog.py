"""Dialog konfirmasi aksi berbahaya, dengan countdown auto-cancel.

Dipanggil dari worker thread, jadi harus dipaksa berjalan di GUI thread
lewat QMetaObject.invokeMethod dengan BlockingQueuedConnection.
"""

from __future__ import annotations

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QTimer, Slot
from PySide6.QtWidgets import QMessageBox

from app.i18n import tr


class _ConfirmBridge(QObject):
    """Menjalankan dialog di GUI thread dan mengembalikan jawabannya."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.answer = False

    @Slot(str, str, int)
    def show(self, rule_name: str, action_type: str, timeout_sec: int) -> None:
        box = QMessageBox(self.parent())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(tr("Konfirmasi aksi berbahaya"))
        box.setText(f"Rule <b>{rule_name}</b> ingin menjalankan:<br><b>{action_type}</b>")
        yes = box.addButton("Jalankan", QMessageBox.AcceptRole)
        box.addButton("Batal", QMessageBox.RejectRole)
        box.setDefaultButton(yes)

        remaining = [max(1, timeout_sec)]

        def tick() -> None:
            remaining[0] -= 1
            if remaining[0] <= 0:
                box.reject()          # auto-cancel: diam = tidak jalan
            else:
                box.setInformativeText(tr("Batal otomatis dalam {detik} detik...", detik=remaining[0]))

        box.setInformativeText(tr("Batal otomatis dalam {detik} detik...", detik=remaining[0]))
        timer = QTimer(box)
        timer.timeout.connect(tick)
        timer.start(1000)

        box.exec()
        timer.stop()
        self.answer = box.clickedButton() is yes


def ask_confirm(parent, rule_name: str, action_type: str, timeout_sec: int = 10) -> bool:
    """Aman dipanggil dari thread mana pun."""
    bridge = _ConfirmBridge(parent)
    QMetaObject.invokeMethod(
        bridge, "show", Qt.BlockingQueuedConnection,
        Q_ARG(str, rule_name), Q_ARG(str, action_type), Q_ARG(int, timeout_sec),
    )
    return bridge.answer
