"""Konfigurasi bersama untuk semua test.

Yang paling penting di sini: test TIDAK BOLEH menulis ke config asli
pengguna. Sebelumnya sebuah test integrasi memanggil _on_serial_changed()
yang menyimpan serial palsu ke config/settings.yaml sungguhan, sehingga
aplikasi kehilangan koneksi ke HP. Fixture di bawah mengalihkan semua
jalur tulis ke folder sementara.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Arahkan semua penyimpanan ke folder sementara.

    Berlaku otomatis untuk SEMUA test - tidak perlu diminta.
    """
    import app.config as cfg

    sandbox = tmp_path / "config"
    sandbox.mkdir(parents=True, exist_ok=True)

    # Salin profil & rule asli supaya test tetap punya data realistis,
    # tapi menulis ke salinan, bukan ke aslinya.
    for name in ("rules.yaml", "game_profiles.yaml"):
        source = cfg.CONFIG_DIR / name
        if source.exists():
            shutil.copy2(source, sandbox / name)

    monkeypatch.setattr(cfg, "CONFIG_DIR", sandbox)
    monkeypatch.setattr(cfg, "SETTINGS_PATH", sandbox / "settings.yaml")
    monkeypatch.setattr(cfg, "RULES_PATH", sandbox / "rules.yaml")
    monkeypatch.setattr(cfg, "GAMES_PATH", sandbox / "game_profiles.yaml")

    # Cache ikon gift juga menulis ke folder config.
    try:
        import app.ui.gift_icons as icons

        monkeypatch.setattr(icons, "ICON_DIR", sandbox / "gift_icons")
    except Exception:                               # noqa: BLE001
        pass

    try:
        import app.live.gifts as gifts

        monkeypatch.setattr(gifts, "CACHE_PATH", sandbox / "gifts.json")
    except Exception:                               # noqa: BLE001
        pass

    yield sandbox


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_adb: test ini memang menguji pencarian adb, jangan diblokir",
    )


@pytest.fixture(autouse=True)
def no_real_device(request, monkeypatch):
    """Cegah test menyentuh HP sungguhan.

    Tanpa ini, test bisa mengirim tap/reboot ke HP yang sedang tersambung.
    Test yang memang menguji pencarian adb menandai dirinya dengan
    @pytest.mark.real_adb.
    """
    if request.node.get_closest_marker("real_adb"):
        return

    import app.config as cfg

    monkeypatch.setattr(cfg, "find_adb", lambda configured="": None)
