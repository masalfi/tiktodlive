"""Aksi khusus game (Mobile Legends, dll).

Kenapa tidak memakai koordinat tetap dari internet:
Mobile Legends mengizinkan pemain memindahkan tombol lewat pengaturan HUD,
dan posisinya juga berubah mengikuti resolusi layar. Koordinat yang
"benar" di satu HP bisa meleset jauh di HP lain.

Jadi posisi tombol disimpan sebagai PERSENTASE layar (0.0-1.0) di dalam
profil, dan pengguna mengkalibrasinya sendiri lewat tab Game: ambil
screenshot saat game terbuka, lalu klik tombolnya. Nilai bawaan hanya
titik awal, bukan kebenaran mutlak.
"""

from __future__ import annotations

import logging
import math
import re
import subprocess
import time
from typing import Any

from app.actions.base import ActionSpec, ParamSpec, register
from app.models import ActionResult

log = logging.getLogger(__name__)

# Arah untuk joystick & skill terarah, dalam derajat layar
# (0 = kanan, 90 = bawah, 180 = kiri, 270 = atas)
DIRECTIONS = {
    "kanan": 0, "kanan-bawah": 45, "bawah": 90, "kiri-bawah": 135,
    "kiri": 180, "kiri-atas": 225, "atas": 270, "kanan-atas": 315,
}


def _ok(t: str, started: float, msg: str) -> ActionResult:
    return ActionResult(t, True, msg, int((time.time() - started) * 1000))


def _fail(t: str, started: float, msg: str) -> ActionResult:
    return ActionResult(t, False, msg, int((time.time() - started) * 1000))


def physical_size(adb) -> tuple[int, int] | None:
    """Ukuran fisik layar - TIDAK berubah walau HP diputar."""
    try:
        proc = adb.run(["shell", "wm", "size"], timeout=10)
    except Exception:                               # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None

    size = None
    for line in (proc.stdout or "").splitlines():
        if ":" not in line:
            continue
        value = line.split(":", 1)[1].strip()
        if "x" in value:
            try:
                w, h = value.lower().split("x")
                size = (int(w), int(h))
            except ValueError:
                continue
        # "Override size" muncul setelah "Physical size" dan menimpanya.
    return size


