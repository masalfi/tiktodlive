"""Panel katalog gift: telusuri gift TikTok beserta ikonnya.

Dipisah dari tab Devices supaya tabelnya punya ruang penuh - nama, ikon,
harga koin, status streak, dan ID sekaligus.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr

from app.live.gifts import CATALOG
from app.ui.gift_icons import ICONS
from app.ui.gift_picker import GiftFetchWorker
from app.ui.theme import TEXT_DIM

# Ikon lebih besar di sini karena tabelnya punya ruang.
TABLE_ICON = 32
MAX_ROWS = 300          # batasi render supaya tabel tetap ringan


class GiftsPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(tr("Cari:")))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("ketik nama gift, mis. rose"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search, 1)

        self.refresh_button = QPushButton(tr("Segarkan dari TikTok"))
        self.refresh_button.clicked.connect(self._refresh)
        bar.addWidget(self.refresh_button)
        root.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Gift", "Koin", "Streak", "ID"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setIconSize(QSize(TABLE_ICON, TABLE_ICON))
        self.table.verticalHeader().setDefaultSectionSize(TABLE_ICON + 8)
        self.table.verticalHeader().setVisible(False)     # kolom nomor tak berguna
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(self.table, 1)

        self.status = QLabel()
        self.status.setProperty("class", "hint")
        root.addWidget(self.status)

        self._worker: GiftFetchWorker | None = None
        self._shown: list = []
        ICONS.icon_ready.connect(self._on_icon_ready)
        self.reload()

    # ------------------------------------------------------------- tabel

    def reload(self) -> None:
        self._filter(self.search.text())

    def _filter(self, query: str) -> None:
        gifts = CATALOG.search(query)
        shown = gifts[:MAX_ROWS]
        self._shown = shown

        self.table.setRowCount(len(shown))
        for row, gift in enumerate(shown):
            name_item = QTableWidgetItem(gift.name)
            icon = ICONS.get(gift.id)
            if icon is not None:
                name_item.setIcon(icon)
            self.table.setItem(row, 0, name_item)

            coins = QTableWidgetItem(f"{gift.diamond_count:,}".replace(",", "."))
            coins.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, coins)

            streak = QTableWidgetItem("ya" if gift.streakable else "-")
            streak.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, streak)

            gift_id = QTableWidgetItem(str(gift.id))
            gift_id.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, gift_id)

        for col in (1, 2, 3):
            self.table.resizeColumnToContents(col)

        # Unduh ikon yang belum ada untuk baris yang sedang tampil.
        ICONS.request(shown)

        if CATALOG.is_empty:
            self.status.setText(
                tr("Katalog kosong - klik 'Segarkan dari TikTok'. Nama gift tetap bisa diketik manual di editor rule.")
            )
        elif len(shown) < len(gifts):
            self.status.setText(
                tr("Menampilkan {n} dari {total} hasil (total katalog {katalog} gift)",
                   n=len(shown), total=len(gifts), katalog=len(CATALOG))
            )
        else:
            self.status.setText(tr("{n} gift ditampilkan (total {katalog})",
                                   n=len(gifts), katalog=len(CATALOG)))

    def _on_icon_ready(self, gift_id: int) -> None:
        """Pasang ikon ke barisnya tanpa membangun ulang seluruh tabel."""
        for row, gift in enumerate(self._shown):
            if gift.id != gift_id:
                continue
            item = self.table.item(row, 0)
            icon = ICONS.get(gift_id)
            if item is not None and icon is not None:
                item.setIcon(icon)
            return

    # ----------------------------------------------------------- refresh

    def _refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.status.setText(tr("mengambil dari TikTok..."))

        self._worker = GiftFetchWorker()
        self._worker.finished_ok.connect(lambda _n: self.reload())
        self._worker.failed.connect(
            lambda msg: self.status.setText(tr("Gagal: {sebab}", sebab=msg[:80]))
        )
        self._worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self._worker.start()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        super().closeEvent(event)
