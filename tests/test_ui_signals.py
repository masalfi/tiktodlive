"""Regresi: sinyal Qt tanpa argumen tidak boleh disambung langsung ke
sinyal yang membawa argumen.

Qt memaafkan argumen berlebih pada method Python biasa, TAPI tidak pada
Signal().emit - di situ ia melempar TypeError dan sinyalnya tidak pernah
terpancar, sehingga perubahan setting hilang diam-diam.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.config import DEFAULT_SETTINGS


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def panel(qapp):
    import copy

    from app.ui.panel_connect import ConnectPanel

    return ConnectPanel(copy.deepcopy(DEFAULT_SETTINGS))


def _watch(panel):
    """Hitung berapa kali settings_changed benar-benar terpancar."""
    fired = []
    panel.settings_changed.connect(lambda: fired.append(1))
    return fired


def test_backend_combo_emits_without_error(panel):
    """Ini bug yang dilaporkan: mengganti backend memicu TypeError."""
    fired = _watch(panel)
    panel.backend_combo.setCurrentIndex(1)
    assert fired, "settings_changed tidak terpancar saat backend diganti"


def test_reconnect_checkbox_emits(panel):
    fired = _watch(panel)
    panel.reconnect_check.setChecked(not panel.reconnect_check.isChecked())
    assert fired


def test_max_queue_spin_emits(panel):
    fired = _watch(panel)
    panel.max_queue_spin.setValue(panel.max_queue_spin.value() + 1)
    assert fired


def test_reboot_cap_spin_emits(panel):
    fired = _watch(panel)
    panel.reboot_cap_spin.setValue(panel.reboot_cap_spin.value() + 1)
    assert fired


def test_backend_choice_reaches_settings(panel):
    """Nilai yang dipilih benar-benar tersimpan, bukan sekadar tidak error."""
    import copy

    panel.backend_combo.setCurrentIndex(panel.backend_combo.findData("eulerstream"))
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    panel.apply_to_settings(settings)
    assert settings["tiktok"]["backend"] == "eulerstream"


def test_no_zero_arg_signal_bound_to_arg_carrying_signal():
    """Cegah pola ini muncul lagi di panel mana pun."""
    import ast
    import pathlib
    import re

    # sinyal Qt yang membawa argumen
    WITH_ARGS = {
        "currentIndexChanged", "toggled", "valueChanged", "textChanged",
        "currentRowChanged", "currentTextChanged", "stateChanged", "doubleClicked",
    }

    offenders = []
    for path in pathlib.Path("app/ui").glob("*.py"):
        source = path.read_text()
        # sinyal tanpa argumen yang dideklarasikan di file ini
        zero_arg = {
            m.group(1)
            for m in re.finditer(r"(\w+)\s*=\s*Signal\(\s*\)", source)
        }
        if not zero_arg:
            continue
        for match in re.finditer(r"\.(\w+)\.connect\(self\.(\w+)\.emit\)", source):
            signal, target = match.group(1), match.group(2)
            if signal in WITH_ARGS and target in zero_arg:
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line} {signal} -> {target}.emit")

    assert not offenders, (
        "Sinyal tanpa argumen disambung ke sinyal berargumen (akan TypeError): "
        + ", ".join(offenders)
    )
