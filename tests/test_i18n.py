"""Penjaga permanen untuk dukungan bahasa.

Test ini yang menahan tiga kesalahan yang paling mudah terjadi:
kunci terjemahan tidak cocok dengan teks di kode, placeholder hilang
saat diterjemahkan, dan berkas bahasa baru yang lupa dilengkapi.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import i18n
from app.i18n import LANGUAGES, LOCALES_DIR, SOURCE_LANG, tr

PLACEHOLDER = re.compile(r"\{(\w+)\}")
TARGET_LANGS = [c for c in LANGUAGES if c != SOURCE_LANG]


def _load(code: str) -> dict:
    return json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _restore_language():
    """Setiap test mengembalikan bahasa aktif; tr() global."""
    before = i18n.current_language()
    yield
    i18n.load_language(before)


@pytest.mark.parametrize("code", TARGET_LANGS)
def test_berkas_bahasa_ada_dan_valid(code: str) -> None:
    path = LOCALES_DIR / f"{code}.json"
    assert path.is_file(), f"locales/{code}.json tidak ada"
    data = _load(code)
    assert isinstance(data.get("strings"), dict), "kunci 'strings' wajib berupa objek"
    assert data.get("_bahasa") == code


@pytest.mark.parametrize("code", TARGET_LANGS)
def test_semua_teks_diterjemahkan(code: str) -> None:
    """Nilai kosong berarti teks masih tampil dalam bahasa Indonesia."""
    kosong = [k for k, v in _load(code)["strings"].items() if not str(v).strip()]
    assert not kosong, f"{len(kosong)} teks belum diterjemahkan di {code}.json: {kosong[:5]}"


@pytest.mark.parametrize("code", TARGET_LANGS)
def test_placeholder_tidak_hilang(code: str) -> None:
    """{nama} di kunci harus tetap ada di terjemahan.

    Kalau hilang, tr() gagal format dan teks jatuh kembali ke bahasa
    Indonesia tanpa peringatan apa pun.
    """
    rusak = []
    for key, value in _load(code)["strings"].items():
        if set(PLACEHOLDER.findall(key)) != set(PLACEHOLDER.findall(str(value))):
            rusak.append(key)
    assert not rusak, f"placeholder berubah di {code}.json: {rusak}"


@pytest.mark.parametrize("code", TARGET_LANGS)
def test_kunci_sama_di_semua_bahasa(code: str) -> None:
    """Semua berkas dibuat dari extractor yang sama, jadi kuncinya identik."""
    acuan = set(_load(TARGET_LANGS[0])["strings"])
    assert set(_load(code)["strings"]) == acuan


@pytest.mark.parametrize("code", TARGET_LANGS)
def test_extractor_menemukan_semua_kunci_yang_dipakai(code: str) -> None:
    """Kunci di berkas bahasa harus benar-benar ada di kode.

    Ini yang menangkap kunci basi setelah teks di kode diubah - kalau
    tidak, terjemahannya diam-diam tidak pernah terpakai.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.extract_strings import collect

    dipakai = set(collect())
    ada = set(_load(code)["strings"])
    basi = ada - dipakai
    assert not basi, f"kunci tidak lagi ada di kode ({code}.json): {sorted(basi)[:5]}"


def test_tr_memakai_terjemahan_dan_kembali_ke_sumber() -> None:
    strings = _load("en")["strings"]
    contoh, terjemahan = next(
        (k, v) for k, v in strings.items() if not PLACEHOLDER.search(k)
    )

    assert i18n.load_language("en") is True
    assert tr(contoh) == terjemahan
    # Teks di luar katalog tampil apa adanya, bukan kosong.
    assert tr("teks yang tidak ada di katalog") == "teks yang tidak ada di katalog"

    i18n.load_language(SOURCE_LANG)
    assert tr(contoh) == contoh


def test_tr_format_placeholder() -> None:
    i18n.load_language(SOURCE_LANG)
    assert tr("Antrian: {n}", n=3) == "Antrian: 3"


def test_tr_tidak_meledak_saat_placeholder_salah() -> None:
    """Terjemahan pihak ketiga bisa salah tulis; UI tidak boleh crash."""
    i18n.load_language(SOURCE_LANG)
    assert tr("Antrian: {n}") == "Antrian: {n}"


def test_bahasa_tidak_dikenal_ditolak_dengan_tenang() -> None:
    assert i18n.load_language("xx") is False
