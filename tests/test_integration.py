"""Audit keterhubungan fitur + adb bawaan scrcpy."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture(scope="module")
def window(qapp):
    """Satu MainWindow untuk seluruh modul.

    Aplikasi nyata hanya punya satu window. Membuat banyak instance
    menyalakan banyak server overlay di port yang sama dan membuat
    proses tes tidak stabil.
    """
    from app.ui.main_window import MainWindow

    w = MainWindow()
    yield w
    w.close()


# ---------------------------------------------------- adb bawaan scrcpy

@pytest.mark.real_adb
def test_vendor_adb_preferred_over_path(tmp_path, monkeypatch):
    """adb bawaan scrcpy harus menang dari PATH, supaya versinya cocok
    dengan scrcpy yang dipakai."""
    import app.config as cfg

    vendor = tmp_path / "vendor" / "scrcpy-x"
    vendor.mkdir(parents=True)
    name = "adb.exe" if cfg.sys.platform == "win32" else "adb"
    bundled = vendor / name
    bundled.write_text("#!/bin/sh\n")

    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    monkeypatch.setattr(cfg.shutil, "which", lambda _: "/usr/bin/adb")

    assert cfg.find_adb() == str(bundled)


@pytest.mark.real_adb
def test_falls_back_to_path_without_vendor(tmp_path, monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    monkeypatch.setattr(cfg.shutil, "which", lambda _: "/usr/bin/adb")
    assert cfg.find_adb() == "/usr/bin/adb"


@pytest.mark.real_adb
def test_configured_path_wins_over_vendor(tmp_path, monkeypatch):
    """Kalau user mengisi path manual, itu yang dipakai."""
    import app.config as cfg

    vendor = tmp_path / "vendor" / "scrcpy-x"
    vendor.mkdir(parents=True)
    name = "adb.exe" if cfg.sys.platform == "win32" else "adb"
    (vendor / name).write_text("x")

    manual = tmp_path / "adb-manual"
    manual.write_text("x")

    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    assert cfg.find_adb(str(manual)) == str(manual)


@pytest.mark.real_adb
def test_vendor_adb_none_when_missing(tmp_path, monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    assert cfg.vendor_adb() is None


# ------------------------------------------------------ audit integrasi

def test_every_action_has_handler_and_appears_in_ui(window):
    """Aksi yang terdaftar tapi tidak muncul di UI = tidak bisa dipakai."""
    from app.actions.base import HANDLERS, REGISTRY
    from app.ui.rule_editor import RuleEditor

    if True:
        editor = RuleEditor(parent=window)
        in_editor = {
            editor.action_type_combo.itemData(i)
            for i in range(editor.action_type_combo.count())
        }
        in_devices = {
            window.devices_panel.action_combo.itemData(i)
            for i in range(window.devices_panel.action_combo.count())
        }
        editor.close()

        for action_type in REGISTRY:
            assert action_type in HANDLERS, f"{action_type} tanpa handler"
            assert action_type in in_editor, f"{action_type} tidak ada di editor rule"
            assert action_type in in_devices, f"{action_type} tidak ada di tes manual"


def test_every_param_gets_a_widget(window):
    """Parameter tanpa widget berarti tidak bisa diisi user."""
    from app.actions.base import REGISTRY
    from app.ui.param_form import ParamForm

    for action_type, spec in REGISTRY.items():
        form = ParamForm(spec)
        for param in spec.params:
            assert param.name in form._widgets, f"{action_type}.{param.name} tanpa widget"


def test_core_objects_are_shared_not_copied(window):
    """Kalau panel memegang salinan, perubahan tidak akan berpengaruh."""
    w = window
    if True:
        assert w.host.overlay is w.overlay
        assert w.host.scrcpy_runner is w.scrcpy_panel.runner
        assert w.host.scrcpy_options is w.scrcpy_panel.options
        assert w.queue.adb is w.adb
        assert w.queue.host is w.host
        assert w.queue.safety is w.safety
        assert w.overlay_panel.host is w.host
        assert w.overlay_panel.overlay is w.overlay
        assert w.scrcpy_panel.adb is w.adb
        assert w.watcher.adb is w.adb


def test_serial_change_propagates_everywhere(window):
    w = window
    if True:
        w._on_serial_changed("uji-9999")
        assert w.adb.serial == "uji-9999"
        assert w.host.adb_serial == "uji-9999"
        assert w.watcher.serial == "uji-9999"
        assert w.settings["adb"]["serial"] == "uji-9999"


# ------------------------------------------------- pemilih channel overlay

def test_channel_combo_lists_rule_channels(window):
    """Channel yang dipakai rule harus muncul di dropdown tanpa diketik."""
    w = window
    if True:
        panel = w.overlay_panel
        panel.set_rule_channels(["alert", "efek", "musik"])
        names = [panel.channel_combo.itemData(i) for i in range(panel.channel_combo.count())]
        assert names[0] == "main"
        for expected in ("alert", "efek", "musik"):
            assert expected in names


def test_channel_combo_deduplicates(window):
    w = window
    if True:
        panel = w.overlay_panel
        panel.set_rule_channels(["alert", "Alert", "  ALERT  ", "main"])
        names = [panel.channel_combo.itemData(i) for i in range(panel.channel_combo.count())]
        assert names.count("alert") == 1
        assert names.count("main") == 1


def test_current_channel_strips_connection_label(window):
    """Item bisa berbunyi 'alert  (2 terbuka)' - yang dikirim harus 'alert'."""
    w = window
    if True:
        panel = w.overlay_panel
        panel.set_rule_channels(["alert"])
        panel.channel_combo.setCurrentText("alert  (2 terbuka)")
        assert panel.current_channel() == "alert"


def test_typing_new_channel_is_allowed(window):
    """Channel baru harus bisa diketik langsung tanpa didaftarkan dulu."""
    w = window
    if True:
        panel = w.overlay_panel
        panel.channel_combo.setCurrentText("channel-baru")
        assert panel.current_channel() == "channel-baru"


def test_rule_channels_collected_from_rules(window):
    from app.models import Action, Rule
    w = window
    if True:
        w.rules = [
            Rule(name="a", actions=[Action("host.overlay", {"channel": "alert"})]),
            Rule(name="b", actions=[Action("host.overlay_effect", {"channel": "efek"})]),
            Rule(name="c", actions=[Action("adb.tap", {"x": 1})]),      # bukan overlay
            Rule(name="d", actions=[Action("host.overlay", {"channel": ""})]),  # kosong
        ]
        assert sorted(w._rule_channels()) == ["alert", "efek"]
