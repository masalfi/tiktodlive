"""Overlay HTTP + WebSocket server untuk OBS Browser Source.

Berjalan di event loop asyncio milik OverlayThread sendiri, jadi bisa
dinyalakan tanpa bergantung pada koneksi TikTok.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from app.overlay.media import REGISTRY, mime_of

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Nama channel bawaan, dipakai overlay yang dibuka tanpa ?ch=
DEFAULT_CHANNEL = "main"
# Nilai khusus untuk mengirim ke SEMUA channel sekaligus.
ALL_CHANNELS = "*"

_CHANNEL_SAFE = re.compile(r"[^a-z0-9_-]+")


def normalize_channel(name: str) -> str:
    """Samakan penulisan channel supaya 'Alert', 'alert ', dan 'ALERT'
    menunjuk ke overlay yang sama."""
    cleaned = _CHANNEL_SAFE.sub("-", str(name or "").strip().lower()).strip("-")
    return cleaned or DEFAULT_CHANNEL


class OverlayServer:
    """Server aiohttp + broadcast WebSocket ke semua klien overlay."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8777) -> None:
        self.host = host
        self.port = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        # ws -> nama channel. Satu server melayani banyak Browser Source,
        # masing-masing memakai channel sendiri lewat ?ch=<nama>.
        self._clients: dict[web.WebSocketResponse, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: str = ""

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Nyalakan server di thread + event loop sendiri."""
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._error = ""
        self._thread = threading.Thread(target=self._run_loop, name="OverlayServer", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._error)

    @property
    def error(self) -> str:
        return self._error

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/overlay"

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._startup())
            self._ready.set()
            self._loop.run_forever()
        except OSError as exc:
            self._error = f"Port {self.port} tidak bisa dipakai: {exc}"
            log.error(self._error)
            self._ready.set()
        except Exception as exc:                    # noqa: BLE001
            self._error = str(exc)
            log.exception("Overlay server error")
            self._ready.set()
        finally:
            try:
                self._loop.close()
            except Exception:                       # noqa: BLE001
                pass

    async def _startup(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/overlay", self._handle_index)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_get("/media/{media_id}", self._handle_media)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        log.info("Overlay aktif di %s", self.url)

    async def _shutdown(self) -> None:
        for ws in list(self._clients):
            await ws.close()
        self._clients.clear()
        if self._runner:
            await self._runner.cleanup()
        self._loop.stop()

    # -------------------------------------------------------------- handlers

    async def _handle_index(self, request: web.Request) -> web.Response:
        path = STATIC_DIR / "overlay.html"
        if not path.exists():
            return web.Response(text="overlay.html tidak ditemukan", status=500)
        return web.Response(text=path.read_text(encoding="utf-8"), content_type="text/html")

    async def _handle_media(self, request: web.Request) -> web.StreamResponse:
        """Sajikan file media yang sudah terdaftar.

        Hanya menerima ID dari registry - path dari URL tidak pernah
        dipakai, jadi tidak ada risiko path traversal.
        """
        media_id = request.match_info.get("media_id", "")
        path = REGISTRY.resolve(media_id)
        if path is None:
            return web.Response(text="media tidak ditemukan", status=404)

        # FileResponse menangani header Range sendiri - dibutuhkan browser
        # untuk seek audio/video, dan sebagian browser menolak memutar
        # media yang servernya tidak mendukung Range.
        return web.FileResponse(
            path,
            headers={
                "Content-Type": mime_of(path),
                "Cache-Control": "no-cache",
                "Accept-Ranges": "bytes",
            },
        )

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        channel = normalize_channel(request.query.get("ch", ""))
        self._clients[ws] = channel
        try:
            async for msg in ws:
                # Klien overlay tidak mengirim apa-apa; cukup abaikan.
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._clients.pop(ws, None)
        return ws

    # ------------------------------------------------------------- broadcast

    def media_url(self, file_path: str) -> tuple[str, str]:
        """Daftarkan file lalu kembalikan (url_relatif, jenis).

        Lempar MediaError kalau file tidak layak.
        """
        media_id, kind = REGISTRY.register(file_path)
        return f"/media/{media_id}", kind

    def send(self, payload: dict[str, Any], channel: str | None = None) -> int:
        """Kirim ke satu channel. Kembalikan jumlah overlay yang menerima.

        channel None/"" = channel utama. ALL_CHANNELS = semua overlay.
        """
        if not self._loop or not self._loop.is_running():
            return 0
        target = ALL_CHANNELS if channel == ALL_CHANNELS else normalize_channel(channel or "")
        future = asyncio.run_coroutine_threadsafe(self._broadcast(payload, target), self._loop)
        try:
            return future.result(timeout=2)
        except Exception:                           # noqa: BLE001
            return 0

    def channels(self) -> dict[str, int]:
        """Channel yang sedang terhubung -> jumlah overlay-nya."""
        counts: dict[str, int] = {}
        for ws, name in list(self._clients.items()):
            if not ws.closed:
                counts[name] = counts.get(name, 0) + 1
        return counts

    def channel_url(self, channel: str = "") -> str:
        """URL untuk dipasang di OBS Browser Source."""
        name = normalize_channel(channel)
        if name == DEFAULT_CHANNEL:
            return self.url
        return f"{self.url}?ch={name}"

    async def _broadcast(self, payload: dict[str, Any], channel: str) -> int:
        data = json.dumps(payload)
        sent = 0
        for ws, name in list(self._clients.items()):
            if ws.closed:
                self._clients.pop(ws, None)
                continue
            if channel != ALL_CHANNELS and name != channel:
                continue
            try:
                await ws.send_str(data)
                sent += 1
            except (ConnectionResetError, RuntimeError):
                self._clients.pop(ws, None)
        return sent
