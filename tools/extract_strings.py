#!/usr/bin/env python3
"""Kumpulkan semua teks yang perlu diterjemahkan.

Jalankan:  python tools/extract_strings.py

Hasilnya memperbarui locales/*.json: teks baru ditambahkan dengan nilai
kosong, teks yang sudah diterjemahkan dipertahankan, dan teks yang sudah
tidak dipakai lagi dipindahkan ke bagian "_tidak_dipakai" (tidak dibuang,
supaya tidak hilang kalau cuma salah ketik sementara).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.i18n import LANGUAGES, LOCALES_DIR, SOURCE_LANG  # noqa: E402

# Pemanggilan yang isinya pasti tampil ke pengguna. Dipakai sebagai
# penyaring nama fungsi; isinya dibaca lewat AST, bukan regex, supaya
# string yang disambung implisit ("a" "b") ikut tergabung dengan benar -
# sama seperti yang dilihat tr() saat aplikasi berjalan.
UI_CALLS = {
    "tr", "QLabel", "QPushButton", "QCheckBox", "QGroupBox", "setText",
    "setToolTip", "setPlaceholderText", "setWindowTitle", "addTab", "setSuffix",
    "setSpecialValueText", "setInformativeText",
}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def from_source_files() -> set[str]:
    """Ambil literal string dari pemanggilan UI, lewat AST.

    tr() boleh menerima argumen dalam bentuk apa pun; yang bisa
    diterjemahkan hanyalah literal, jadi hanya itu yang dikumpulkan.
    AST juga sudah menggabungkan string bersambung dan mengurai escape,
    jadi kuncinya persis seperti yang dilihat tr() saat aplikasi jalan.
    """
    found: set[str] = set()
    for path in sorted((ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in UI_CALLS:
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _looks_translatable(arg.value):
                        found.add(arg.value)
    return found


def from_action_specs() -> set[str]:
    """Label & bantuan aksi diterjemahkan saat ditampilkan."""
    from app.actions.adb import register_adb_actions
    from app.actions.apps import register_app_actions
    from app.actions.base import CATEGORY_LABEL, REGISTRY
    from app.actions.game import register_game_actions
    from app.actions.host import register_host_actions

    for register in (register_adb_actions, register_app_actions,
                     register_game_actions, register_host_actions):
        register()

    found = set(CATEGORY_LABEL.values())
    for spec in REGISTRY.values():
        found.add(spec.label)
        if spec.help:
            found.add(spec.help)
        for param in spec.params:
            found.add(param.label)
            if param.help:
                found.add(param.help)
    return {v for v in found if _looks_translatable(v)}


def from_conditions() -> set[str]:
    from app.engine.rules import COMMON_CONDITIONS, CONDITION_SPECS

    found = {label for items in CONDITION_SPECS.values() for _, label, _ in items}
    found |= {label for _, label, _ in COMMON_CONDITIONS}
    return {v for v in found if _looks_translatable(v)}


def _looks_translatable(value: str) -> bool:
    if not any(ch.isalpha() for ch in value):
        return False
    # Buang hal teknis: path, kode warna, nama package, keycode.
    if value.startswith(("#", "/", "http", "com.", "KEYCODE_", "{")):
        return False
    if re.fullmatch(r"[a-z0-9_.\-]+", value):       # kunci/identifier
        return False
    return True


def collect() -> list[str]:
    return sorted(from_source_files() | from_action_specs() | from_conditions())


def update_locale(code: str, keys: list[str]) -> tuple[int, int, int]:
    """Perbarui satu berkas bahasa. Kembalikan (baru, terjemah, tak dipakai)."""
    path = LOCALES_DIR / f"{code}.json"
    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}

    strings = dict(existing.get("strings") or {})
    retired = dict(existing.get("_tidak_dipakai") or {})

    # Teks yang muncul kembali dipulihkan dari arsip.
    for key in keys:
        if key not in strings and key in retired:
            strings[key] = retired.pop(key)

    added = 0
    for key in keys:
        if key not in strings:
            strings[key] = ""
            added += 1

    live = set(keys)
    for key in [k for k in strings if k not in live]:
        retired[key] = strings.pop(key)

    payload = {
        "_bahasa": code,
        "_nama": LANGUAGES.get(code, code),
        "_petunjuk": (
            "Kunci adalah teks bahasa Indonesia. Isi nilainya dengan "
            "terjemahanmu. Nilai kosong berarti belum diterjemahkan dan "
            "akan tampil dalam bahasa Indonesia."
        ),
        "strings": dict(sorted(strings.items())),
    }
    if retired:
        payload["_tidak_dipakai"] = dict(sorted(retired.items()))

    LOCALES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    translated = sum(1 for v in strings.values() if str(v).strip())
    return added, translated, len(retired)


def main() -> int:
    keys = collect()
    print(f"{len(keys)} teks ditemukan\n")
    for code in LANGUAGES:
        if code == SOURCE_LANG:
            continue
        added, translated, retired = update_locale(code, keys)
        print(f"  {code}.json: {translated}/{len(keys)} diterjemahkan, "
              f"{added} baru, {retired} tidak dipakai")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
