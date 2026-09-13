"""Pemilih gift dengan pencarian, menggantikan ketik nama manual.

Tetap mengizinkan nama bebas: kalau gift baru belum ada di katalog,
user masih bisa mengetiknya sendiri.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QSizePolicy,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from app.i18n import tr

from app.live.gifts import CATALOG, fetch_gift_list_sync
from app.ui.gift_icons import ICON_SIZE, ICONS


class GiftFetchWorker(QThread):
    """Ambil katalog gift di background supaya GUI tidak membeku."""

    finished_ok = Signal(int)       # jumlah gift
    failed = Signal(str)

    def run(self) -> None:
        try:
            raw = fetch_gift_list_sync()
        except Exception as exc:                    # noqa: BLE001
            self.failed.emit(str(exc))
            return
        count = CATALOG.set_from_raw(raw, "api")
        if count:
            self.finished_ok.emit(count)
        else:
            self.failed.emit(tr("API mengembalikan daftar kosong"))


class GiftPicker(QWidget):
    """Combo box gift: bisa dicari, bisa diketik bebas, bisa disegarkan."""

    value_changed = Signal(str)

    def __init__(self, value: str = "") -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.combo = QComboBox()
        self.combo.setEditable(True)                # tetap bisa ketik manual
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.setMinimumWidth(130)
        self.combo.currentTextChanged.connect(self._on_changed)
        layout.addWidget(self.combo, 1)

        self.refresh_button = QPushButton(tr("\u27f3"))          # simbol segarkan
        self.refresh_button.setToolTip(tr("Ambil daftar gift terbaru dari TikTok"))

        # Lebar mengikuti teks + padding; angka piksel tetap akan terpotong
        # saat font OS lebih besar (macOS 13pt vs Windows 9pt).
        self.refresh_button.setSizePolicy(
            QSizePolicy.Maximum, self.refresh_button.sizePolicy().verticalPolicy()
        )
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)

        self.status = QLabel()
        self.status.setProperty("class", "hint")
        layout.addWidget(self.status)

        self._worker: GiftFetchWorker | None = None
        ICONS.icon_ready.connect(self._on_icon_ready)
        self.reload_items()
        self.set_value(value)

    # ------------------------------------------------------------- isi

    def reload_items(self) -> None:
        """Isi ulang dropdown dari katalog, pertahankan teks yang sedang diisi."""
        current = self.combo.currentText()

        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.combo.addItem("", "")                  # kosong = cocokkan semua gift
        for gift in CATALOG.gifts:
            # Data = nama murni; teks tampilan menyertakan harga.
            icon = ICONS.get(gift.id)
            if icon is not None:
                self.combo.addItem(icon, gift.label(), gift.name)
            else:
                self.combo.addItem(gift.label(), gift.name)
        self.combo.blockSignals(False)

        # Ikon yang belum ada diunduh di latar belakang lalu dipasang.
        ICONS.request(CATALOG.gifts)

        # Completer mencari di mana saja dalam nama, bukan hanya awalan.
        completer = QCompleter([self.combo.itemText(i) for i in range(self.combo.count())], self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.combo.setCompleter(completer)

        if CATALOG.is_empty:
            self.status.setText("0")
        else:
            self.status.setText(str(len(CATALOG)))
            self.status.setToolTip(tr("{n} gift di katalog", n=len(CATALOG)))

        if current:
            self.set_value(current)

    def _on_icon_ready(self, gift_id: int) -> None:
        """Pasang ikon ke baris yang sesuai tanpa membangun ulang dropdown."""
        gift = CATALOG.find_by_id(gift_id)
        if gift is None:
            return
        index = self.combo.findData(gift.name, flags=Qt.MatchFixedString)
        if index >= 0:
            icon = ICONS.get(gift_id)
            if icon is not None:
                self.combo.setItemIcon(index, icon)

    def _on_changed(self, _text: str) -> None:
        self.value_changed.emit(self.value())

    # ----------------------------------------------------------- nilai

    def value(self) -> str:
        """Kembalikan NAMA gift saja, tanpa embel-embel harga."""
        text = self.combo.currentText().strip()
        if not text:
            return ""
        index = self.combo.findText(text)
        if index >= 0:
            data = self.combo.itemData(index)
            if data:
                return str(data)
        # Diketik manual: buang bagian " - N koin" kalau user menyalinnya.
        return text.split(" - ")[0].strip()

    def set_value(self, name: str) -> None:
        name = (name or "").strip()
        self.combo.blockSignals(True)
        if not name:
            self.combo.setCurrentIndex(0)
        else:
            index = self.combo.findData(name, flags=Qt.MatchFixedString)
            if index >= 0:
                self.combo.setCurrentIndex(index)
            else:
                self.combo.setCurrentText(name)     # gift tak dikenal, tetap dipakai
        self.combo.blockSignals(False)

    # --------------------------------------------------------- refresh

    def refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.status.setText("...")

        self._worker = GiftFetchWorker()
        self._worker.finished_ok.connect(self._on_fetched)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self._worker.start()

    def _on_fetched(self, count: int) -> None:
        self.reload_items()
        self.status.setText(str(count))
        self.status.setToolTip(tr("{n} gift, baru disegarkan", n=count))

    def _on_failed(self, message: str) -> None:
        self.status.setText("!")
        self.status.setToolTip(message)

    def closeEvent(self, event) -> None:
        # Jangan biarkan thread hidup lebih lama dari widget-nya.
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        super().closeEvent(event)
