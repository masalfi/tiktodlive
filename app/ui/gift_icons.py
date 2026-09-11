"""Cache ikon gift.

Ikon diunduh sekali lalu disimpan ke config/gift_icons/, jadi pemakaian
berikutnya langsung dari disk. Pengunduhan berjalan di thread terpisah
supaya daftar gift tidak membeku.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap

from app.live.gifts import ICON_DIR

log = logging.getLogger(__name__)

ICON_SIZE = 28


class _Downloader(QThread):
    """Unduh beberapa ikon sekaligus di latar belakang."""

    downloaded = Signal(int, bytes)     # gift_id, data

    def __init__(self, jobs: list[tuple[int, str]]) -> None:
        super().__init__()
        self.jobs = jobs
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        import httpx

        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                for gift_id, url in self.jobs:
                    if self._stop:
                        return
                    try:
                        response = client.get(url)
                        if response.status_code == 200 and response.content:
                            self.downloaded.emit(gift_id, response.content)
                    except Exception:               # noqa: BLE001
                        continue                    # satu ikon gagal bukan masalah
        except Exception:                           # noqa: BLE001
            log.debug("Downloader ikon berhenti", exc_info=True)


class GiftIconCache(QObject):
    """Menyediakan QIcon untuk gift, mengunduh saat pertama dibutuhkan."""

    icon_ready = Signal(int)            # gift_id - pemanggil bisa refresh tampilan

    def __init__(self) -> None:
        super().__init__()
        self._memory: dict[int, QIcon] = {}
        self._pending: set[int] = set()
        self._failed: set[int] = set()
        self._workers: list[_Downloader] = []

    # -------------------------------------------------------------- disk

    @staticmethod
    def _path(gift_id: int) -> Path:
        return ICON_DIR / f"{gift_id}.img"

    def _load_from_disk(self, gift_id: int) -> QIcon | None:
        path = self._path(gift_id)
        if not path.exists():
            return None
        pixmap = QPixmap()
        if not pixmap.load(str(path)):
            return None
        return QIcon(pixmap)

    def _save_to_disk(self, gift_id: int, data: bytes) -> None:
        try:
            ICON_DIR.mkdir(parents=True, exist_ok=True)
            self._path(gift_id).write_bytes(data)
        except OSError as exc:
            log.debug("Gagal menyimpan ikon %s: %s", gift_id, exc)

    # --------------------------------------------------------------- API

    def get(self, gift_id: int) -> QIcon | None:
        """Ikon kalau sudah siap; None kalau belum (akan diunduh)."""
        icon = self._memory.get(gift_id)
        if icon is not None:
            return icon
        icon = self._load_from_disk(gift_id)
        if icon is not None:
            self._memory[gift_id] = icon
            return icon
        return None

    def request(self, gifts) -> None:
        """Minta ikon untuk sekumpulan gift; yang belum ada diunduh."""
        jobs: list[tuple[int, str]] = []
        for gift in gifts:
            gid = gift.id
            if gid in self._memory or gid in self._pending or gid in self._failed:
                continue
            if self._load_from_disk(gid) is not None:
                continue
            if not gift.icon_url:
                self._failed.add(gid)
                continue
            self._pending.add(gid)
            jobs.append((gid, gift.icon_url))

        if not jobs:
            return

        worker = _Downloader(jobs)
        worker.downloaded.connect(self._on_downloaded)
        worker.finished.connect(lambda: self._retire(worker))
        self._workers.append(worker)
        worker.start()

    def _on_downloaded(self, gift_id: int, data: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._failed.add(gift_id)
            self._pending.discard(gift_id)
            return
        self._save_to_disk(gift_id, data)
        self._memory[gift_id] = QIcon(pixmap)
        self._pending.discard(gift_id)
        self.icon_ready.emit(gift_id)

    def _retire(self, worker: _Downloader) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def shutdown(self) -> None:
        """Hentikan unduhan yang masih jalan saat aplikasi ditutup."""
        for worker in list(self._workers):
            worker.stop()
            if worker.isRunning():
                worker.wait(2000)
        self._workers.clear()


# Cache bersama satu aplikasi.
ICONS = GiftIconCache()
