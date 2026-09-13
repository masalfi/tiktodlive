"""Registry file media untuk overlay.

Overlay berjalan di browser (OBS Browser Source), jadi file lokal tidak
bisa diakses langsung - harus disajikan lewat HTTP.

Kenapa pakai registry, bukan `?path=/isi/path/apa/saja`: endpoint seperti
itu akan menyajikan file APA PUN di komputer ke siapa saja yang bisa
menghubungi port overlay. Di sini setiap file harus didaftarkan dulu oleh
aplikasi, lalu diakses lewat ID acak. Tidak ada path dari luar yang
dipercaya, jadi tidak ada celah path traversal.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import threading
from pathlib import Path

from app.i18n import tr
log = logging.getLogger(__name__)

# Tipe yang boleh disajikan. Selain ini ditolak.
AUDIO_SUFFIXES = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".apng"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
ALLOWED_SUFFIXES = AUDIO_SUFFIXES | IMAGE_SUFFIXES | VIDEO_SUFFIXES

# Batas ukuran; file raksasa akan membuat overlay tersendat.
MAX_BYTES = 64 * 1024 * 1024

_FALLBACK_MIME = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
    ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac",
    ".opus": "audio/opus", ".webm": "video/webm", ".mp4": "video/mp4",
    ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".apng": "image/apng", ".webp": "image/webp", ".svg": "image/svg+xml",
}


class MediaError(ValueError):
    """File tidak bisa dipakai - pesannya layak ditampilkan ke user."""


# Tanda pengenal di awal file, untuk berkas tanpa ekstensi yang jelas.
# Cache ikon gift misalnya disimpan sebagai ".img" apa pun formatnya.
_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image", "image/png"),
    (b"\xff\xd8\xff", "image", "image/jpeg"),
    (b"GIF87a", "image", "image/gif"),
    (b"GIF89a", "image", "image/gif"),
    (b"BM", "image", "image/bmp"),
]


def sniff(path: Path) -> tuple[str, str]:
    """Tebak (jenis, mime) dari isi file. ('', '') kalau tidak dikenali."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return "", ""

    for signature, kind, mime in _MAGIC:
        if head.startswith(signature):
            return kind, mime
    # WEBP: "RIFF" + 4 byte ukuran + "WEBP"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    return "", ""


def kind_of(path: Path) -> str:
    """audio | image | video, atau '' kalau tidak didukung."""
    suffix = path.suffix.lower()
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    # Ekstensi tidak dikenal - periksa isinya. Ini yang membuat ikon gift
    # (disimpan sebagai .img) tetap bisa disajikan ke overlay.
    return sniff(path)[0]


def mime_of(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    fallback = _FALLBACK_MIME.get(path.suffix.lower())
    if fallback:
        return fallback
    # Browser menolak memutar/menampilkan media dengan Content-Type salah,
    # jadi untuk ekstensi tak dikenal tipe dibaca dari isi file.
    sniffed = sniff(path)[1]
    return sniffed or "application/octet-stream"


class MediaRegistry:
    """Peta ID -> file. Aman dipakai lintas thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, Path] = {}
        self._by_path: dict[str, str] = {}

    def register(self, raw_path: str) -> tuple[str, str]:
        """Daftarkan file. Kembalikan (media_id, jenis).

        Lempar MediaError dengan pesan yang jelas kalau file bermasalah.
        """
        if not raw_path or not str(raw_path).strip():
            raise MediaError(tr("Path file kosong"))

        path = Path(str(raw_path)).expanduser()
        try:
            path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise MediaError(tr("File tidak ditemukan: {path}", path=raw_path)) from exc

        if not path.is_file():
            raise MediaError(tr("Bukan file: {path}", path=path))

        kind = kind_of(path)
        if not kind:
            raise MediaError(
                tr("Format '{ext}' tidak didukung. "
                   "Audio: mp3/wav/ogg/m4a - Gambar: png/jpg/gif/webp - Video: mp4/webm",
                   ext=path.suffix)
            )

        try:
            size = path.stat().st_size
        except OSError as exc:
            raise MediaError(tr("Tidak bisa membaca file: {sebab}", sebab=exc)) from exc

        if size == 0:
            raise MediaError(tr("File kosong: {nama}", nama=path.name))
        if size > MAX_BYTES:
            raise MediaError(
                tr("File terlalu besar ({mb} MB, maks {maks} MB)",
                   mb=f"{size / 1048576:.0f}", maks=MAX_BYTES // 1048576)
            )

        key = str(path)
        with self._lock:
            existing = self._by_path.get(key)
            if existing is not None:
                return existing, kind
            # ID diturunkan dari path supaya stabil antar restart, tapi
            # tetap tidak membocorkan isi path ke URL.
            media_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
            self._by_id[media_id] = path
            self._by_path[key] = media_id
        return media_id, kind

    def resolve(self, media_id: str) -> Path | None:
        """Ambil path dari ID. None kalau tidak terdaftar."""
        with self._lock:
            path = self._by_id.get(media_id)
        # File bisa saja dihapus/dipindah setelah didaftarkan.
        if path is not None and path.is_file():
            return path
        return None

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._by_path.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_id)


# Registry bersama satu aplikasi.
REGISTRY = MediaRegistry()
