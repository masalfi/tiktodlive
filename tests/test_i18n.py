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


# ----------------------------------------------------------- audit cakupan

#: Teks yang memang tidak diterjemahkan, beserta alasannya. Daftar ini
#: sengaja eksplisit: teks pengguna yang lupa dibungkus tr() akan
#: menggagalkan test di bawah, bukan lolos diam-diam ke rilis.
SENGAJA_TIDAK_DITERJEMAHKAN = {
    # Gema perintah adb - mencerminkan perintah yang benar-benar
    # dijalankan, jadi harus sama persis di semua bahasa.
    "tap (", "swipe (", "reboot (", "wifi ", "airplane mode ", "brightness ",
    "volume ", "exit code ", "exit ",
    # Parsing keluaran adb / pesan pustaka - bukan untuk dibaca pengguna.
    "connected to", "No activities found", "rate limit",
    # Data & nama diri.
    "Gift #", "Live Controller", "TikTok Live Controller",
    "Bahasa Indonesia", "main", "scrcpy", "x",
    "#ff4d94", "● LIVE", "OK  ",
    # Format logging & anotasi tipe.
    "%(asctime)s %(levelname)s %(name)s: %(message)s",
    "Callable[[], list[str]] | None",
    "Callable[[], list[tuple[str, str]]] | None",
}

#: Modul yang seluruh isinya bukan teks pengguna.
BUKAN_TEKS = {"app/ui/theme.py"}      # stylesheet Qt & nama font


def _kandidat_belum_dibungkus() -> list[tuple[str, int, str]]:
    """Cari literal berbentuk kalimat yang belum dibungkus tr().

    Sengaja longgar. Versi pertama menyaring berdasarkan daftar kata
    Indonesia, dan teks seperti "Menunggu device kembali..." lolos karena
    tak satu pun katanya ada di daftar itu - pengguna yang menemukannya,
    bukan test.
    """
    import ast

    import sys

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from tools.extract_strings import from_action_specs, from_conditions, from_ui_tables

    # Label aksi, kondisi, dan tabel UI didefinisikan sebagai literal biasa
    # lalu dibungkus tr() di tempat ditampilkan - modul-modul itu diimpor
    # sebelum bahasa dipasang. Daftar sahnya diambil dari extractor supaya
    # tidak perlu dirawat dua kali.
    dibungkus_di_pemakaian = from_action_specs() | from_conditions() | from_ui_tables()

    codey = re.compile(r"^(?:[\w./\\:*%$@#+~-]+|[A-Z][A-Z0-9_]+|\s*)$")
    markup = re.compile(r"[{};]\s*$|^\s*[.#]?[\w-]+\s*\{|<[a-z]+[ >]|:\s*#[0-9a-f]{3,8}", re.I)
    fmt_log = re.compile(r"%[sdrifx]")

    def literal_ids(tree, ambil):
        out = set()
        for node in ast.walk(tree):
            for sub in ambil(node):
                for inner in ast.walk(sub):
                    if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                        out.add(id(inner))
        return out

    def arg_tr(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
            return node.args
        return []

    def docstring(node):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                return [body[0].value]
        return []

    def arg_log(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in ("log", "logger", "logging"):
                return node.args
        return []

    temuan = []
    for path in sorted((root / "app").rglob("*.py")):
        rel = str(path.relative_to(root))
        if rel in BUKAN_TEKS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lewati = (literal_ids(tree, arg_tr) | literal_ids(tree, docstring)
                  | literal_ids(tree, arg_log))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in lewati:
                continue
            s = node.value
            if s in dibungkus_di_pemakaian or s in SENGAJA_TIDAK_DITERJEMAHKAN or len(s) < 3:
                continue
            if codey.match(s) or markup.search(s) or fmt_log.search(s):
                continue
            if not any(ch.isalpha() for ch in s):
                continue
            # Kata tunggal huruf kecil hampir selalu identifier; yang
            # berhuruf kapital ("Connect", "Error") justru teks tombol.
            if " " not in s and not s.endswith((".", "?", "!", ":", "...")) \
               and not s[:1].isupper():
                continue
            temuan.append((rel, node.lineno, s))
    return temuan


def test_tidak_ada_teks_pengguna_yang_lolos_dari_tr() -> None:
    sisa = _kandidat_belum_dibungkus()
    pesan = "\n".join(f"  {f}:{ln}  {s!r}" for f, ln, s in sisa)
    assert not sisa, (
        f"{len(sisa)} teks belum dibungkus tr() (atau belum masuk katalog):\n{pesan}\n\n"
        "Bungkus dengan tr(), lalu jalankan tools/extract_strings.py. Kalau teks itu "
        "memang bukan untuk pengguna, tambahkan ke SENGAJA_TIDAK_DITERJEMAHKAN."
    )
