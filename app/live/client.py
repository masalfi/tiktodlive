"""Koneksi TikTok LIVE di QThread dengan event loop asyncio sendiri.

TikTokLiveClient berbasis asyncio dan akan memblokir GUI kalau dijalankan
di thread Qt. Karena itu loop-nya hidup di thread terpisah, dan hasilnya
dikirim ke GUI lewat Qt Signal (satu-satunya cara aman lintas thread).
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import QThread, Signal

from app.live.normalizer import (
    normalize_comment,
    normalize_gift,
    normalize_like,
    normalize_simple,
)

log = logging.getLogger(__name__)

# Status koneksi yang dipancarkan ke GUI
STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_LIVE = "live"
STATE_ERROR = "error"


class TikTokWorker(QThread):
    """Menjalankan TikTokLiveClient dan memancarkan LiveEvent ke GUI."""

    event_received = Signal(object)         # LiveEvent
    status_changed = Signal(str, str)       # state, pesan
    viewer_count = Signal(int)
    gifts_updated = Signal(int)             # jumlah gift baru dari room

    def __init__(self, username: str, sign_api_key: str = "", auto_reconnect: bool = True) -> None:
        super().__init__()
        self.username = username.strip().lstrip("@")
        self.sign_api_key = sign_api_key.strip()
        self.auto_reconnect = auto_reconnect

        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._should_stop = False

    # ------------------------------------------------------------- lifecycle

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:                    # noqa: BLE001
            log.exception("Worker TikTok berhenti")
            self.status_changed.emit(STATE_ERROR, str(exc))
        finally:
            try:
                self._loop.close()
            except Exception:                       # noqa: BLE001
                pass
            self.status_changed.emit(STATE_DISCONNECTED, "Terputus")

    def stop(self) -> None:
        """Minta worker berhenti (aman dipanggil dari thread GUI)."""
        self._should_stop = True
        if self._loop and self._loop.is_running() and self._client is not None:
            asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)

    async def _disconnect(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:                           # noqa: BLE001
            pass

    # ------------------------------------------------------------------ main

    async def _main(self) -> None:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.client.errors import UserOfflineError
        from TikTokLive.client.web.web_settings import WebDefaults

        if self.sign_api_key:
            # Menaikkan rate limit sign server EulerStream.
            WebDefaults.tiktok_sign_api_key = self.sign_api_key

        backoff = 3
        while not self._should_stop:
            self.status_changed.emit(STATE_CONNECTING, f"Menyambung ke @{self.username}...")
            self._client = TikTokLiveClient(unique_id=self.username)
            self._wire_listeners(self._client)

            try:
                # fetch_gift_info=True mengambil daftar gift yang benar-benar
                # tersedia di room ini, termasuk gift eksklusif/musiman.
                await self._client.connect(fetch_gift_info=True)
                # connect() kembali normal saat live berakhir / disconnect.
                if self._should_stop:
                    break
                self.status_changed.emit(STATE_DISCONNECTED, "Koneksi berakhir")
            except UserOfflineError:
                self.status_changed.emit(
                    STATE_ERROR, f"@{self.username} sedang tidak live."
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:                # noqa: BLE001
                message = self._explain_error(exc)
                fatal = self._is_fatal(exc)
                self.status_changed.emit(STATE_ERROR, message)
                if fatal:
                    # Reconnect tidak akan menolong dan hanya membakar kuota
                    # sign server, jadi berhenti dan biarkan user bertindak.
                    return

            if self._should_stop or not self.auto_reconnect:
                break

            # Backoff eksponensial supaya tidak membanjiri sign server.
            self.status_changed.emit(STATE_CONNECTING, f"Mencoba lagi dalam {backoff}s...")
            for _ in range(backoff * 10):
                if self._should_stop:
                    return
                await asyncio.sleep(0.1)
            backoff = min(backoff * 2, 60)

    @staticmethod
    def _is_fatal(exc: Exception) -> bool:
        """Error yang tidak akan sembuh dengan mencoba ulang."""
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        return status in (400, 401, 403)

    @staticmethod
    def _explain_error(exc: Exception) -> str:
        """Ubah error mentah jadi penjelasan yang bisa ditindaklanjuti."""
        name = type(exc).__name__
        message = str(exc)
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)

        # TikTok/EulerStream menolak handshake WebSocket. Ini terjadi ketika
        # sign server tidak bisa memberi URL TikTok asli dan mengembalikan
        # proxy fallback miliknya, yang butuh API key berbayar.
        if status in (400, 401, 403):
            return (
                f"WebSocket ditolak (HTTP {status}). Sign server gratis "
                "(EulerStream) sedang tidak bisa memberi koneksi langsung ke "
                "TikTok dan mengalihkan ke proxy fallback yang butuh API key. "
                "Isi 'Sign API key' di tab Koneksi, atau coba lagi nanti. "
                "Ini batasan layanan pihak ketiga, bukan kesalahan aplikasi."
            )

        if "Sign" in name or "sign" in message.lower():
            return (
                f"Sign server bermasalah/rate limit ({message}). "
                "Coba lagi sebentar, atau isi sign_api_key di settings."
            )

        return f"{name}: {message}" if message else name

    def _merge_room_gifts(self, client) -> None:
        """Tambahkan gift khusus room ini ke katalog global."""
        info = getattr(client, "gift_info", None)
        if not info:
            return
        raw = info.get("gifts") if isinstance(info, dict) else None
        if not raw:
            return
        try:
            from app.live.gifts import CATALOG
            added = CATALOG.merge_from_raw(raw, "room")
        except Exception as exc:                    # noqa: BLE001
            log.warning("Gagal menggabungkan gift room: %s", exc)
            return
        if added:
            self.gifts_updated.emit(added)

    def _wire_listeners(self, client) -> None:
        from TikTokLive.events import (
            CommentEvent,
            ConnectEvent,
            DisconnectEvent,
            FollowEvent,
            GiftEvent,
            JoinEvent,
            LikeEvent,
            LiveEndEvent,
            ShareEvent,
        )

        async def on_connect(_event) -> None:
            room = getattr(client, "room_id", "?")
            self.status_changed.emit(STATE_LIVE, f"Terhubung ke @{self.username} (room {room})")
            self._merge_room_gifts(client)

        async def on_disconnect(_event) -> None:
            self.status_changed.emit(STATE_DISCONNECTED, "Terputus dari live")

        async def on_live_end(_event) -> None:
            self.status_changed.emit(STATE_DISCONNECTED, "Live telah berakhir")

        async def on_gift(event) -> None:
            gift = getattr(event, "gift", None)
            if gift is None:
                return
            # Gift streakable memancarkan event berkali-kali selama streak.
            # Hanya hitung saat streak selesai, kalau tidak satu streak bisa
            # memicu aksi puluhan kali.
            if getattr(gift, "type", 0) == 1:
                if event.streaking:
                    return
                count = int(getattr(event, "repeat_count", 1) or 1)
            else:
                count = 1
            self.event_received.emit(normalize_gift(event, count))

        async def on_comment(event) -> None:
            self.event_received.emit(normalize_comment(event))

        async def on_like(event) -> None:
            self.event_received.emit(normalize_like(event))
            total = getattr(event, "total", None)
            if total:
                self.viewer_count.emit(int(total))

        async def on_follow(event) -> None:
            self.event_received.emit(normalize_simple(event, "follow"))

        async def on_share(event) -> None:
            self.event_received.emit(normalize_simple(event, "share"))

        async def on_join(event) -> None:
            self.event_received.emit(normalize_simple(event, "join"))

        client.add_listener(ConnectEvent, on_connect)
        client.add_listener(DisconnectEvent, on_disconnect)
        client.add_listener(LiveEndEvent, on_live_end)
        client.add_listener(GiftEvent, on_gift)
        client.add_listener(CommentEvent, on_comment)
        client.add_listener(LikeEvent, on_like)
        client.add_listener(FollowEvent, on_follow)
        client.add_listener(ShareEvent, on_share)
        client.add_listener(JoinEvent, on_join)
