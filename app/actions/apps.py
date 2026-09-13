"""Aksi mengelola aplikasi di HP: buka, tutup, mulai ulang.

Kenapa terpisah dari adb.open_app/adb.close_app yang lama: aksi di sini
tahu game apa yang sedang kamu pakai (dari profil di tab Game), jadi kamu
tidak perlu mengetik nama package seperti "com.mobile.legends" sama
sekali. Untuk aplikasi lain, nama package bisa dipilih dari daftar yang
terpasang di HP, bukan diketik.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.actions.base import ActionSpec, ParamSpec, register
from app.i18n import tr
from app.models import ActionResult

log = logging.getLogger(__name__)

# Aplikasi sistem yang tidak boleh ditutup - menutupnya bisa membuat HP
# tidak bisa dipakai sampai di-reboot.
PROTECTED = {
    "android",
    "com.android.systemui",
    "com.android.settings",
    "com.google.android.gms",
    "com.android.phone",
    "com.android.launcher",
}


def _ok(t: str, started: float, msg: str) -> ActionResult:
    return ActionResult(t, True, msg, int((time.time() - started) * 1000))


def _fail(t: str, started: float, msg: str) -> ActionResult:
    return ActionResult(t, False, msg, int((time.time() - started) * 1000))


def list_packages(adb, only_user: bool = True) -> list[str]:
    """Daftar package yang terpasang. Kosong kalau gagal."""
    args = ["shell", "pm", "list", "packages"]
    if only_user:
        args.append("-3")                   # -3 = hanya aplikasi yang dipasang user
    try:
        proc = adb.run(args, timeout=20)
    except Exception:                       # noqa: BLE001
        return []
    if proc.returncode != 0:
        return []
    names = [
        line.strip().removeprefix("package:")
        for line in (proc.stdout or "").splitlines()
        if line.strip().startswith("package:")
    ]
    return sorted(set(names))


def foreground_package(adb) -> str:
    """Package aplikasi yang sedang tampil. Kosong kalau tidak terbaca."""
    import re

    try:
        proc = adb.run(["shell", "dumpsys", "window"], timeout=15)
    except Exception:                       # noqa: BLE001
        return ""
    if proc.returncode != 0:
        return ""
    match = re.search(r"mCurrentFocus=\S+\s+\S+\s+([A-Za-z0-9_.]+)/", proc.stdout or "")
    return match.group(1) if match else ""


def game_package(adb) -> str:
    """Package game dari profil yang sedang aktif di tab Game."""
    profile = getattr(adb, "game_profile", None) or {}
    return str(profile.get("package") or "").strip()


def _stop(adb, package: str, action_type: str, started: float) -> ActionResult:
    if not package:
        return _fail(action_type, started, tr("Nama package kosong"))
    if package in PROTECTED:
        return _fail(
            action_type, started,
            tr("'{package}' adalah aplikasi sistem - menutupnya bisa membuat HP "
               "tidak bisa dipakai. Dilewati demi keamanan.", package=package),
        )
    try:
        proc = adb.run(["shell", "am", "force-stop", package], timeout=20)
    except Exception as exc:                # noqa: BLE001
        return _fail(action_type, started, tr("Gagal: {sebab}", sebab=exc))
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return _fail(action_type, started, err)
    return _ok(action_type, started, tr("{package} ditutup", package=package))


def _launch(adb, package: str, action_type: str, started: float) -> ActionResult:
    if not package:
        return _fail(action_type, started, tr("Nama package kosong"))
    try:
        proc = adb.run(
            ["shell", "monkey", "-p", package, "-c",
             "android.intent.category.LAUNCHER", "1"], timeout=25)
    except Exception as exc:                # noqa: BLE001
        return _fail(action_type, started, tr("Gagal: {sebab}", sebab=exc))

    output = (proc.stdout or "") + (proc.stderr or "")
    # monkey mengembalikan 0 walau package tidak ada, jadi cek pesannya.
    if proc.returncode != 0 or "No activities found" in output or "Error" in output:
        return _fail(
            action_type, started,
            tr("Tidak bisa membuka '{package}' - pastikan aplikasinya terpasang", package=package),
        )
    return _ok(action_type, started, tr("{package} dibuka", package=package))


# ---------------------------------------------------------------- handlers

def _h_open(adb, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    return _launch(adb, str(p.get("package") or "").strip(), "app.open", started)


def _h_close(adb, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    return _stop(adb, str(p.get("package") or "").strip(), "app.close", started)


def _h_restart(adb, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    package = str(p.get("package") or "").strip()
    result = _stop(adb, package, "app.restart", started)
    if not result.ok:
        return result

    delay = max(0.0, min(10.0, float(p.get("delay_sec", 1.5))))
    time.sleep(delay)
    result = _launch(adb, package, "app.restart", started)
    if result.ok:
        return _ok("app.restart", started, f"{package} dimulai ulang")
    return result


def _h_close_game(adb, p: dict[str, Any]) -> ActionResult:
    """Tutup game dari profil aktif - tanpa perlu tahu nama package-nya."""
    started = time.time()
    package = game_package(adb)
    if not package:
        return _fail(
            "app.close_game", started,
            tr("Profil game aktif belum punya nama package. Isi di tab Game "
               "atau pakai aksi 'Tutup aplikasi' dan ketik package-nya."),
        )
    result = _stop(adb, package, "app.close_game", started)
    if result.ok:
        return _ok("app.close_game", started, tr("game ditutup ({package})", package=package))
    return result


def _h_restart_game(adb, p: dict[str, Any]) -> ActionResult:
    started = time.time()
    package = game_package(adb)
    if not package:
        return _fail("app.restart_game", started,
                     tr("Profil game aktif belum punya nama package."))
    result = _stop(adb, package, "app.restart_game", started)
    if not result.ok:
        return result

    delay = max(0.0, min(20.0, float(p.get("delay_sec", 2.0))))
    time.sleep(delay)
    result = _launch(adb, package, "app.restart_game", started)
    if result.ok:
        return _ok("app.restart_game", started, tr("game dimulai ulang ({package})", package=package))
    return result


def _h_close_foreground(adb, p: dict[str, Any]) -> ActionResult:
    """Tutup apa pun yang sedang tampil di layar."""
    started = time.time()
    package = foreground_package(adb)
    if not package:
        return _fail("app.close_foreground", started,
                     tr("Tidak bisa membaca aplikasi yang sedang tampil"))
    if package in PROTECTED:
        return _fail("app.close_foreground", started,
                     tr("Yang tampil adalah aplikasi sistem ({package}) - dilewati", package=package))
    result = _stop(adb, package, "app.close_foreground", started)
    if result.ok:
        return _ok("app.close_foreground", started,
                   tr("aplikasi di layar ditutup ({package})", package=package))
    return result


def _h_clear_background(adb, p: dict[str, Any]) -> ActionResult:
    """Tutup aplikasi latar untuk melegakan memori.

    Berguna sebelum membuka game supaya tidak patah-patah.
    """
    started = time.time()
    keep = {n.strip() for n in str(p.get("kecuali") or "").split(",") if n.strip()}
    current = foreground_package(adb)
    if current:
        keep.add(current)

    packages = list_packages(adb, only_user=True)
    if not packages:
        return _fail("app.clear_background", started,
                     tr("Tidak bisa membaca daftar aplikasi"))

    closed = 0
    for package in packages:
        if package in keep or package in PROTECTED:
            continue
        try:
            proc = adb.run(["shell", "am", "force-stop", package], timeout=15)
        except Exception:                   # noqa: BLE001
            continue
        if proc.returncode == 0:
            closed += 1

    kept = ", ".join(sorted(keep)) or "-"
    return _ok("app.clear_background", started,
               f"{closed} aplikasi latar ditutup (dibiarkan: {kept})")


# --------------------------------------------------------------- registrasi

def register_app_actions() -> None:
    register(
        ActionSpec("app.close_game", "Tutup game", "app", [], help=(
            "Menutup game dari profil yang aktif di tab Game - "
            "tidak perlu mengetik nama package"
        )),
        _h_close_game,
    )
    register(
        ActionSpec("app.restart_game", "Mulai ulang game", "app", [
            ParamSpec("delay_sec", "Jeda sebelum dibuka lagi (detik)", "float", 2.0),
        ], help="Menutup lalu membuka kembali game dari profil aktif"),
        _h_restart_game,
    )
    register(
        ActionSpec("app.close_foreground", "Tutup aplikasi yang sedang tampil", "app", [],
                   help="Menutup apa pun yang ada di layar HP saat itu"),
        _h_close_foreground,
    )
    register(
        ActionSpec("app.close", "Tutup aplikasi tertentu", "app", [
            ParamSpec("package", "Aplikasi", "package", "",
                      help="pilih dari daftar aplikasi di HP"),
        ]),
        _h_close,
    )
    register(
        ActionSpec("app.open", "Buka aplikasi", "app", [
            ParamSpec("package", "Aplikasi", "package", ""),
        ]),
        _h_open,
    )
    register(
        ActionSpec("app.restart", "Mulai ulang aplikasi", "app", [
            ParamSpec("package", "Aplikasi", "package", ""),
            ParamSpec("delay_sec", "Jeda (detik)", "float", 1.5),
        ]),
        _h_restart,
    )
    register(
        ActionSpec("app.clear_background", "Tutup semua aplikasi latar", "app", [
            ParamSpec("kecuali", "Jangan tutup (pisah koma)", "str", "",
                      help="nama package yang harus tetap jalan"),
        ], dangerous=True, help=(
            "Melegakan memori sebelum main. Aplikasi sistem dan yang sedang "
            "tampil selalu dilewati."
        )),
        _h_clear_background,
    )
