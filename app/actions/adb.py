"""Eksekutor aksi ADB.

Semua perintah dijalankan via subprocess dengan argumen list (tanpa
shell=True) dan timeout wajib. Di Windows dipakai CREATE_NO_WINDOW supaya
jendela konsol tidak berkedip tiap aksi.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.actions.base import ActionSpec, ParamSpec, register
from app.config import find_adb
from app.i18n import tr
from app.models import ActionResult

# Windows: sembunyikan jendela konsol
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

KEYCODES = [
    "KEYCODE_HOME", "KEYCODE_BACK", "KEYCODE_APP_SWITCH", "KEYCODE_POWER",
    "KEYCODE_VOLUME_UP", "KEYCODE_VOLUME_DOWN", "KEYCODE_VOLUME_MUTE",
    "KEYCODE_ENTER", "KEYCODE_DEL", "KEYCODE_TAB", "KEYCODE_SEARCH",
    "KEYCODE_MEDIA_PLAY_PAUSE", "KEYCODE_MEDIA_NEXT", "KEYCODE_MEDIA_PREVIOUS",
    "KEYCODE_DPAD_UP", "KEYCODE_DPAD_DOWN", "KEYCODE_DPAD_LEFT", "KEYCODE_DPAD_RIGHT",
    "KEYCODE_CAMERA", "KEYCODE_WAKEUP", "KEYCODE_SLEEP",
]


class AdbError(RuntimeError):
    pass


class AdbExecutor:
    """Pembungkus tipis di atas binary adb."""

    def __init__(self, adb_path: str = "", serial: str = "", timeout: int = 15) -> None:
        self.adb_path = find_adb(adb_path)
        self.serial = serial
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.adb_path)

    def set_serial(self, serial: str) -> None:
        self.serial = serial

    def _base_cmd(self) -> list[str]:
        if not self.adb_path:
            raise AdbError(
                tr("adb tidak ditemukan. Install Android platform-tools atau isi "
                   "path-nya di config/settings.yaml (adb.path).")
            )
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def run(self, args: list[str], timeout: int | None = None, binary: bool = False):
        """Jalankan `adb [-s serial] <args>`; kembalikan CompletedProcess."""
        cmd = self._base_cmd() + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=not binary,
            timeout=timeout or self.timeout,
            creationflags=_NO_WINDOW,
        )

    def shell(self, args: list[str], timeout: int | None = None):
        return self.run(["shell", *args], timeout=timeout)

    def list_devices(self) -> list[dict[str, str]]:
        """Parse `adb devices -l` menjadi list dict."""
        if not self.available:
            return []
        try:
            proc = self.run(["devices", "-l"], timeout=10)
        except (subprocess.TimeoutExpired, OSError, AdbError):
            return []
        devices: list[dict[str, str]] = []
        for line in (proc.stdout or "").splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            info = {"serial": parts[0], "state": parts[1], "model": "", "device": ""}
            for token in parts[2:]:
                if ":" in token:
                    key, _, value = token.partition(":")
                    if key in info:
                        info[key] = value
            devices.append(info)
        return devices

    def device_label(self, serial: str) -> str:
        for d in self.list_devices():
            if d["serial"] == serial:
                model = d.get("model") or d.get("device") or ""
                return f"{serial} ({model})" if model else serial
        return serial


def _ok(action_type: str, started: float, message: str = "OK") -> ActionResult:
    return ActionResult(action_type, True, message, int((time.time() - started) * 1000))


def _fail(action_type: str, started: float, message: str) -> ActionResult:
    return ActionResult(action_type, False, message, int((time.time() - started) * 1000))


def _run_guarded(adb: AdbExecutor, action_type: str, args: list[str], success_msg: str) -> ActionResult:
    """Jalankan perintah adb dan bungkus semua error jadi ActionResult."""
    started = time.time()
    try:
        proc = adb.run(args)
    except AdbError as exc:
        return _fail(action_type, started, str(exc))
    except subprocess.TimeoutExpired:
        return _fail(action_type, started, tr("Timeout setelah {detik}s", detik=adb.timeout))
    except OSError as exc:
        return _fail(action_type, started, tr("Gagal menjalankan adb: {sebab}", sebab=exc))

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit code {proc.returncode}"
        return _fail(action_type, started, err)

    # adb shell sering exit 0 walau perintah di device gagal; tampilkan stderr.
    stderr = (proc.stderr or "").strip()
    if stderr:
        return _ok(action_type, started, f"{success_msg} (catatan: {stderr})")
    return _ok(action_type, started, success_msg)


# ---------------------------------------------------------------- handlers

def _h_tap(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    x, y = p.get("x", 0), p.get("y", 0)
    return _run_guarded(adb, "adb.tap", ["shell", "input", "tap", str(x), str(y)], f"tap ({x}, {y})")


def _h_swipe(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    x1, y1 = p.get("x1", 0), p.get("y1", 0)
    x2, y2 = p.get("x2", 0), p.get("y2", 0)
    dur = p.get("duration_ms") or 300
    return _run_guarded(
        adb, "adb.swipe",
        ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(dur)],
        f"swipe ({x1},{y1}) -> ({x2},{y2}) {dur}ms",
    )


def _h_text(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    raw = str(p.get("text") or "")
    if not raw:
        return ActionResult("adb.text", False, tr("Teks kosong"))
    # `input text` tidak menerima spasi literal; %s adalah konvensi Android.
    encoded = raw.replace(" ", "%s")
    return _run_guarded(adb, "adb.text", ["shell", "input", "text", encoded], tr("ketik: {teks}", teks=raw[:40]))


def _h_keyevent(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    key = str(p.get("keycode") or "KEYCODE_HOME")
    return _run_guarded(adb, "adb.keyevent", ["shell", "input", "keyevent", key], tr("keyevent {key}", key=key))


def _h_open_app(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    pkg = str(p.get("package") or "").strip()
    if not pkg:
        return ActionResult("adb.open_app", False, tr("Nama package kosong"))
    return _run_guarded(
        adb, "adb.open_app",
        ["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"],
        tr("buka {package}", package=pkg),
    )


def _h_close_app(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    pkg = str(p.get("package") or "").strip()
    if not pkg:
        return ActionResult("adb.close_app", False, tr("Nama package kosong"))
    return _run_guarded(adb, "adb.close_app", ["shell", "am", "force-stop", pkg], tr("tutup {package}", package=pkg))


def _h_open_url(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    url = str(p.get("url") or "").strip()
    if not url:
        return ActionResult("adb.open_url", False, tr("URL kosong"))
    return _run_guarded(
        adb, "adb.open_url",
        ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url],
        tr("buka {url}", url=url),
    )


def _h_screenshot(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    out_dir = Path(str(p.get("save_dir") or "")).expanduser() if p.get("save_dir") else Path.cwd() / "screenshots"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        proc = adb.run(["exec-out", "screencap", "-p"], binary=True)
        if proc.returncode != 0 or not proc.stdout:
            return _fail("adb.screenshot", started, tr("screencap gagal"))
        path = out_dir / f"shot_{int(time.time())}.png"
        path.write_bytes(proc.stdout)
        return _ok("adb.screenshot", started, tr("disimpan: {path}", path=path))
    except AdbError as exc:
        return _fail("adb.screenshot", started, str(exc))
    except subprocess.TimeoutExpired:
        return _fail("adb.screenshot", started, tr("Timeout"))
    except OSError as exc:
        return _fail("adb.screenshot", started, tr("Gagal menyimpan: {sebab}", sebab=exc))


def _h_reboot(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    mode = str(p.get("mode") or "normal")
    args = ["reboot"] if mode == "normal" else ["reboot", mode]
    return _run_guarded(adb, "adb.reboot", args, f"reboot ({mode})")


def _h_wifi(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    state = "enable" if p.get("enabled", True) else "disable"
    return _run_guarded(adb, "adb.wifi", ["shell", "svc", "wifi", state], f"wifi {state}")


def _h_airplane(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    state = "enable" if p.get("enabled", True) else "disable"
    return _run_guarded(
        adb, "adb.airplane",
        ["shell", "cmd", "connectivity", "airplane-mode", state],
        f"airplane mode {state}",
    )


def _h_brightness(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    level = max(0, min(255, int(p.get("level", 128))))
    return _run_guarded(
        adb, "adb.brightness",
        ["shell", "settings", "put", "system", "screen_brightness", str(level)],
        f"brightness {level}",
    )


def _h_rotate(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    rot = max(0, min(3, int(p.get("rotation", 0))))
    started = time.time()
    # Matikan auto-rotate dulu, kalau tidak user_rotation diabaikan.
    try:
        adb.run(["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
    except (AdbError, subprocess.TimeoutExpired, OSError):
        pass
    result = _run_guarded(
        adb, "adb.rotate",
        ["shell", "settings", "put", "system", "user_rotation", str(rot)],
        f"rotasi {rot * 90} derajat",
    )
    result.duration_ms = int((time.time() - started) * 1000)
    return result


def _h_volume(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    direction = str(p.get("direction") or "up")
    key = "KEYCODE_VOLUME_UP" if direction == "up" else "KEYCODE_VOLUME_DOWN"
    steps = max(1, min(15, int(p.get("steps", 1))))
    started = time.time()
    for _ in range(steps):
        result = _run_guarded(adb, "adb.volume", ["shell", "input", "keyevent", key], "")
        if not result.ok:
            return result
    return _ok("adb.volume", started, f"volume {direction} x{steps}")


def _h_shell(adb: AdbExecutor, p: dict[str, Any]) -> ActionResult:
    raw = str(p.get("command") or "").strip()
    if not raw:
        return ActionResult("adb.shell", False, tr("Perintah kosong"))
    try:
        # shlex.split -> argumen list, tetap tanpa shell=True di host.
        args = shlex.split(raw)
    except ValueError as exc:
        return ActionResult("adb.shell", False, tr("Perintah tidak valid: {sebab}", sebab=exc))
    return _run_guarded(adb, "adb.shell", ["shell", *args], tr("shell: {perintah}", perintah=raw[:60]))


# --------------------------------------------------------------- registrasi

def register_adb_actions() -> None:
    register(
        ActionSpec("adb.tap", "Tap layar", "adb", [
            ParamSpec("x", "X", "int", 500),
            ParamSpec("y", "Y", "int", 1000),
        ]),
        _h_tap,
    )
    register(
        ActionSpec("adb.swipe", "Swipe", "adb", [
            ParamSpec("x1", "Dari X", "int", 500),
            ParamSpec("y1", "Dari Y", "int", 1500),
            ParamSpec("x2", "Ke X", "int", 500),
            ParamSpec("y2", "Ke Y", "int", 500),
            ParamSpec("duration_ms", "Durasi (ms)", "int", 300),
        ]),
        _h_swipe,
    )
    register(
        ActionSpec("adb.text", "Ketik teks", "adb", [
            ParamSpec("text", "Teks", "str", "", help="Spasi otomatis di-escape"),
        ]),
        _h_text,
    )
    register(
        ActionSpec("adb.keyevent", "Tombol (keyevent)", "adb", [
            ParamSpec("keycode", "Keycode", "choice", "KEYCODE_HOME", choices=KEYCODES),
        ]),
        _h_keyevent,
    )
    register(
        ActionSpec("adb.open_app", "Buka aplikasi", "adb", [
            ParamSpec("package", "Package", "str", "", help="mis. com.zhiliaoapp.musically"),
        ]),
        _h_open_app,
    )
    register(
        ActionSpec("adb.close_app", "Tutup aplikasi", "adb", [
            ParamSpec("package", "Package", "str", ""),
        ]),
        _h_close_app,
    )
    register(
        ActionSpec("adb.open_url", "Buka URL", "adb", [
            ParamSpec("url", "URL", "str", "https://"),
        ]),
        _h_open_url,
    )
    register(
        ActionSpec("adb.screenshot", "Screenshot", "adb", [
            ParamSpec("save_dir", "Folder simpan", "str", "", help="Kosong = ./screenshots"),
        ]),
        _h_screenshot,
    )
    register(
        ActionSpec("adb.reboot", "Reboot device", "adb", [
            ParamSpec("mode", "Mode", "choice", "normal", choices=["normal", "recovery", "bootloader"]),
        ], dangerous=True, help="Memutus koneksi device beberapa menit"),
        _h_reboot,
    )
    register(
        ActionSpec("adb.wifi", "WiFi on/off", "adb", [
            ParamSpec("enabled", "Nyalakan", "bool", True),
        ], dangerous=True, help="Mematikan wifi bisa memutus adb wireless"),
        _h_wifi,
    )
    register(
        ActionSpec("adb.airplane", "Mode pesawat", "adb", [
            ParamSpec("enabled", "Nyalakan", "bool", True),
        ], dangerous=True),
        _h_airplane,
    )
    register(
        ActionSpec("adb.brightness", "Brightness", "adb", [
            ParamSpec("level", "Level (0-255)", "int", 128, minimum=0, maximum=255),
        ]),
        _h_brightness,
    )
    register(
        ActionSpec("adb.rotate", "Rotasi layar", "adb", [
            ParamSpec("rotation", "Rotasi", "choice", "0", choices=["0", "1", "2", "3"],
                      help="0=portrait, 1=landscape, 2=portrait terbalik, 3=landscape terbalik"),
        ]),
        _h_rotate,
    )
    register(
        ActionSpec("adb.volume", "Volume", "adb", [
            ParamSpec("direction", "Arah", "choice", "up", choices=["up", "down"]),
            ParamSpec("steps", "Jumlah step", "int", 1, minimum=1, maximum=15),
        ]),
        _h_volume,
    )
    register(
        ActionSpec("adb.shell", "Custom shell command", "adb", [
            ParamSpec("command", "Perintah", "str", "", help="Tanpa prefix 'adb shell'"),
        ], dangerous=True, help="Perintah bebas - pastikan benar sebelum dipakai live"),
        _h_shell,
    )
