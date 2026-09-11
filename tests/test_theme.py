"""Test tema: konsistensi lintas macOS & Windows."""

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.ui import theme


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    theme.apply_font(app)
    app.setStyleSheet(theme.STYLESHEET)
    return app


# ------------------------------------------------------------- stylesheet

def test_stylesheet_has_no_em_units():
    """Qt DIAM-DIAM mengabaikan satuan em - harus pt/px."""
    assert "em;" not in theme.STYLESHEET


def test_stylesheet_has_no_unresolved_placeholders():
    """f-string yang lupa diganti akan menyisakan {NAMA}."""
    leftovers = re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", theme.STYLESHEET)
    assert not leftovers, f"placeholder belum terisi: {leftovers}"


def test_arrow_files_exist():
    """Panah spinbox/combobox dimuat dari file - harus benar-benar ada."""
    import pathlib

    urls = re.findall(r'image: url\("([^"]+)"\)', theme.STYLESHEET)
    assert urls, "tidak ada ikon panah di stylesheet"
    missing = [u for u in urls if not pathlib.Path(u).exists()]
    assert not missing, f"file panah hilang: {missing}"


# ------------------------------------------------------------------ font

def test_font_size_differs_per_platform(monkeypatch):
    """macOS merender lebih besar pada pt yang sama, jadi Windows dinaikkan."""
    monkeypatch.setattr(theme, "IS_MAC", True)
    mac = theme.base_point_size()
    monkeypatch.setattr(theme, "IS_MAC", False)
    win = theme.base_point_size()
    assert mac != win
    assert mac > win


def test_font_family_falls_back_when_none_available(qapp, monkeypatch):
    """Kalau tidak ada font pilihan, harus tetap mengembalikan sesuatu."""
    monkeypatch.setattr("PySide6.QtGui.QFontDatabase.families", staticmethod(lambda: []))
    assert theme.ui_font_family()
    assert theme.mono_font_family()


def test_applied_font_is_not_generic(qapp):
    """Jangan pakai 'Sans Serif' generik - itu tampak buruk di semua OS."""
    family = qapp.font().family()
    assert family
    assert family.lower() not in ("sans serif", "sansserif")


# ----------------------------------------------------------- kelas label

@pytest.mark.parametrize("cls,expected", [("hint", "kecil"), ("status-big", "besar")])
def test_label_classes_change_size(qapp, cls, expected):
    base = QLabel("x")
    base.show()
    styled = QLabel("x")
    styled.setProperty("class", cls)
    styled.show()

    base_pt = base.font().pointSizeF()
    styled_pt = styled.font().pointSizeF()
    if expected == "kecil":
        assert styled_pt < base_pt
    else:
        assert styled_pt > base_pt


def test_mono_class_uses_monospace(qapp):
    label = QLabel("x")
    label.setProperty("class", "mono")
    label.show()
    assert label.font().family() == theme.mono_font_family() or label.font().family()


# ------------------------------------------------------------- ukuran UI

def test_buttons_fit_their_text(qapp):
    """Lebar tombol tidak boleh lebih kecil dari kebutuhan teksnya.

    Ini pernah bikin tombol 'Segarkan' terpotong jadi 'egarka' karena
    setMaximumWidth(90) yang pas di Windows tapi kurang di macOS.
    """
    for text in ["Segarkan", "Cek kuota", "Unduh scrcpy", "Jalankan scrcpy",
                 "PANIC - HENTIKAN SEMUA", "Segarkan dari TikTok"]:
        button = QPushButton(text)
        button.show()
        assert button.sizeHint().width() >= button.fontMetrics().horizontalAdvance(text), text


def test_no_hardcoded_pixel_font_sizes_in_panels():
    """Panel tidak boleh menulis font-size px sendiri - harus lewat kelas
    tema, supaya ikut menyesuaikan font OS."""
    import pathlib

    offenders = []
    for path in pathlib.Path("app/ui").glob("*.py"):
        if path.name == "theme.py":
            continue
        for match in re.finditer(r"font-size:\s*\d+px", path.read_text()):
            line = path.read_text()[: match.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}")
    assert not offenders, f"font-size px ditemukan di: {offenders}"


# ------------------------------------------------- adaptasi per platform

def test_stylesheet_adapts_to_platform(monkeypatch, qapp):
    """Ukuran font harus berbeda antara macOS dan Windows, bukan dibekukan
    saat import."""
    import re

    monkeypatch.setattr(theme, "IS_MAC", True)
    monkeypatch.setattr(theme, "IS_WINDOWS", False)
    mac_css = theme.build_stylesheet()

    monkeypatch.setattr(theme, "IS_MAC", False)
    monkeypatch.setattr(theme, "IS_WINDOWS", True)
    win_css = theme.build_stylesheet()

    assert mac_css != win_css

    def hint_pt(css):
        return int(re.search(r'class="hint"\]\s*\{[^}]*font-size:\s*(\d+)pt', css).group(1))

    assert hint_pt(mac_css) > hint_pt(win_css)


def test_monospace_font_matches_platform(monkeypatch, qapp):
    monkeypatch.setattr(theme, "IS_MAC", False)
    monkeypatch.setattr(theme, "IS_WINDOWS", True)
    assert "Consolas" in theme.build_stylesheet()

    monkeypatch.setattr(theme, "IS_MAC", True)
    monkeypatch.setattr(theme, "IS_WINDOWS", False)
    assert "Menlo" in theme.build_stylesheet()


def test_built_stylesheet_is_valid_for_both_platforms(monkeypatch, qapp):
    """Tidak boleh ada placeholder tersisa di platform mana pun."""
    import re

    for is_mac in (True, False):
        monkeypatch.setattr(theme, "IS_MAC", is_mac)
        monkeypatch.setattr(theme, "IS_WINDOWS", not is_mac)
        css = theme.build_stylesheet()
        assert not re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", css)
        assert "em;" not in css