def _as_quarter_turns(value: int) -> int:
    """Samakan penulisan rotasi jadi 0-3 (perempatan putaran).

    Android tidak konsisten: `mCurrentRotation` memakai DERAJAT
    (ROTATION_0/90/180/270) sedangkan field lain memakai perempatan
    putaran (0/1/2/3). Menyamakan keduanya dengan `% 4` keliru -
    90 % 4 = 2, yang berarti "tegak terbalik", bukan "mendatar".
    """
    if value >= 45:                 # jelas derajat
        return (value // 90) % 4
    return value % 4


def current_rotation(adb) -> int | None:
    """Rotasi layar saat ini sebagai perempatan putaran: 0-3.

    0 = tegak, 1 = mendatar, 2 = tegak terbalik, 3 = mendatar terbalik.

    `wm size` TIDAK berguna untuk ini - ia selalu melaporkan ukuran fisik
    walau HP sedang mendatar. Rotasi nyata hanya bisa dibaca dari dumpsys.
    """
    try:
        proc = adb.run(["shell", "dumpsys", "window"], timeout=12)
    except Exception:                               # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None

    text = proc.stdout or ""
    match = re.search(r"mCurrentRotation=ROTATION_(\d+)", text)
    if match:
        return _as_quarter_turns(int(match.group(1)))

    # `mRotation` sering muncul beberapa kali dengan nilai berbeda (satu
    # per display/window), jadi hanya dipakai kalau semuanya sepakat.
    values = {int(v) for v in re.findall(r"\bmRotation=(\d+)", text)}
    if len(values) == 1:
        return _as_quarter_turns(values.pop())
    return None


def screen_size(adb) -> tuple[int, int] | None:
    """Ukuran layar SESUAI rotasi saat ini.

    Inilah ruang koordinat yang dipakai `input tap`, jadi ini yang harus
    dipakai untuk mengubah persentase jadi piksel.
    """
    size = physical_size(adb)
    if size is None:
        return None
    rotation = current_rotation(adb)
    if rotation in (1, 3):
        return size[1], size[0]                     # mendatar: tukar sisi
    return size


def is_landscape(adb) -> bool:
    """Apakah layar sedang mendatar (game MOBA biasanya begitu)?"""
    return current_rotation(adb) in (1, 3)


def screen_awake(adb) -> bool | None:
    """False kalau layar mati/HP terkunci - tap tidak akan terlihat efeknya."""
    try:
        proc = adb.run(["shell", "dumpsys", "power"], timeout=10)
    except Exception:                               # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"mWakefulness=(\w+)", proc.stdout or "")
    if not match:
        return None
    return match.group(1).lower() == "awake"


def resolve_point(adb, profile: dict, button: str) -> tuple[int, int] | str:
    """Ubah posisi persen sebuah tombol jadi piksel.

    Kembalikan (x, y) atau pesan error berupa string.
    """
    buttons = profile.get("buttons") or {}
    entry = buttons.get(button)
    if not entry:
        available = ", ".join(sorted(buttons)) or "(profil kosong)"
        return f"Tombol '{button}' belum dikalibrasi. Yang tersedia: {available}"

    try:
        px, py = float(entry["x"]), float(entry["y"])
    except (KeyError, TypeError, ValueError):
        return f"Posisi tombol '{button}' rusak di profil"

    size = screen_size(adb)
    if size is None:
        return "Tidak bisa membaca ukuran layar device (adb shell wm size gagal)"

    width, height = size
    now_landscape = width > height
    calibrated_landscape = bool(profile.get("landscape", True))

    # Orientasi harus SAMA dengan saat kalibrasi. Kalau berbeda, menukar
    # sisi begitu saja menghasilkan titik yang salah - lebih baik bilang
    # terus terang daripada menekan tempat acak.
    if calibrated_landscape != now_landscape:
        butuh = "mendatar (landscape)" if calibrated_landscape else "tegak (portrait)"
        sekarang = "mendatar" if now_landscape else "tegak"
        return (
            f"Profil dikalibrasi saat layar {butuh}, tapi HP sekarang {sekarang}. "
            f"Putar HP ke posisi yang sama, atau kalibrasi ulang di tab Game."
        )

    return int(px * width), int(py * height)


def _tap(adb, x: int, y: int, timeout: int | None = None):
    return adb.run(["shell", "input", "tap", str(x), str(y)], timeout=timeout)


def _hold(adb, x: int, y: int, ms: int, timeout: int | None = None):
    # Swipe dengan titik awal = titik akhir menghasilkan tekan-tahan.
    return adb.run(
        ["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(ms)],
        timeout=timeout,
    )


def _drag(adb, x1: int, y1: int, x2: int, y2: int, ms: int, timeout: int | None = None):
    return adb.run(
        ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms)],
        timeout=timeout,
    )


def _guard(adb, action_type: str, started: float, proc) -> ActionResult | None:
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return _fail(action_type, started, err)
    return None


def _profile_of(adb_host) -> dict:
    """Profil aktif diselipkan ke AdbExecutor oleh MainWindow."""
    return getattr(adb_host, "game_profile", None) or {}


# ---------------------------------------------------------------- handlers

