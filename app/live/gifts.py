"""Katalog gift TikTok.

Nama gift tidak perlu diketik manual. Daftar diambil langsung dari API
TikTok (endpoint /gift/list/), lalu di-cache ke config/gifts.json supaya
tetap bisa dipakai offline.

Katalog global berisi ratusan gift. Saat terhubung ke sebuah room,
daftarnya bisa diperbarui dengan gift yang benar-benar tersedia di room
tersebut (fetch_gift_info=True).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.config import CONFIG_DIR

log = logging.getLogger(__name__)

CACHE_PATH = CONFIG_DIR / "gifts.json"
# Folder cache gambar ikon gift. Dipakai bersama oleh tampilan (tab Gift)
# dan aksi overlay "hujan ikon gift".
ICON_DIR = CONFIG_DIR / "gift_icons"
# Katalog jarang berubah; segarkan otomatis kalau cache lebih tua dari ini.
CACHE_MAX_AGE_SEC = 7 * 24 * 3600


@dataclass(frozen=True)
class Gift:
    """Satu jenis gift TikTok."""

    id: int
    name: str
    diamond_count: int          # harga dalam koin
    type: int                   # 1 = streakable
    icon_url: str = ""          # gambar gift dari CDN TikTok

    @property
    def streakable(self) -> bool:
        return self.type == 1

    def label(self) -> str:
        """Teks untuk dropdown, mis. 'Rose - 1 koin (streak)'."""
        suffix = " (streak)" if self.streakable else ""
        return f"{self.name} - {self.diamond_count} koin{suffix}"


def _icon_url(item: dict[str, Any]) -> str:
    """Ambil URL gambar gift. API memakai 'image' atau 'icon', keduanya
    berisi url_list (beberapa mirror CDN) - ambil yang pertama."""
    for key in ("image", "icon"):
        block = item.get(key)
        if not isinstance(block, dict):
            continue
        urls = block.get("url_list") or block.get("urlList") or []
        if isinstance(urls, str):
            return urls
        if isinstance(urls, list) and urls:
            return str(urls[0])
    return ""


def _parse(raw: Iterable[dict[str, Any]]) -> list[Gift]:
    """Ambil field yang dipakai saja; abaikan entri rusak."""
    out: list[Gift] = []
    for item in raw:
        try:
            name = str(item["name"]).strip()
            if not name:
                continue
            out.append(Gift(
                id=int(item["id"]),
                name=name,
                diamond_count=int(item.get("diamond_count", 0)),
                type=int(item.get("type", 0)),
                icon_url=str(item.get("icon_url") or "") or _icon_url(item),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _dedupe(gifts: list[Gift]) -> list[Gift]:
    """TikTok punya beberapa gift dengan nama sama tapi ID berbeda.

    Rule mencocokkan berdasarkan nama, jadi simpan satu entri per nama -
    dipilih yang termurah, karena itu yang paling sering dikirim penonton.
    """
    best: dict[str, Gift] = {}
    for gift in gifts:
        key = gift.name.casefold()
        current = best.get(key)
        if current is None or gift.diamond_count < current.diamond_count:
            best[key] = gift
    return sorted(best.values(), key=lambda g: (g.diamond_count, g.name.casefold()))


class GiftCatalog:
    """Menyimpan daftar gift + cache ke disk."""

    def __init__(self) -> None:
        self.gifts: list[Gift] = []      # hasil dedupe, untuk tampilan
        self._all: list[Gift] = []       # daftar lengkap, untuk lookup ID
        self.updated_at: float = 0.0
        self.source: str = "kosong"

    # ------------------------------------------------------------ akses

    def __len__(self) -> int:
        return len(self.gifts)

    @property
    def is_empty(self) -> bool:
        return not self.gifts

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.updated_at) > CACHE_MAX_AGE_SEC

    def names(self) -> list[str]:
        return [g.name for g in self.gifts]

    def find(self, name: str) -> Gift | None:
        target = (name or "").strip().casefold()
        for gift in self.gifts:
            if gift.name.casefold() == target:
                return gift
        return None

    def find_by_id(self, gift_id: int) -> Gift | None:
        """Cari berdasarkan ID - dipakai backend EulerStream yang hanya
        mengirim giftId tanpa nama. Mencari di daftar lengkap (sebelum
        dedupe) supaya ID varian tetap dikenali."""
        for gift in (self._all or self.gifts):
            if gift.id == gift_id:
                return gift
        return None

    def search(self, query: str) -> list[Gift]:
        """Filter berdasarkan potongan nama (untuk kotak cari di GUI)."""
        q = (query or "").strip().casefold()
        if not q:
            return list(self.gifts)
        return [g for g in self.gifts if q in g.name.casefold()]

    # ------------------------------------------------------------ cache

    def load_cache(self) -> bool:
        if not CACHE_PATH.exists():
            return False
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            gifts = _parse(data.get("gifts") or [])
            if not gifts:
                return False
            self._all = gifts
            self.gifts = _dedupe(gifts)
            self.updated_at = float(data.get("updated_at", 0))
            self.source = "cache"
            return True
        except (OSError, ValueError, TypeError) as exc:
            log.warning("Gagal membaca cache gift: %s", exc)
            return False

    def save_cache(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": self.updated_at,
                "gifts": [
                    {"id": g.id, "name": g.name, "diamond_count": g.diamond_count,
                     "type": g.type, "icon_url": g.icon_url}
                    for g in (self._all or self.gifts)
                ],
            }
            with open(CACHE_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
        except OSError as exc:
            log.warning("Gagal menyimpan cache gift: %s", exc)

    # ------------------------------------------------------------ update

    def set_from_raw(self, raw: Iterable[dict[str, Any]], source: str) -> int:
        """Ganti isi katalog dari data mentah API. Kembalikan jumlah gift."""
        parsed = _parse(raw)
        if not parsed:
            return 0
        # Semua gift disimpan supaya lookup lewat giftId selalu berhasil;
        # daftar tampilan (self.gifts) tetap hasil dedupe per nama.
        self._all = parsed
        self.gifts = _dedupe(parsed)
        self.updated_at = time.time()
        self.source = source
        self.save_cache()
        return len(self.gifts)

    def merge_from_raw(self, raw: Iterable[dict[str, Any]], source: str) -> int:
        """Gabungkan gift room ke katalog global. Kembalikan jumlah gift baru."""
        incoming = _parse(raw)
        if not incoming:
            return 0
        known = {g.name.casefold() for g in self.gifts}
        added = [g for g in _dedupe(incoming) if g.name.casefold() not in known]
        if added:
            self._all = (self._all or list(self.gifts)) + added
            self.gifts = _dedupe(self.gifts + added)
            self.updated_at = time.time()
            self.source = source
            self.save_cache()
        return len(added)


async def fetch_gift_list() -> list[dict[str, Any]]:
    """Ambil katalog gift global dari API TikTok.

    Tidak perlu terhubung ke room mana pun - room_id opsional pada
    endpoint /gift/list/.
    """
    from TikTokLive import TikTokLiveClient

    client = TikTokLiveClient(unique_id="tiktok")
    try:
        data = await client.web.fetch_gift_list()
        return data.get("gifts") or []
    finally:
        try:
            await client.web.close()
        except Exception:                           # noqa: BLE001
            pass


def fetch_gift_list_sync(timeout: float = 30.0) -> list[dict[str, Any]]:
    """Versi blocking untuk dipakai di worker thread GUI."""
    async def runner() -> list[dict[str, Any]]:
        return await asyncio.wait_for(fetch_gift_list(), timeout=timeout)

    return asyncio.run(runner())


def icon_path(gift_id: int) -> Path:
    """Lokasi file ikon sebuah gift di cache."""
    return ICON_DIR / f"{gift_id}.img"


def ensure_icon(gift_id: int, timeout: float = 15.0) -> Path | None:
    """Ambil file ikon gift, unduh dulu kalau belum ada.

    Dipakai aksi overlay supaya hujan ikon tetap jalan untuk gift yang
    belum pernah tampil di tab Gift. Kembalikan None kalau gagal.
    """
    path = icon_path(gift_id)
    if path.is_file() and path.stat().st_size > 0:
        return path

    gift = CATALOG.find_by_id(gift_id)
    if gift is None or not gift.icon_url:
        return None

    try:
        import httpx

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(gift.icon_url)
        if response.status_code != 200 or not response.content:
            return None
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    except Exception as exc:                        # noqa: BLE001
        log.warning("Gagal mengunduh ikon gift %s: %s", gift_id, exc)
        return None
    return path


# Katalog bersama satu aplikasi.
CATALOG = GiftCatalog()
