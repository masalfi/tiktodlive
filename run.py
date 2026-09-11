#!/usr/bin/env python3
"""TikTok Live Controller - jalankan aplikasi.

Cukup jalankan file ini:

    python run.py          (atau python3 run.py)

Kalau ada paket yang belum terpasang, file ini memasangnya lebih dulu ke
lingkungan virtual (.venv), lalu membuka aplikasi. Tidak perlu mengaktifkan
venv secara manual.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MIN_PYTHON = (3, 10)

# Paket -> nama modul untuk pengecekan impor
REQUIRED = {
    "PySide6": "PySide6",
    "TikTokLive": "TikTokLive",
    "aiohttp": "aiohttp",
    "PyYAML": "yaml",
    "pynput": "pynput",
    "httpx": "httpx",
}


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _in_venv() -> bool:
    try:
        return _venv_python().resolve() == Path(sys.executable).resolve()
    except OSError:
        return False


def _missing() -> list[str]:
    import importlib.util

    return [pkg for pkg, mod in REQUIRED.items() if importlib.util.find_spec(mod) is None]


def _missing_for(python: Path) -> list[str]:
    """Cek paket yang kurang pada interpreter lain (venv)."""
    check = (
        "import importlib.util,sys;"
        "mods=" + repr(list(REQUIRED.values())) + ";"
        "print(','.join(m for m in mods if importlib.util.find_spec(m) is None))"
    )
    try:
        proc = subprocess.run([str(python), "-c", check], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return list(REQUIRED)
    if proc.returncode != 0:
        return list(REQUIRED)
    out = (proc.stdout or "").strip()
    return out.split(",") if out else []


def _exec_venv() -> None:
    """Pindah proses ke python milik .venv."""
    python = _venv_python()
    os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])


def _run(args: list[str], desc: str) -> None:
    print(f"  {desc}...", flush=True)
    result = subprocess.run(args)
    if result.returncode != 0:
        sys.exit(f"\nGagal: {desc}. Coba jalankan manual:\n  {' '.join(args)}")


def _bootstrap() -> None:
    """Buat venv + pasang dependencies, lalu jalankan ulang di dalamnya."""
    python = _venv_python()

    if not python.exists():
        print("Menyiapkan lingkungan (sekali saja)...")
        _run([sys.executable, "-m", "venv", str(VENV)], "membuat .venv")

    print("Memasang paket yang dibutuhkan...")
    _run([str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], "memperbarui pip")
    _run(
        [str(python), "-m", "pip", "install", "--quiet", "-r", str(ROOT / "requirements.txt")],
        "memasang dependencies",
    )

    print("Menjalankan aplikasi...\n")
    _exec_venv()


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        sys.exit(
            f"Butuh Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} atau lebih baru "
            f"(terdeteksi {sys.version_info.major}.{sys.version_info.minor}).\n"
            "Unduh di https://www.python.org/downloads/"
        )

    if not (ROOT / "requirements.txt").exists():
        sys.exit(f"requirements.txt tidak ditemukan di {ROOT}")

    # Selalu jalankan di dalam .venv milik project. Tanpa ini, paket bisa
    # terpasang ke Python sistem dan bentrok dengan project lain.
    if not _in_venv():
        if _venv_python().exists() and not _missing_for(_venv_python()):
            # venv sudah siap - langsung pindah ke sana.
            _exec_venv()
        _bootstrap()
        return 0

    # Sudah di dalam venv: pasang yang kurang, tanpa exec ulang supaya
    # tidak menjadi loop tak berujung.
    if _missing():
        _run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(ROOT / "requirements.txt")],
            "memasang dependencies",
        )
        still = _missing()
        if still:
            sys.exit("Paket berikut gagal dipasang: " + ", ".join(still))

    sys.path.insert(0, str(ROOT))
    from app.main import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
