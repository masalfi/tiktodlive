"""Jembatan pengaturan scrcpy: dari pilihan di UI jadi argumen CLI.

Tujuannya supaya kamu tidak perlu mengetik perintah scrcpy di terminal.
Setiap opsi di sini punya padanan langsung ke flag scrcpy.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from app.i18n import tr
log = logging.getLogger(__name__)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Pilihan yang ditampilkan di UI
MAX_SIZE_CHOICES = ["(asli)", "640", "800", "1024", "1280", "1600", "1920"]
FPS_CHOICES = ["(bawaan)", "15", "24", "30", "45", "60"]
BITRATE_CHOICES = ["(bawaan)", "2M", "4M", "8M", "16M", "24M"]
CODEC_CHOICES = ["(bawaan)", "h264", "h265", "av1"]
ORIENTATION_CHOICES = ["(bawaan)", "0", "90", "180", "270"]


@dataclass
class ScrcpyOptions:
    """Semua pengaturan scrcpy yang bisa diatur dari UI."""

    # tampilan
    max_size: str = "(asli)"
    max_fps: str = "(bawaan)"
    bitrate: str = "(bawaan)"
    codec: str = "(bawaan)"
    orientation: str = "(bawaan)"
    crop: str = ""                      # mis. 1224:1440:0:0

    # jendela
    window_title: str = "Live Controller"
    always_on_top: bool = False
    fullscreen: bool = False
    borderless: bool = False
    window_x: int = -1                  # -1 = biarkan scrcpy yang atur
    window_y: int = -1
    window_width: int = 0               # 0 = otomatis
    window_height: int = 0

    # perilaku device
    turn_screen_off: bool = False
    stay_awake: bool = True
    show_touches: bool = True
    power_off_on_close: bool = False

    # audio & kontrol
    no_audio: bool = True               # audio jarang dibutuhkan untuk kontrol
    no_control: bool = False            # True = hanya lihat, tidak bisa kontrol
    no_video: bool = False              # True = kontrol tanpa tampilan

    # rekaman
    record_file: str = ""

    # lain-lain
    disable_screensaver: bool = True
    extra_args: str = ""                # argumen tambahan bebas

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ScrcpyOptions":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def _is_set(value: str) -> bool:
    """Pilihan '(bawaan)'/'(asli)' berarti tidak dikirim ke scrcpy."""
    return bool(value) and not value.startswith("(")


def build_args(options: ScrcpyOptions, serial: str = "") -> list[str]:
    """Ubah opsi jadi daftar argumen scrcpy (tanpa nama programnya)."""
    args: list[str] = []

    if serial:
        args += ["--serial", serial]

    # ---- tampilan
    if _is_set(options.max_size):
        args.append(f"--max-size={options.max_size}")
    if _is_set(options.max_fps):
        args.append(f"--max-fps={options.max_fps}")
    if _is_set(options.bitrate):
        args.append(f"--video-bit-rate={options.bitrate}")
    if _is_set(options.codec):
        args.append(f"--video-codec={options.codec}")
    if _is_set(options.orientation):
        args.append(f"--capture-orientation={options.orientation}")
    if options.crop.strip():
        args.append(f"--crop={options.crop.strip()}")

    # ---- jendela
    if options.window_title.strip():
        args.append(f"--window-title={options.window_title.strip()}")
    if options.always_on_top:
        args.append("--always-on-top")
    if options.fullscreen:
        args.append("--fullscreen")
    if options.borderless:
        args.append("--window-borderless")
    if options.window_x >= 0:
        args.append(f"--window-x={options.window_x}")
    if options.window_y >= 0:
        args.append(f"--window-y={options.window_y}")
    if options.window_width > 0:
        args.append(f"--window-width={options.window_width}")
    if options.window_height > 0:
        args.append(f"--window-height={options.window_height}")

    # ---- perilaku device
    if options.turn_screen_off:
        args.append("--turn-screen-off")
    if options.stay_awake:
        args.append("--stay-awake")
    if options.show_touches:
        args.append("--show-touches")
    if options.power_off_on_close:
        args.append("--power-off-on-close")

    # ---- audio & kontrol
    if options.no_audio:
        args.append("--no-audio")
    if options.no_control:
        args.append("--no-control")
    if options.no_video:
        args.append("--no-video")

    # ---- rekaman
    if options.record_file.strip():
        args.append(f"--record={options.record_file.strip()}")

    if options.disable_screensaver:
        args.append("--disable-screensaver")

    # ---- argumen bebas dari user
    if options.extra_args.strip():
        try:
            args += shlex.split(options.extra_args, posix=(sys.platform != "win32"))
        except ValueError as exc:
            log.warning("Argumen tambahan tidak valid: %s", exc)

    return args


def preview_command(scrcpy_path: str, options: ScrcpyOptions, serial: str = "") -> str:
    """Perintah lengkap sebagai teks - ditampilkan di UI supaya transparan."""
    name = scrcpy_path or "scrcpy"
    parts = [name] + build_args(options, serial)
    return " ".join(shlex.quote(p) for p in parts)


# ------------------------------------------------------------- wireless

IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def device_ip(adb, serial: str = "") -> str:
    """Cari alamat IP WiFi device lewat adb. Kosong kalau gagal."""
    # Cara paling andal lebih dulu, lalu cadangan.
    attempts = [
        ["shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
        ["shell", "ip", "route"],
        ["shell", "getprop", "dhcp.wlan0.ipaddress"],
    ]
    for args in attempts:
        try:
            proc = adb.run(args, timeout=10)
        except Exception:                           # noqa: BLE001
            continue
        text = (proc.stdout or "") if proc.returncode == 0 else ""
        for match in IP_RE.finditer(text):
            ip = match.group(1)
            # Buang alamat yang jelas bukan IP device.
            if ip.startswith(("127.", "0.")) or ip.endswith(".0"):
                continue
            return ip
    return ""


def enable_wireless(adb, port: int = 5555, timeout: int = 25) -> tuple[bool, str]:
    """Aktifkan adb over TCP/IP lalu sambungkan.

    Device harus terhubung USB dulu. Kembalikan (berhasil, pesan/serial).
    """
    ip = device_ip(adb)
    if not ip:
        return False, (
            tr("Tidak bisa membaca IP device. Pastikan HP terhubung USB dan "
               "WiFi-nya menyala (HP dan PC harus satu jaringan).")
        )

    try:
        proc = adb.run(["tcpip", str(port)], timeout=timeout)
    except Exception as exc:                        # noqa: BLE001
        return False, tr("Gagal menjalankan 'adb tcpip': {sebab}", sebab=exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or tr("adb tcpip gagal")).strip()

    # Device butuh sesaat untuk membuka port setelah tcpip.
    import time

    time.sleep(2)

    target = f"{ip}:{port}"
    try:
        proc = adb.run(["connect", target], timeout=timeout)
    except Exception as exc:                        # noqa: BLE001
        return False, tr("Gagal menjalankan 'adb connect': {sebab}", sebab=exc)

    output = (proc.stdout or "") + (proc.stderr or "")
    if "connected to" in output.lower():
        return True, target
    return False, output.strip() or tr("Gagal menyambung ke {target}", target=target)


def disconnect_wireless(adb, serial: str) -> tuple[bool, str]:
    """Putuskan koneksi wireless."""
    if not serial or ":" not in serial:
        return False, tr("Serial wireless tidak valid")
    try:
        proc = adb.run(["disconnect", serial], timeout=15)
    except Exception as exc:                        # noqa: BLE001
        return False, str(exc)
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, output or "terputus"
