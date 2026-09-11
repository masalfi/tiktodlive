"""Load/save konfigurasi YAML + auto-discovery path adb & scrcpy."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from app.models import Rule

log = logging.getLogger(__name__)


class RulesLoadError(RuntimeError):
    """rules.yaml ada tapi tidak bisa dibaca."""

# Root proyek = parent dari folder app/
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
RULES_PATH = CONFIG_DIR / "rules.yaml"
GAMES_PATH = CONFIG_DIR / "game_profiles.yaml"
SFX_DIR = ROOT / "assets" / "sfx"

DEFAULT_SETTINGS: dict[str, Any] = {
    "tiktok": {
        "username": "",
        "sign_api_key": "",        # EulerStream API key
        "auto_reconnect": True,
        # auto = pakai EulerStream kalau ada API key, kalau tidak TikTokLive.
        # Bisa dipaksa: "tiktoklive" atau "eulerstream".
        "backend": "auto",
    },
    "adb": {
        "path": "",                # kosong = auto-detect
        "serial": "",              # kosong = device pertama
        "timeout_sec": 15,
    },
    "scrcpy": {
        "path": "",                # kosong = auto-detect (vendor/ lalu PATH)
        "wireless_port": 5555,
        "options": {},             # diisi dari tab scrcpy
    },
    "overlay": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8777,
        "test": {},                # pengaturan terakhir di tab Overlay
    },
    "safety": {
        "max_queue": 50,           # antrian penuh -> event baru di-drop
        "reboot_max_per_hour": 2,  # hard cap, tak bisa dilewati rule
        "confirm_timeout_sec": 10, # dialog konfirmasi auto-cancel
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override ke base secara rekursif (base tidak dimutasi)."""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings() -> dict[str, Any]:
    """Baca settings.yaml, isi field yang hilang dengan default."""
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)
    with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return _deep_merge(DEFAULT_SETTINGS, data)


def save_settings(settings: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(settings, fh, sort_keys=False, allow_unicode=True)


def load_rules() -> list[Rule]:
    """Baca rules.yaml. File rusak dilaporkan, bukan didiamkan.

    Mengembalikan [] diam-diam saat file rusak berbahaya: penyimpanan
    berikutnya akan menimpa seluruh rule dengan daftar kosong.
    """
    if not RULES_PATH.exists():
        return []
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RulesLoadError(f"config/rules.yaml tidak bisa dibaca: {exc}") from exc

    rules = []
    for item in data.get("rules") or []:
        try:
            rules.append(Rule.from_dict(item))
        except Exception as exc:                    # noqa: BLE001
            log.warning("Rule dilewati karena rusak: %s", exc)
    return rules


def save_rules(rules: list[Rule]) -> None:
    """Simpan rules.yaml, dengan cadangan file sebelumnya.

    Cadangan penting karena penyimpanan menimpa seluruh file - satu
    kesalahan bisa menghapus semua rule yang sudah disusun.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if RULES_PATH.exists():
        try:
            shutil.copy2(RULES_PATH, RULES_PATH.with_suffix(".yaml.bak"))
        except OSError as exc:
            log.warning("Gagal membuat cadangan rules: %s", exc)

    payload = {"rules": [r.to_dict() for r in rules]}
    # Tulis ke file sementara lalu ganti, supaya file tidak rusak
    # kalau aplikasi mati di tengah penulisan.
    tmp = RULES_PATH.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
    tmp.replace(RULES_PATH)


DEFAULT_GAMES: dict[str, Any] = {"active": "", "profiles": {}}


def load_games() -> dict[str, Any]:
    """Baca profil tombol game. File rusak tidak boleh membuat app gagal."""
    if not GAMES_PATH.exists():
        return dict(DEFAULT_GAMES)
    try:
        with open(GAMES_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("game_profiles.yaml tidak bisa dibaca: %s", exc)
        return dict(DEFAULT_GAMES)

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        return dict(DEFAULT_GAMES)
    return {"active": str(data.get("active") or ""), "profiles": profiles}


def save_games(data: dict[str, Any]) -> None:
    """Simpan profil, dengan cadangan seperti rules."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if GAMES_PATH.exists():
        try:
            shutil.copy2(GAMES_PATH, GAMES_PATH.with_suffix(".yaml.bak"))
        except OSError as exc:
            log.warning("Gagal mencadangkan profil game: %s", exc)

    tmp = GAMES_PATH.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    tmp.replace(GAMES_PATH)


def active_profile(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Profil yang sedang dipakai, atau {} kalau tidak ada."""
    data = data or load_games()
    return (data.get("profiles") or {}).get(data.get("active"), {}) or {}


def _candidate_adb_paths() -> list[Path]:
    """Lokasi umum adb per platform, dicek setelah PATH."""
    home = Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        return [
            Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            home / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            Path("C:/Android/platform-tools/adb.exe"),
            Path("C:/platform-tools/adb.exe"),
        ]
    if sys.platform == "darwin":
        return [
            home / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
            Path("/opt/homebrew/bin/adb"),
            Path("/usr/local/bin/adb"),
        ]
    return [
        home / "Android" / "Sdk" / "platform-tools" / "adb",
        Path("/usr/bin/adb"),
        Path("/usr/local/bin/adb"),
    ]


def vendor_adb() -> Path | None:
    """adb yang ikut dalam paket scrcpy di folder vendor/.

    scrcpy selalu membawa adb-nya sendiri, jadi begitu scrcpy diunduh,
    kamu tidak perlu memasang Android platform-tools terpisah - ini
    sangat membantu di Windows.
    """
    vendor = ROOT / "vendor"
    if not vendor.exists():
        return None
    name = "adb.exe" if sys.platform == "win32" else "adb"
    direct = vendor / name
    if direct.is_file():
        return direct
    for child in sorted(vendor.iterdir()):
        if child.is_dir():
            candidate = child / name
            if candidate.is_file():
                return candidate
    return None


def find_adb(configured: str = "") -> str | None:
    """Cari executable adb.

    Urutan: path manual -> adb bawaan scrcpy (vendor/) -> PATH -> SDK.
    Bawaan scrcpy didahulukan supaya versinya cocok dengan scrcpy yang
    dipakai, dan supaya aplikasi tetap jalan tanpa install adb terpisah.
    """
    if configured:
        p = Path(configured).expanduser()
        if p.exists():
            return str(p)

    bundled = vendor_adb()
    if bundled is not None:
        return str(bundled)

    found = shutil.which("adb")
    if found:
        return found
    for candidate in _candidate_adb_paths():
        if candidate.exists():
            return str(candidate)
    return None


def find_scrcpy(configured: str = "") -> str | None:
    """scrcpy opsional - hanya dipakai aksi host.launch_scrcpy."""
    if configured:
        p = Path(configured).expanduser()
        if p.exists():
            return str(p)
    return shutil.which("scrcpy")
