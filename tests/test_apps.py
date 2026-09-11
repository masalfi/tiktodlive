"""Test aksi mengelola aplikasi: buka, tutup, mulai ulang."""

from types import SimpleNamespace

import pytest

from app.actions.apps import (
    PROTECTED,
    foreground_package,
    game_package,
    list_packages,
    register_app_actions,
)
from app.actions.base import HANDLERS, coerce_params, get_spec

register_app_actions()

FOKUS = (
    "  mCurrentFocus=Window{bd430d4 u0 com.mobile.legends/"
    "com.moba.unityplugin.MobaGameUnityActivity}\n"
)


class FakeAdb:
    def __init__(self, packages=None, focus=FOKUS, fail=False, game="com.mobile.legends"):
        self.packages = packages if packages is not None else [
            "com.mobile.legends", "com.whatsapp", "com.spotify.music",
        ]
        self.focus = focus
        self.fail = fail
        self.commands: list[list[str]] = []
        self.game_profile = {"package": game} if game else {}

    def run(self, args, timeout=None, binary=False):
        self.commands.append(list(args))
        if self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr="device offline")
        if args[:4] == ["shell", "pm", "list", "packages"]:
            body = "".join(f"package:{p}\n" for p in self.packages)
            return SimpleNamespace(returncode=0, stdout=body, stderr="")
        if args[:3] == ["shell", "dumpsys", "window"]:
            return SimpleNamespace(returncode=0, stdout=self.focus, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def stopped(self):
        return [c[3] for c in self.commands if c[:3] == ["shell", "am", "force-stop"]]

    def launched(self):
        return [c[3] for c in self.commands if c[:3] == ["shell", "monkey", "-p"]]


def run(adb, action, params=None):
    return HANDLERS[action](adb, coerce_params(action, params or {}))


# ------------------------------------------------------------- pembacaan

def test_list_packages_parsed():
    adb = FakeAdb()
    assert list_packages(adb) == sorted(adb.packages)


def test_list_packages_uses_user_apps_only():
    """-3 membatasi ke aplikasi yang dipasang user, bukan bawaan sistem."""
    adb = FakeAdb()
    list_packages(adb)
    assert "-3" in adb.commands[-1]


def test_list_packages_empty_on_failure():
    assert list_packages(FakeAdb(fail=True)) == []


def test_foreground_package_parsed():
    assert foreground_package(FakeAdb()) == "com.mobile.legends"


def test_foreground_empty_when_no_package():
    """Panel notifikasi/lockscreen tidak punya package."""
    adb = FakeAdb(focus="mCurrentFocus=Window{f4 u0 NotificationShade}\n")
    assert foreground_package(adb) == ""


def test_game_package_from_profile():
    assert game_package(FakeAdb()) == "com.mobile.legends"
    assert game_package(FakeAdb(game="")) == ""


# ------------------------------------------------------------- menutup

def test_close_game_needs_no_typing():
    """Inti fitur: tutup game tanpa tahu nama package-nya."""
    adb = FakeAdb()
    result = run(adb, "app.close_game")
    assert result.ok
    assert adb.stopped() == ["com.mobile.legends"]


def test_close_game_without_profile_explains():
    adb = FakeAdb(game="")
    result = run(adb, "app.close_game")
    assert not result.ok
    assert "package" in result.message.lower()
    assert adb.stopped() == []


def test_close_specific_app():
    adb = FakeAdb()
    assert run(adb, "app.close", {"package": "com.whatsapp"}).ok
    assert adb.stopped() == ["com.whatsapp"]


def test_close_foreground_app():
    adb = FakeAdb()
    result = run(adb, "app.close_foreground")
    assert result.ok
    assert adb.stopped() == ["com.mobile.legends"]


def test_close_foreground_unreadable_reported():
    adb = FakeAdb(focus="mCurrentFocus=null\n")
    result = run(adb, "app.close_foreground")
    assert not result.ok and adb.stopped() == []


# ------------------------------------------------------------ keamanan

@pytest.mark.parametrize("package", sorted(PROTECTED))
def test_system_apps_refused(package):
    """Menutup systemui bisa membuat HP tidak bisa dipakai sampai reboot."""
    adb = FakeAdb()
    result = run(adb, "app.close", {"package": package})
    assert not result.ok
    assert "sistem" in result.message
    assert adb.stopped() == []


def test_empty_package_refused():
    adb = FakeAdb()
    assert not run(adb, "app.close", {"package": "   "}).ok
    assert adb.stopped() == []


def test_clear_background_skips_system_and_foreground():
    adb = FakeAdb(packages=[
        "com.mobile.legends", "com.whatsapp", "com.android.systemui",
    ])
    result = run(adb, "app.clear_background")
    assert result.ok
    stopped = adb.stopped()
    assert "com.whatsapp" in stopped
    assert "com.android.systemui" not in stopped      # sistem
    assert "com.mobile.legends" not in stopped        # sedang tampil


def test_clear_background_honours_exceptions():
    adb = FakeAdb(packages=["com.whatsapp", "com.spotify.music"])
    run(adb, "app.clear_background", {"kecuali": "com.spotify.music"})
    assert "com.spotify.music" not in adb.stopped()
    assert "com.whatsapp" in adb.stopped()


# ------------------------------------------------------------- membuka

def test_open_app():
    adb = FakeAdb()
    assert run(adb, "app.open", {"package": "com.mobile.legends"}).ok
    assert adb.launched() == ["com.mobile.legends"]


def test_open_missing_app_reported():
    """monkey mengembalikan 0 walau aplikasinya tidak ada - pesannya
    harus tetap dibaca, kalau tidak kegagalan terlihat seperti sukses."""

    class NoActivity(FakeAdb):
        def run(self, args, timeout=None, binary=False):
            self.commands.append(list(args))
            if args[:3] == ["shell", "monkey", "-p"]:
                return SimpleNamespace(
                    returncode=0, stdout="** No activities found to run", stderr=""
                )
            return super().run(args, timeout, binary)

    result = run(NoActivity(), "app.open", {"package": "com.tidak.ada"})
    assert not result.ok and "terpasang" in result.message


def test_restart_stops_then_launches():
    adb = FakeAdb()
    result = run(adb, "app.restart", {"package": "com.whatsapp", "delay_sec": 0})
    assert result.ok
    assert adb.stopped() == ["com.whatsapp"]
    assert adb.launched() == ["com.whatsapp"]


def test_restart_game_uses_profile():
    adb = FakeAdb()
    result = run(adb, "app.restart_game", {"delay_sec": 0})
    assert result.ok
    assert adb.stopped() == ["com.mobile.legends"]
    assert adb.launched() == ["com.mobile.legends"]


def test_restart_does_not_launch_if_stop_refused():
    """Kalau penutupan ditolak (aplikasi sistem), jangan lanjut membuka."""
    adb = FakeAdb()
    result = run(adb, "app.restart", {"package": "com.android.systemui", "delay_sec": 0})
    assert not result.ok
    assert adb.launched() == []


# ----------------------------------------------------------- registrasi

@pytest.mark.parametrize("action", [
    "app.open", "app.close", "app.restart",
    "app.close_game", "app.restart_game",
    "app.close_foreground", "app.clear_background",
])
def test_registered_in_app_category(action):
    spec = get_spec(action)
    assert spec is not None and spec.category == "app"


def test_package_fields_use_picker_kind():
    """kind 'package' membuat UI menampilkan daftar aplikasi HP, bukan
    kolom teks kosong yang harus diketik manual."""
    for action in ("app.open", "app.close", "app.restart"):
        kinds = {p.name: p.kind for p in get_spec(action).params}
        assert kinds["package"] == "package"


def test_clear_background_marked_dangerous():
    assert get_spec("app.clear_background").dangerous is True
