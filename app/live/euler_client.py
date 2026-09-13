"""Backend koneksi alternatif: WebSocket terkelola EulerStream.

Kenapa ada dua backend:

TikTokLive (backend "tiktoklive") menyambung langsung ke TikTok memakai URL
bertanda tangan dari sign server. Ketika sign server tidak bisa memberi URL
TikTok asli, ia mengembalikan proxy fallback yang menolak koneksi (HTTP
400/403) - live jadi tidak bisa dipantau sama sekali.

Backend ini memakai jalur berbeda: WebSocket terkelola EulerStream
(wss://ws.eulerstream.com) yang diautentikasi dengan API key. Formatnya JSON,
bukan protobuf, dan gift datang tanpa nama - hanya giftId, yang diterjemahkan
lewat katalog gift.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote

from PySide6.QtCore import QThread, Signal

from app.live.client import (
    STATE_CONNECTING,
    STATE_DISCONNECTED,
    STATE_ERROR,
    STATE_LIVE,
)
from app.i18n import tr
from app.models import LiveEvent

log = logging.getLogger(__name__)

WS_BASE = "wss://ws.eulerstream.com/"

# Tipe pesan EulerStream -> jenis event internal
_KIND_BY_TYPE = {
    "WebcastChatMessage": "comment",
    "WebcastGiftMessage": "gift",
    "WebcastLikeMessage": "like",
    "WebcastMemberMessage": "join",
    "WebcastSocialMessage": "social",     # follow atau share, dibedakan nanti
}


def _user_bits(data: dict[str, Any]) -> dict[str, str]:
    user = data.get("user") or {}
    return {
        "user_id": str(user.get("userId") or ""),
        "username": str(user.get("uniqueId") or ""),
        "nickname": str(user.get("nickname") or ""),
    }


def _social_kind(data: dict[str, Any]) -> str:
    """WebcastSocialMessage dipakai untuk follow maupun share."""
    key = str(
        ((data.get("common") or {}).get("displayText") or {}).get("key") or ""
    ).lower()
    if "follow" in key:
        return "follow"
    if "share" in key:
        return "share"
    return ""


def normalize(msg_type: str, data: dict[str, Any]) -> LiveEvent | None:
    """Ubah satu pesan EulerStream jadi LiveEvent, atau None kalau diabaikan."""
    kind = _KIND_BY_TYPE.get(msg_type)
    if kind is None:
        return None

    if kind == "social":
        kind = _social_kind(data)
        if not kind:
            return None

    bits = _user_bits(data)

    if kind == "comment":
        return LiveEvent(kind="comment", comment=str(data.get("comment") or ""), **bits)

    if kind == "like":
        return LiveEvent(kind="like", like_count=int(data.get("likeCount") or 0), **bits)

    if kind == "gift":
        # Gift streakable memancarkan event berkali-kali; repeatEnd=1 menandai
        # streak selesai. Hanya event terakhir yang dihitung.
        gift_id = int(data.get("giftId") or 0)
        repeat = int(data.get("repeatCount") or 1)

        from app.live.gifts import CATALOG

        gift = CATALOG.find_by_id(gift_id)
        # EulerStream tidak mengirim nama/harga gift, hanya ID.
        name = gift.name if gift else f"Gift #{gift_id}"
        coins = gift.diamond_count if gift else 0
        streakable = gift.streakable if gift else False

        if streakable and not int(data.get("repeatEnd") or 0):
            return None                          # streak masih berjalan

        return LiveEvent(
            kind="gift", gift_name=name, gift_id=gift_id,
            repeat_count=repeat, diamond_count=coins,
            total_coins=coins * repeat, **bits,
        )

    return LiveEvent(kind=kind, **bits)


class EulerWorker(QThread):
    """Menyambung ke WebSocket terkelola EulerStream memakai API key."""

    event_received = Signal(object)
    status_changed = Signal(str, str)
    viewer_count = Signal(int)
    gifts_updated = Signal(int)          # dipakai agar antarmuka sama

    def __init__(self, username: str, api_key: str, auto_reconnect: bool = True) -> None:
        super().__init__()
        self.username = username.strip().lstrip("@")
        self.api_key = api_key.strip()
        self.auto_reconnect = auto_reconnect
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._should_stop = False

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:                    # noqa: BLE001
            log.exception("EulerWorker berhenti")
            self.status_changed.emit(STATE_ERROR, str(exc))
        finally:
            try:
                self._loop.close()
            except Exception:                       # noqa: BLE001
                pass
            self.status_changed.emit(STATE_DISCONNECTED, "Terputus")

    def stop(self) -> None:
        self._should_stop = True
        if self._loop and self._loop.is_running() and self._ws is not None:
            asyncio.run_coroutine_threadsafe(self._close(), self._loop)

    async def _close(self) -> None:
        try:
            await self._ws.close()
        except Exception:                           # noqa: BLE001
            pass

    async def _main(self) -> None:
        import websockets

        backoff = 3
        while not self._should_stop:
            self.status_changed.emit(
                STATE_CONNECTING, tr("Menyambung ke @{nama} (EulerStream)...", nama=self.username)
            )
            url = f"{WS_BASE}?uniqueId={quote(self.username)}"
            try:
                async with websockets.connect(
                    url,
                    additional_headers={"X-Api-Key": self.api_key},
                    open_timeout=20,
                    ping_interval=20,
                ) as ws:
                    self._ws = ws
                    self.status_changed.emit(
                        STATE_LIVE, tr("Terhubung ke @{nama} (EulerStream)", nama=self.username)
                    )
                    backoff = 3                     # reset setelah sukses
                    await self._listen(ws)
            except asyncio.CancelledError:
                break
            except Exception as exc:                # noqa: BLE001
                status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
                if status in (401, 403):
                    self.status_changed.emit(
                        STATE_ERROR,
                        tr("API key ditolak EulerStream (HTTP {status}). "
                           "Periksa kembali key di tab Koneksi.", status=status),
                    )
                    return                          # retry tidak akan menolong

                # Kode 4429 = batas koneksi serentak pada paket EulerStream.
                # Menyambung ulang cepat malah memperparah, jadi tunggu lama.
                code = getattr(exc, "code", None)
                if code == 4429 or "rate limit" in str(exc).lower():
                    self.status_changed.emit(
                        STATE_ERROR,
                        tr("Batas koneksi EulerStream tercapai. Pastikan tidak ada "
                           "aplikasi/tab lain yang masih tersambung, lalu tunggu "
                           "sekitar satu menit. Menyambung ulang otomatis..."),
                    )
                    backoff = max(backoff, 60)
                else:
                    self.status_changed.emit(STATE_ERROR, f"{type(exc).__name__}: {exc}")
            finally:
                self._ws = None

            if self._should_stop or not self.auto_reconnect:
                break

            self.status_changed.emit(STATE_CONNECTING, tr("Mencoba lagi dalam {detik}s...", detik=backoff))
            for _ in range(backoff * 10):
                if self._should_stop:
                    return
                await asyncio.sleep(0.1)
            backoff = min(backoff * 2, 60)

    async def _listen(self, ws) -> None:
        async for raw in ws:
            if self._should_stop:
                return
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                continue

            for message in payload.get("messages") or []:
                msg_type = message.get("type") or ""
                data = message.get("data") or {}

                if msg_type == "WebcastRoomUserSeqMessage":
                    total = data.get("totalUser") or data.get("total")
                    if total:
                        self.viewer_count.emit(int(total))
                    continue

                try:
                    event = normalize(msg_type, data)
                except Exception:                   # noqa: BLE001
                    log.debug("Gagal normalisasi %s", msg_type, exc_info=True)
                    continue

                if event is not None:
                    self.event_received.emit(event)