def _h_tap_button(adb, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    button = str(p.get("button") or "").strip()
    point = resolve_point(adb, _profile_of(adb), button)
    if isinstance(point, str):
        return _fail("game.tap_button", started, point)

    x, y = point
    repeat = max(1, min(20, int(p.get("repeat", 1))))
    gap = max(0, int(p.get("gap_ms", 120)))
    try:
        for i in range(repeat):
            proc = _tap(adb, x, y)
            problem = _guard(adb, "game.tap_button", started, proc)
            if problem:
                return problem
            if i < repeat - 1 and gap:
                time.sleep(gap / 1000)
    except Exception as exc:                        # noqa: BLE001
        return _fail("game.tap_button", started, f"Gagal: {exc}")

    suffix = f" x{repeat}" if repeat > 1 else ""
    return _ok("game.tap_button", started, f"tekan '{button}'{suffix} di ({x}, {y})")


def _h_hold_button(adb, p: dict[str, Any]) -> ActionResult:
    """Tekan-tahan: untuk skill yang perlu di-charge atau recall."""
    started = time.time()
    button = str(p.get("button") or "").strip()
    point = resolve_point(adb, _profile_of(adb), button)
    if isinstance(point, str):
        return _fail("game.hold_button", started, point)

    x, y = point
    ms = max(50, min(30000, int(p.get("duration_ms", 1500))))
    try:
        proc = _hold(adb, x, y, ms, timeout=max(15, ms // 1000 + 10))
    except Exception as exc:                        # noqa: BLE001
        return _fail("game.hold_button", started, f"Gagal: {exc}")
    problem = _guard(adb, "game.hold_button", started, proc)
    if problem:
        return problem
    return _ok("game.hold_button", started, f"tahan '{button}' {ms}ms di ({x}, {y})")


def _h_aim_skill(adb, p: dict[str, Any]) -> ActionResult:
    """Skill terarah: tekan tombol lalu geser ke satu arah sebelum lepas."""
    started = time.time()
    button = str(p.get("button") or "").strip()
    point = resolve_point(adb, _profile_of(adb), button)
    if isinstance(point, str):
        return _fail("game.aim_skill", started, point)

    x, y = point
    direction = str(p.get("direction") or "kanan")
    degrees = DIRECTIONS.get(direction)
    if degrees is None:
        return _fail("game.aim_skill", started,
                     f"Arah '{direction}' tidak dikenal. Pilih: {', '.join(DIRECTIONS)}")

    size = screen_size(adb)
    if size is None:
        return _fail("game.aim_skill", started, "Tidak bisa membaca ukuran layar")
    # Jarak geser relatif terhadap sisi terpendek, supaya konsisten
    # di resolusi berapa pun.
    reach = max(0.02, min(0.5, float(p.get("distance", 0.12))))
    radius = int(min(size) * reach)

    radians = math.radians(degrees)
    x2 = x + int(radius * math.cos(radians))
    y2 = y + int(radius * math.sin(radians))
    # Jangan sampai keluar layar.
    x2 = max(1, min(size[0] - 1, x2))
    y2 = max(1, min(size[1] - 1, y2))

    ms = max(80, min(5000, int(p.get("duration_ms", 300))))
    try:
        proc = _drag(adb, x, y, x2, y2, ms)
    except Exception as exc:                        # noqa: BLE001
        return _fail("game.aim_skill", started, f"Gagal: {exc}")
    problem = _guard(adb, "game.aim_skill", started, proc)
    if problem:
        return problem
    return _ok("game.aim_skill", started, f"'{button}' diarahkan ke {direction}")


def _h_move(adb, p: dict[str, Any]) -> ActionResult:
    """Gerakkan hero dengan menggeser joystick ke satu arah."""
    started = time.time()
    profile = _profile_of(adb)
    point = resolve_point(adb, profile, "joystick")
    if isinstance(point, str):
        return _fail("game.move", started, point)

    x, y = point
    direction = str(p.get("direction") or "kanan")
    degrees = DIRECTIONS.get(direction)
    if degrees is None:
        return _fail("game.move", started,
                     f"Arah '{direction}' tidak dikenal. Pilih: {', '.join(DIRECTIONS)}")

    size = screen_size(adb)
    if size is None:
        return _fail("game.move", started, "Tidak bisa membaca ukuran layar")

    reach = max(0.02, min(0.4, float(p.get("distance", 0.09))))
    radius = int(min(size) * reach)
    radians = math.radians(degrees)
    x2 = max(1, min(size[0] - 1, x + int(radius * math.cos(radians))))
    y2 = max(1, min(size[1] - 1, y + int(radius * math.sin(radians))))

    ms = max(100, min(15000, int(p.get("duration_ms", 1200))))
    try:
        proc = _drag(adb, x, y, x2, y2, ms, timeout=max(15, ms // 1000 + 10))
    except Exception as exc:                        # noqa: BLE001
        return _fail("game.move", started, f"Gagal: {exc}")
    problem = _guard(adb, "game.move", started, proc)
    if problem:
        return problem
    return _ok("game.move", started, f"jalan ke {direction} selama {ms}ms")


def _h_combo(adb, p: dict[str, Any]) -> ActionResult:
    """Beberapa tombol berurutan, mis. 'skill1,skill2,ultimate'."""
    started = time.time()
    raw = str(p.get("buttons") or "").strip()
    if not raw:
        return _fail("game.combo", started, "Daftar tombol kosong")

    names = [n.strip() for n in raw.split(",") if n.strip()]
    if not names:
        return _fail("game.combo", started, "Daftar tombol kosong")

    profile = _profile_of(adb)
    gap = max(0, min(5000, int(p.get("gap_ms", 250))))
    done = []
    for name in names:
        point = resolve_point(adb, profile, name)
        if isinstance(point, str):
            return _fail("game.combo", started, f"{point} (berhenti setelah: {', '.join(done) or '-'})")
        x, y = point
        try:
            proc = _tap(adb, x, y)
        except Exception as exc:                    # noqa: BLE001
            return _fail("game.combo", started, f"Gagal di '{name}': {exc}")
        problem = _guard(adb, "game.combo", started, proc)
        if problem:
            return problem
        done.append(name)
        if gap:
            time.sleep(gap / 1000)

    return _ok("game.combo", started, f"combo: {' -> '.join(done)}")


# --------------------------------------------------------------- registrasi

def register_game_actions() -> None:
    button_help = "nama tombol dari tab Game (mis. ultimate, recall, skill1)"

    register(
        ActionSpec("game.tap_button", "Tekan tombol game", "game", [
            ParamSpec("button", "Tombol", "str", "ultimate", help=button_help),
            ParamSpec("repeat", "Ulangi", "int", 1, minimum=1, maximum=20),
            ParamSpec("gap_ms", "Jeda antar tekan (ms)", "int", 120),
        ], help="Posisi tombol diambil dari profil di tab Game"),
        _h_tap_button,
    )
    register(
        ActionSpec("game.hold_button", "Tekan & tahan tombol game", "game", [
            ParamSpec("button", "Tombol", "str", "recall", help=button_help),
            ParamSpec("duration_ms", "Lama tahan (ms)", "int", 1500),
        ], help="Untuk recall atau skill yang perlu di-charge"),
        _h_hold_button,
    )
    register(
        ActionSpec("game.aim_skill", "Skill terarah", "game", [
            ParamSpec("button", "Tombol", "str", "skill1", help=button_help),
            ParamSpec("direction", "Arah", "choice", "kanan", choices=list(DIRECTIONS)),
            ParamSpec("distance", "Jarak geser (0-0.5)", "float", 0.12),
            ParamSpec("duration_ms", "Durasi (ms)", "int", 300),
        ], help="Tekan tombol lalu geser untuk membidik"),
        _h_aim_skill,
    )
    register(
        ActionSpec("game.move", "Gerakkan hero (joystick)", "game", [
            ParamSpec("direction", "Arah", "choice", "kanan", choices=list(DIRECTIONS)),
            ParamSpec("duration_ms", "Lama jalan (ms)", "int", 1200),
            ParamSpec("distance", "Jarak joystick (0-0.4)", "float", 0.09),
        ], help="Butuh tombol 'joystick' terkalibrasi"),
        _h_move,
    )
    register(
        ActionSpec("game.combo", "Combo beberapa tombol", "game", [
            ParamSpec("buttons", "Tombol (pisah koma)", "str", "skill1,skill2,ultimate"),
            ParamSpec("gap_ms", "Jeda (ms)", "int", 250),
        ], help="Dijalankan berurutan, mis. skill1,skill2,ultimate"),
        _h_combo,
    )
