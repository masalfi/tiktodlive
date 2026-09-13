"""Aksi yang dijalankan di PC host (bukan di device Android)."""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.actions.base import ActionSpec, ParamSpec, register
from app.config import SFX_DIR
from app.i18n import tr
from app.models import ActionResult

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

#: Penanda "pesan terkirim tapi tidak ada yang menerima". Panel overlay
#: mencocokkan tr() dari konstanta ini, jadi jangan disalin sebagai literal.
NO_LISTENER = "tapi belum ada overlay yang membukanya"

# Tombol umum untuk pynput; string lain diperlakukan sebagai karakter biasa.
SPECIAL_KEYS = [
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "space", "enter", "esc", "tab", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "page_up", "page_down",
]


class HostExecutor:
    """State bersama untuk aksi host: overlay, scrcpy, dan pemutar suara."""

    def __init__(self, overlay_server=None, scrcpy_path: str = "", scrcpy_runner=None) -> None:
        self.overlay = overlay_server
        self.scrcpy_path = scrcpy_path
        # Runner & opsi dibagi dengan tab scrcpy, supaya aksi rule memakai
        # pengaturan yang sama dengan yang kamu atur di UI.
        self.scrcpy_runner = scrcpy_runner
        self.scrcpy_options = None
        self.adb_serial = ""
        self._sound_player = None       # diisi GUI (QSoundEffect butuh QApplication)
        self._procs: list[subprocess.Popen] = []

    def set_sound_player(self, player) -> None:
        """GUI menyuntikkan pemutar berbasis Qt; tanpa ini suara dilewati."""
        self._sound_player = player

    def play_sound(self, path: Path, volume: float) -> tuple[bool, str]:
        if self._sound_player is None:
            return False, tr("Pemutar suara belum siap (jalankan lewat GUI)")
        return self._sound_player(path, volume)

    def cleanup(self) -> None:
        """Matikan proses anak (mis. scrcpy) saat aplikasi ditutup."""
        for proc in self._procs:
            if proc.poll() is None:
                proc.terminate()
        self._procs.clear()
        if self.scrcpy_runner is not None:
            self.scrcpy_runner.stop_all()


def _ok(t: str, started: float, msg: str) -> ActionResult:
    return ActionResult(t, True, msg, int((time.time() - started) * 1000))


def _fail(t: str, started: float, msg: str) -> ActionResult:
    return ActionResult(t, False, msg, int((time.time() - started) * 1000))


def _resolve_sound(name: str) -> Path | None:
    """Terima path absolut atau nama file relatif terhadap assets/sfx."""
    if not name:
        return None
    direct = Path(name).expanduser()
    if direct.is_absolute() and direct.exists():
        return direct
    candidate = SFX_DIR / name
    if candidate.exists():
        return candidate
    return direct if direct.exists() else None


# ---------------------------------------------------------------- handlers

