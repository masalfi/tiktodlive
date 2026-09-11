"""Test perbaikan pengalaman pengguna: pembersih username & tab Mulai."""

import pytest

from app.live.client import clean_username


# ------------------------------------------------------ username

@pytest.mark.parametrize("raw,expected", [
    ("budi", "budi"),
    ("@budi", "budi"),
    ("  @Budi  ", "Budi"),
    # Orang sering menyalin "@nama/live" dari aplikasi TikTok.
    ("dlyzreal/live", "dlyzreal"),
    ("@dlyzreal/live", "dlyzreal"),
    # Atau menempel URL profil.
    ("https://www.tiktok.com/@dlyzreal/live", "dlyzreal"),
    ("https://tiktok.com/@budi", "budi"),
    ("www.tiktok.com/@a.qim.joul.t/live", "a.qim.joul.t"),
    ("tiktok.com/@budi?lang=id", "budi"),
    ("tiktok.com/@budi#bagian", "budi"),
    ("", ""),
    ("   ", ""),
])
def test_clean_username(raw, expected):
    assert clean_username(raw) == expected


def test_dots_in_username_kept():
    """Username TikTok boleh mengandung titik - jangan ikut dipotong."""
    assert clean_username("a.qim.joul.t") == "a.qim.joul.t"


def test_clean_username_is_idempotent():
    for raw in ["@budi/live", "https://tiktok.com/@siti", "budi"]:
        once = clean_username(raw)
        assert clean_username(once) == once


def test_worker_cleans_username():
    """Pembersihan harus terjadi juga kalau nilai datang dari config lama."""
    from app.live.client import TikTokWorker

    worker = TikTokWorker("dlyzreal/live")
    assert worker.username == "dlyzreal"


# ---------------------------------------------------------- tab Mulai

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture(scope="module")
def window(qapp):
    from app.ui.main_window import MainWindow

    w = MainWindow()
    yield w
    w.close()


def test_home_tab_is_first(window):
    """Pengguna baru harus mendarat di panduan, bukan di layar teknis."""
    assert window.tabs.tabText(0) == "Mulai"


def test_every_step_points_to_a_real_tab(window):
    """Tombol 'Buka' yang menunjuk tab tidak ada = tombol mati."""
    names = {window.tabs.tabText(i) for i in range(window.tabs.count())}
    for row in window.home_panel.rows:
        assert row.step.tab in names, f"langkah '{row.step.title}' menunjuk tab tidak ada"


def test_open_tab_button_switches_tab(window):
    window.tabs.setCurrentIndex(0)
    window.home_panel.open_tab.emit("Rules")
    assert window.tabs.tabText(window.tabs.currentIndex()) == "Rules"
    window.tabs.setCurrentIndex(0)


def test_unknown_tab_name_is_ignored(window):
    """Jangan crash kalau nama tab salah ketik."""
    window.tabs.setCurrentIndex(0)
    window.home_panel.open_tab.emit("TabTidakAda")
    assert window.tabs.currentIndex() == 0


def test_steps_report_status_without_crashing(window):
    from app.ui.panel_home import OPSIONAL, PERLU, SIAP

    for row in window.home_panel.rows:
        status = row.refresh()
        assert status in (SIAP, PERLU, OPSIONAL)
        assert row.detail.text()


def test_step_check_failure_is_contained(window):
    """Satu pemeriksaan yang error tidak boleh mematikan tab Mulai."""
    from app.ui.panel_home import PERLU

    row = window.home_panel.rows[0]
    original = row.step.check
    row.step.check = lambda: (_ for _ in ()).throw(RuntimeError("rusak"))
    try:
        assert row.refresh() == PERLU
        assert "tidak bisa diperiksa" in row.detail.text()
    finally:
        row.step.check = original


def test_missing_account_is_flagged(window):
    from app.ui.panel_home import PERLU

    original = window.settings["tiktok"]["username"]
    window.settings["tiktok"]["username"] = ""
    try:
        status, detail = window.home_panel._check_account()
        assert status == PERLU and "belum diisi" in detail
    finally:
        window.settings["tiktok"]["username"] = original


def test_rules_all_disabled_is_flagged(window):
    from app.models import Action, Rule
    from app.ui.panel_home import PERLU

    original = window.rules
    window.rules = [Rule(name="x", enabled=False, actions=[Action("adb.tap")])]
    try:
        status, detail = window.home_panel._check_rules()
        assert status == PERLU and "nonaktif" in detail
    finally:
        window.rules = original
