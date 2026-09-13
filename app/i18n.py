"""Dukungan banyak bahasa berbasis berkas JSON.

Kenapa JSON, bukan format .ts/.qm bawaan Qt: berkas Qt berbentuk biner
dan butuh perkakas khusus (lupdate/lrelease) untuk dibuat. Dengan JSON,
siapa pun bisa menyalin satu berkas, menerjemahkan isinya di editor teks
biasa, dan mengirimkannya.

Kunci terjemahan adalah teks bahasa Indonesia itu sendiri - sama seperti
cara kerja gettext. Keuntungannya: kalau sebuah teks belum diterjemahkan,
yang tampil adalah bahasa Indonesia yang tetap bisa dibaca, bukan kode
seperti "tab.connection.title".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / "locales"

# Bahasa sumber: teks di dalam kode ditulis dalam bahasa ini.
SOURCE_LANG = "id"

# Bahasa yang disertakan. Kontributor cukup menambah berkas JSON baru di
# folder locales/ dan menambahkan barisnya di sini.
LANGUAGES: dict[str, str] = {
    "id": "Bahasa Indonesia",
    "en": "English",
    "zh": "中文",
}

_current = SOURCE_LANG
_table: dict[str, str] = {}


def available_languages() -> dict[str, str]:
    """Kode bahasa -> nama yang ditampilkan, hanya yang berkasnya ada."""
    found = {SOURCE_LANG: LANGUAGES[SOURCE_LANG]}
    for code, name in LANGUAGES.items():
        if code == SOURCE_LANG or (LOCALES_DIR / f"{code}.json").is_file():
            found[code] = name
    return found


def current_language() -> str:
    return _current


def load_language(code: str) -> bool:
    """Muat satu bahasa. Kembalikan False kalau gagal (tetap pakai sumber)."""
    global _current, _table

    code = (code or SOURCE_LANG).strip().lower()
    if code == SOURCE_LANG:
        _current, _table = SOURCE_LANG, {}
        return True

    path = LOCALES_DIR / f"{code}.json"
    if not path.is_file():
        log.warning("Berkas bahasa tidak ditemukan: %s", path)
        _current, _table = SOURCE_LANG, {}
        return False

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log.warning("Berkas bahasa %s rusak: %s", path.name, exc)
        _current, _table = SOURCE_LANG, {}
        return False

    # Entri bisa berupa string biasa, atau objek {"text": ..., "note": ...}
    # supaya penerjemah bisa menyimpan catatan.
    table: dict[str, str] = {}
    for key, value in (data.get("strings") or data).items():
        if key.startswith("_"):                     # metadata berkas
            continue
        if isinstance(value, str):
            table[key] = value
        elif isinstance(value, dict) and isinstance(value.get("text"), str):
            table[key] = value["text"]

    _current, _table = code, table
    log.info("Bahasa %s dimuat (%d teks)", code, len(table))
    return True


def tr(text: str, **kwargs: Any) -> str:
    """Terjemahkan sebuah teks.

    Teks yang belum diterjemahkan dikembalikan apa adanya, jadi antarmuka
    tidak pernah menampilkan kunci mentah.

    Nilai pengganti memakai format {nama}:
        tr("Terhubung ke @{nama}", nama="budi")
    """
    result = _table.get(text) or text
    if kwargs:
        try:
            return result.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # Terjemahan dengan placeholder salah tidak boleh membuat
            # aplikasi gagal - pakai teks sumber.
            try:
                return text.format(**kwargs)
            except Exception:                       # noqa: BLE001
                return text
    return result


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


def missing_keys(code: str, keys: list[str]) -> list[str]:
    """Teks yang belum ada terjemahannya - dipakai berkas uji & perkakas."""
    path = LOCALES_DIR / f"{code}.json"
    if not path.is_file():
        return list(keys)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return list(keys)
    table = data.get("strings") or data
    return [k for k in keys if not str(table.get(k) or "").strip()]