def _h_sound(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    path = _resolve_sound(str(p.get("file") or ""))
    if path is None:
        return _fail("host.sound", started, tr("File suara tidak ditemukan: {file}", file=p.get("file")))
    volume = max(0.0, min(1.0, float(p.get("volume", 1.0))))
    ok, msg = host.play_sound(path, volume)
    return _ok("host.sound", started, tr("putar {nama}", nama=path.name)) if ok else _fail("host.sound", started, msg)


def _h_script(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    raw = str(p.get("command") or "").strip()
    if not raw:
        return _fail("host.script", started, tr("Perintah kosong"))
    timeout = max(1, int(p.get("timeout_sec", 30)))
    try:
        args = shlex.split(raw, posix=(sys.platform != "win32"))
    except ValueError as exc:
        return _fail("host.script", started, tr("Perintah tidak valid: {sebab}", sebab=exc))
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True,
            timeout=timeout, creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return _fail("host.script", started, tr("Timeout setelah {detik}s", detik=timeout))
    except (OSError, ValueError) as exc:
        return _fail("host.script", started, tr("Gagal menjalankan: {sebab}", sebab=exc))

    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or out or "").strip() or f"exit code {proc.returncode}"
        return _fail("host.script", started, err[:300])
    return _ok("host.script", started, out[:300] or "selesai")


def _h_keypress(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    key_name = str(p.get("key") or "").strip()
    if not key_name:
        return _fail("host.keypress", started, tr("Tombol kosong"))
    try:
        from pynput.keyboard import Controller, Key
    except ImportError:
        return _fail("host.keypress", started, tr("pynput belum terinstall"))

    modifiers = [m.strip().lower() for m in str(p.get("modifiers") or "").split(",") if m.strip()]
    keyboard = Controller()

    def resolve(name: str):
        attr = getattr(Key, name.lower(), None)
        if attr is not None:
            return attr
        return name if len(name) == 1 else None

    target = resolve(key_name)
    if target is None:
        return _fail("host.keypress", started, tr("Tombol tidak dikenal: {tombol}", tombol=key_name))

    mod_keys = [resolve(m) for m in modifiers]
    if any(m is None for m in mod_keys):
        return _fail("host.keypress", started, tr("Modifier tidak dikenal: {modifier}", modifier=modifiers))

    try:
        for mod in mod_keys:
            keyboard.press(mod)
        keyboard.press(target)
        keyboard.release(target)
        for mod in reversed(mod_keys):
            keyboard.release(mod)
    except Exception as exc:                        # noqa: BLE001 - pynput bisa gagal karena izin OS
        return _fail(
            "host.keypress", started,
            tr("Gagal menekan tombol: {sebab} (macOS: beri izin Accessibility)", sebab=exc),
        )

    combo = "+".join([*modifiers, key_name])
    return _ok("host.keypress", started, tr("tekan {kombinasi}", kombinasi=combo))


def _h_overlay(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    if host.overlay is None or not host.overlay.running:
        return _fail("host.overlay", started, tr("Server overlay tidak aktif"))
    payload = {
        "type": "alert",
        "style": str(p.get("style") or "info"),
        "title": str(p.get("title") or ""),
        "subtitle": str(p.get("subtitle") or ""),
        "duration": int(p.get("duration_ms", 5000)),
    }
    return _send_overlay(host, "host.overlay", started, payload, str(p.get("channel") or ""))


def _overlay_ready(host: HostExecutor, action_type: str, started: float):
    """Cek server overlay siap. Kembalikan ActionResult kalau tidak."""
    if host.overlay is None or not host.overlay.running:
        return _fail(action_type, started,
                     tr("Server overlay tidak aktif - cek tab Overlay atau setelan port."))
    return None


def _send_overlay(host: HostExecutor, action_type: str, started: float, payload: dict,
                  channel: str = "") -> ActionResult:
    from app.overlay.server import normalize_channel

    name = normalize_channel(channel)
    sent = host.overlay.send(payload, channel)
    if sent == 0:
        # Sebutkan channel-nya: penyebab tersering adalah Browser Source
        # untuk channel itu belum dibuka (atau URL-nya salah ketik).
        return _ok(
            action_type, started,
            tr("terkirim ke channel '{channel}'", channel=name) + ", " + tr(NO_LISTENER),
        )
    return _ok(action_type, started, tr("terkirim ke {n} overlay (channel '{channel}')", n=sent, channel=name))


def _h_overlay_sound(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    """Putar suara DI DALAM overlay, jadi OBS menangkapnya langsung."""
    started = time.time()
    problem = _overlay_ready(host, "host.overlay_sound", started)
    if problem:
        return problem

    from app.overlay.media import MediaError

    try:
        url, kind = host.overlay.media_url(str(p.get("file") or ""))
    except MediaError as exc:
        return _fail("host.overlay_sound", started, str(exc))
    if kind != "audio":
        return _fail("host.overlay_sound", started, tr("File ini bertipe {tipe}, bukan audio", tipe=kind))

    return _send_overlay(host, "host.overlay_sound", started, {
        "type": "sound",
        "url": url,
        "volume": max(0.0, min(1.0, float(p.get("volume", 1.0)))),
    }, str(p.get("channel") or ""))


def _h_overlay_music(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    """Musik latar: mulai, hentikan, atau ubah volume - dengan fade."""
    started = time.time()
    problem = _overlay_ready(host, "host.overlay_music", started)
    if problem:
        return problem

    from app.overlay.media import MediaError

    action = str(p.get("action") or "play")
    payload: dict[str, Any] = {
        "type": "music",
        "action": action,
        "volume": max(0.0, min(1.0, float(p.get("volume", 0.5)))),
        "fade_ms": max(0, int(p.get("fade_ms", 800))),
        "loop": bool(p.get("loop", True)),
    }

    if action == "play":
        try:
            url, kind = host.overlay.media_url(str(p.get("file") or ""))
        except MediaError as exc:
            return _fail("host.overlay_music", started, str(exc))
        if kind != "audio":
            return _fail("host.overlay_music", started, tr("File ini bertipe {tipe}, bukan audio", tipe=kind))
        payload["url"] = url

    return _send_overlay(host, "host.overlay_music", started, payload,
                         str(p.get("channel") or ""))


def _rain_image(host: HostExecutor, p: dict[str, Any], payload: dict, started: float):
    """Hujan memakai file gambar pilihan user."""
    from app.overlay.media import MediaError

    raw = str(p.get("file") or "").strip()
    if not raw:
        return _fail("host.overlay_effect", started,
                     tr("Sumber 'gambar' dipilih tapi file belum diisi"))
    try:
        url, kind = host.overlay.media_url(raw)
    except MediaError as exc:
        return _fail("host.overlay_effect", started, str(exc))
    if kind != "image":
        return _fail("host.overlay_effect", started,
                     tr("File ini bertipe {tipe}, bukan gambar", tipe=kind))
    payload["image"] = url
    return None


def _rain_gift_icon(host: HostExecutor, p: dict[str, Any], payload: dict, started: float):
    """Hujan memakai ikon gift yang memicu rule.

    gift_id datang dari placeholder {gift_id}; kalau rule dipicu event
    non-gift (mis. komentar) nilainya kosong, jadi kembali ke emoji.
    """
    from app.live.gifts import ensure_icon
    from app.overlay.media import MediaError

    raw = str(p.get("gift_id") or "").strip()
    if not raw.isdigit():
        # Bukan event gift - jangan gagal, cukup pakai emoji cadangan.
        payload["emoji"] = str(p.get("emoji") or "\U0001F381")
        return None

    path = ensure_icon(int(raw))
    if path is None:
        payload["emoji"] = str(p.get("emoji") or "\U0001F381")
        return None

    try:
        url, _ = host.overlay.media_url(str(path))
    except MediaError as exc:
        return _fail("host.overlay_effect", started, str(exc))
    payload["image"] = url
    return None


def _h_overlay_effect(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    """Efek visual: confetti, getar, kilat, teks melayang, hujan emoji."""
    started = time.time()
    problem = _overlay_ready(host, "host.overlay_effect", started)
    if problem:
        return problem

    effect = str(p.get("effect") or "confetti")
    payload: dict[str, Any] = {"type": "effect", "effect": effect}

    if effect == "confetti":
        payload["count"] = max(1, min(400, int(p.get("count", 80))))
    elif effect == "shake":
        payload["duration"] = max(100, int(p.get("duration_ms", 500)))
    elif effect == "flash":
        payload["color"] = str(p.get("color") or "#ffffff")
        payload["duration"] = max(60, int(p.get("duration_ms", 150)))
    elif effect == "text":
        payload["text"] = str(p.get("text") or "")
        payload["color"] = str(p.get("color") or "")
    elif effect == "rain":
        payload["count"] = max(1, min(80, int(p.get("count", 20))))
        payload["size"] = max(16, min(200, int(p.get("size_px", 44))))

        sumber = str(p.get("sumber") or "emoji").strip().lower()
        if sumber == "gift":
            # Pakai ikon gift yang memicu rule ini. gift_id diisi otomatis
            # oleh placeholder {gift_id} saat rule dijalankan.
            problem = _rain_gift_icon(host, p, payload, started)
            if problem is not None:
                return problem
        elif sumber == "gambar":
            problem = _rain_image(host, p, payload, started)
            if problem is not None:
                return problem
        else:
            payload["emoji"] = str(p.get("emoji") or "\U0001F381")

    return _send_overlay(host, "host.overlay_effect", started, payload,
                         str(p.get("channel") or ""))


def _effect_handler(effect: str, action_type: str):
    """Buat handler untuk satu jenis efek.

    Sebelumnya semua efek berbagi satu aksi "Efek visual overlay" dengan
    kolom yang tidak semuanya relevan - pengguna harus menebak mana yang
    berlaku. Sekarang tiap efek punya aksinya sendiri dengan kolom yang
    memang dipakai saja.
    """

    def handler(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
        merged = dict(p)
        merged["effect"] = effect
        result = _h_overlay_effect(host, merged)
        result.action_type = action_type
        return result

    return handler


def _h_launch_scrcpy(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    from app.scrcpy.bridge import ScrcpyOptions
    from app.scrcpy.manager import find_scrcpy

    info = find_scrcpy(host.scrcpy_path)
    if not info.available:
        return _fail(
            "host.launch_scrcpy", started,
            tr("scrcpy belum tersedia. Buka tab 'scrcpy' lalu klik 'Unduh scrcpy' (sekali saja)."),
        )

    # Pakai opsi dari tab scrcpy; kalau belum ada, pakai bawaan.
    options = host.scrcpy_options or ScrcpyOptions()
    extra = str(p.get("extra_args") or "").strip()
    if extra:
        import copy

        options = copy.deepcopy(options)
        options.extra_args = (options.extra_args + " " + extra).strip()

    if host.scrcpy_runner is None:
        from app.scrcpy.runner import ScrcpyRunner

        host.scrcpy_runner = ScrcpyRunner()

    ok, message = host.scrcpy_runner.start(info.path, options, host.adb_serial)
    return _ok("host.launch_scrcpy", started, message) if ok else _fail("host.launch_scrcpy", started, message)


def _h_stop_scrcpy(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    if host.scrcpy_runner is None:
        return _ok("host.stop_scrcpy", started, tr("scrcpy tidak berjalan"))
    stopped = host.scrcpy_runner.stop(host.adb_serial)
    return _ok("host.stop_scrcpy", started, tr("dihentikan") if stopped else tr("tidak ada yang berjalan"))


def _h_wait(host: HostExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    seconds = max(0.0, min(60.0, float(p.get("seconds", 1.0))))
    time.sleep(seconds)
    return _ok("host.wait", started, tr("tunggu {detik}s", detik=seconds))


# --------------------------------------------------------------- registrasi

def register_host_actions() -> None:
    CHANNEL = ParamSpec(
        "channel", "Channel overlay", "str", "",
        help="kosong = overlay utama; isi mis. 'alert' untuk Browser Source terpisah",
    )

    # ---------------------------------------------------------- overlay
    register(
        ActionSpec("host.overlay", "Notifikasi teks", "overlay", [
            ParamSpec("title", "Judul", "str", ""),
            ParamSpec("subtitle", "Subjudul", "str", ""),
            ParamSpec("style", "Gaya", "choice", "gift",
                      choices=["gift", "comment", "follow", "share", "like", "danger", "info"]),
            ParamSpec("duration_ms", "Durasi (ms)", "int", 5000),
            CHANNEL,
        ], order=10, help="Placeholder: {user}, {gift}, {count}, {coins}, {comment}"),
        _h_overlay,
    )
    register(
        ActionSpec("host.overlay_sound", "Suara", "overlay", [
            ParamSpec("file", "File audio", "file", "", help="mp3/wav/ogg - path lengkap"),
            ParamSpec("volume", "Volume (0-1)", "float", 1.0),
            CHANNEL,
        ], order=20, help="Diputar di overlay, jadi OBS menangkapnya tanpa Desktop Audio"),
        _h_overlay_sound,
    )
    register(
        ActionSpec("host.overlay_music", "Musik latar", "overlay", [
            ParamSpec("action", "Aksi", "choice", "play", choices=["play", "stop", "volume"]),
            ParamSpec("file", "File audio", "file", "", help="hanya untuk aksi 'play'"),
            ParamSpec("volume", "Volume (0-1)", "float", 0.5),
            ParamSpec("fade_ms", "Fade (ms)", "int", 800),
            ParamSpec("loop", "Ulangi terus", "bool", True),
            CHANNEL,
        ], order=30, help="Musik yang diulang; 'stop' menghentikannya dengan fade"),
        _h_overlay_music,
    )

    # --- efek visual: satu aksi per efek, bukan satu aksi serba guna ---
    register(
        ActionSpec("overlay.rain", "Hujan (emoji / ikon gift / gambar)", "overlay", [
            ParamSpec("sumber", "Hujan pakai", "choice", "gift",
                      choices=["gift", "emoji", "gambar"],
                      help="gift = ikon gift yang memicu rule ini"),
            ParamSpec("emoji", "Emoji", "str", "\U0001F381",
                      help="dipakai kalau sumber = emoji"),
            ParamSpec("file", "Gambar", "file", "",
                      help="dipakai kalau sumber = gambar"),
            ParamSpec("count", "Jumlah", "int", 25),
            ParamSpec("size_px", "Ukuran (px)", "int", 56),
            ParamSpec("gift_id", "ID gift", "str", "{gift_id}",
                      help="biarkan {gift_id} - terisi otomatis dari gift yang masuk"),
            CHANNEL,
        ], order=40, help="Sumber 'gift': ikon gift yang memicu rule ini yang berjatuhan"),
        _effect_handler("rain", "overlay.rain"),
    )
    register(
        ActionSpec("overlay.confetti", "Confetti", "overlay", [
            ParamSpec("count", "Jumlah", "int", 80),
            CHANNEL,
        ], order=50),
        _effect_handler("confetti", "overlay.confetti"),
    )
    register(
        ActionSpec("overlay.text", "Teks melayang", "overlay", [
            ParamSpec("text", "Teks", "str", "{user}"),
            ParamSpec("color", "Warna", "str", "#ffd24d"),
            CHANNEL,
        ], order=60, help="Placeholder {user}, {gift}, {count} bisa dipakai"),
        _effect_handler("text", "overlay.text"),
    )
    register(
        ActionSpec("overlay.shake", "Layar bergetar", "overlay", [
            ParamSpec("duration_ms", "Durasi (ms)", "int", 600),
            CHANNEL,
        ], order=70),
        _effect_handler("shake", "overlay.shake"),
    )
    register(
        ActionSpec("overlay.flash", "Kilat warna", "overlay", [
            ParamSpec("color", "Warna", "str", "#ffffff"),
            ParamSpec("duration_ms", "Durasi (ms)", "int", 150),
            CHANNEL,
        ], order=80),
        _effect_handler("flash", "overlay.flash"),
    )

    # Aksi lama: tetap jalan untuk rule yang sudah ada, tapi tidak
    # ditampilkan lagi karena sudah digantikan lima aksi di atas.
    register(
        ActionSpec("host.overlay_effect", "Efek visual overlay (lama)", "overlay", [
            ParamSpec("effect", "Efek", "choice", "confetti",
                      choices=["confetti", "shake", "flash", "text", "rain"]),
            ParamSpec("count", "Jumlah", "int", 80),
            ParamSpec("duration_ms", "Durasi (ms)", "int", 500),
            ParamSpec("color", "Warna", "str", "#ffffff"),
            ParamSpec("text", "Teks", "str", ""),
            ParamSpec("sumber", "Hujan pakai", "choice", "emoji",
                      choices=["emoji", "gift", "gambar"]),
            ParamSpec("emoji", "Emoji", "str", "\U0001F381"),
            ParamSpec("file", "File gambar", "file", ""),
            ParamSpec("gift_id", "ID gift", "str", "{gift_id}"),
            ParamSpec("size_px", "Ukuran (px)", "int", 44),
            CHANNEL,
        ], hidden=True),
        _h_overlay_effect,
    )

    register(
        ActionSpec("host.sound", "Mainkan suara di PC", "host", [
            ParamSpec("file", "File", "file", "", help="Nama file di assets/sfx atau path lengkap"),
            ParamSpec("volume", "Volume (0-1)", "float", 1.0),
        ]),
        _h_sound,
    )
    register(
        ActionSpec("host.script", "Jalankan script/program", "host", [
            ParamSpec("command", "Perintah", "str", ""),
            ParamSpec("timeout_sec", "Timeout (detik)", "int", 30),
        ], dangerous=True),
        _h_script,
    )
    register(
        ActionSpec("host.keypress", "Tekan tombol di PC", "host", [
            ParamSpec("key", "Tombol", "str", "f1", help="Contoh: a, f1, f2, f3, space, enter, esc"),
            ParamSpec("modifiers", "Modifier (pisah koma)", "str", "", help="ctrl, alt, shift, cmd"),
        ], help="macOS butuh izin Accessibility untuk aplikasi ini"),
        _h_keypress,
    )
    register(
        ActionSpec("host.launch_scrcpy", "Jalankan scrcpy", "host", [
            ParamSpec("extra_args", "Argumen tambahan", "str", ""),
        ], help="Memakai pengaturan dari tab scrcpy"),
        _h_launch_scrcpy,
    )
    register(
        ActionSpec("host.stop_scrcpy", "Hentikan scrcpy", "host", []),
        _h_stop_scrcpy,
    )
    register(
        ActionSpec("host.wait", "Tunggu", "host", [
            ParamSpec("seconds", "Detik", "float", 1.0),
        ]),
        _h_wait,
    )
