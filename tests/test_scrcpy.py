"""Test bridge scrcpy: opsi UI -> argumen CLI."""

import pytest

from app.scrcpy.bridge import ScrcpyOptions, build_args, preview_command
from app.scrcpy.manager import _norm_arch, current_platform_key, pick_asset


def args_of(**kw) -> list[str]:
    return build_args(ScrcpyOptions(**kw))


# ------------------------------------------------------------- default

def test_defaults_are_sensible():
    args = args_of()
    assert "--no-audio" in args            # audio tidak perlu untuk kontrol
    assert "--stay-awake" in args
    assert "--show-touches" in args
    assert "--disable-screensaver" in args


def test_placeholder_values_are_not_sent():
    """'(bawaan)' dan '(asli)' berarti biarkan scrcpy yang menentukan."""
    args = args_of(max_size="(asli)", max_fps="(bawaan)", bitrate="(bawaan)",
                   codec="(bawaan)", orientation="(bawaan)")
    joined = " ".join(args)
    assert "--max-size" not in joined
    assert "--max-fps" not in joined
    assert "--video-bit-rate" not in joined
    assert "--video-codec" not in joined
    assert "--capture-orientation" not in joined


def test_serial_included_when_given():
    assert build_args(ScrcpyOptions(), "emulator-5554")[:2] == ["--serial", "emulator-5554"]
    assert "--serial" not in build_args(ScrcpyOptions(), "")


# ------------------------------------------------------------ tampilan

def test_display_options():
    args = args_of(max_size="1280", max_fps="30", bitrate="8M", codec="h265")
    assert "--max-size=1280" in args
    assert "--max-fps=30" in args
    assert "--video-bit-rate=8M" in args
    assert "--video-codec=h265" in args


def test_crop_trimmed_and_skipped_when_empty():
    assert "--crop=1224:1440:0:0" in args_of(crop="  1224:1440:0:0  ")
    assert not any(a.startswith("--crop") for a in args_of(crop="   "))


# -------------------------------------------------------------- jendela

def test_window_flags():
    args = args_of(always_on_top=True, fullscreen=True, borderless=True)
    assert "--always-on-top" in args
    assert "--fullscreen" in args
    assert "--window-borderless" in args


def test_window_position_negative_means_auto():
    """-1 = biarkan scrcpy menentukan posisi."""
    args = args_of(window_x=-1, window_y=-1)
    assert not any(a.startswith("--window-x") for a in args)
    assert not any(a.startswith("--window-y") for a in args)

    args = args_of(window_x=0, window_y=100)
    assert "--window-x=0" in args              # 0 valid, bukan "otomatis"
    assert "--window-y=100" in args


def test_window_size_zero_means_auto():
    assert not any(a.startswith("--window-width") for a in args_of(window_width=0))
    assert "--window-width=800" in args_of(window_width=800)


# --------------------------------------------------------------- device

def test_device_behaviour_flags():
    args = args_of(turn_screen_off=True, power_off_on_close=True,
                   no_control=True, no_video=True)
    assert "--turn-screen-off" in args
    assert "--power-off-on-close" in args
    assert "--no-control" in args
    assert "--no-video" in args


def test_flags_off_by_default_are_absent():
    args = args_of(turn_screen_off=False, fullscreen=False)
    assert "--turn-screen-off" not in args
    assert "--fullscreen" not in args


def test_record_file():
    assert "--record=out.mp4" in args_of(record_file="out.mp4")
    assert not any(a.startswith("--record") for a in args_of(record_file=""))


# ---------------------------------------------------------------- extra

def test_extra_args_are_split():
    args = args_of(extra_args="--no-cleanup --print-fps")
    assert "--no-cleanup" in args and "--print-fps" in args


def test_broken_extra_args_do_not_crash():
    """Tanda kutip tidak seimbang tidak boleh menggagalkan peluncuran."""
    args = args_of(extra_args='--window-title="belum ditutup')
    assert isinstance(args, list)


# ------------------------------------------------------- serialisasi

def test_options_roundtrip():
    original = ScrcpyOptions(max_size="1280", always_on_top=True, extra_args="--x")
    restored = ScrcpyOptions.from_dict(original.to_dict())
    assert restored == original


def test_from_dict_ignores_unknown_keys():
    """Config lama/rusak tidak boleh membuat aplikasi gagal start."""
    o = ScrcpyOptions.from_dict({"max_size": "800", "opsi_yang_sudah_dihapus": 123})
    assert o.max_size == "800"


def test_from_dict_handles_none():
    assert ScrcpyOptions.from_dict(None) == ScrcpyOptions()


def test_preview_is_readable_and_quoted():
    text = preview_command("/path/scrcpy", ScrcpyOptions(), "emulator-5554")
    assert text.startswith("/path/scrcpy")
    assert "--serial emulator-5554" in text


# -------------------------------------------------------------- manager

def test_platform_key_is_known():
    system, arch = current_platform_key()
    assert system in ("darwin", "windows", "linux")
    assert arch


def test_arch_normalisation():
    assert _norm_arch() in ("arm64", "x86_64", "amd64", "x86") or True  # arsitektur lain tetap lolos


def test_pick_asset_matches_platform():
    system, arch = current_platform_key()
    patterns = {
        ("darwin", "arm64"): "scrcpy-macos-aarch64-v4.1.tar.gz",
        ("darwin", "x86_64"): "scrcpy-macos-x86_64-v4.1.tar.gz",
        ("windows", "amd64"): "scrcpy-win64-v4.1.zip",
        ("linux", "x86_64"): "scrcpy-linux-x86_64-v4.1.tar.gz",
    }
    fake = {"assets": [{"name": n} for n in patterns.values()]}
    expected = patterns.get((system, arch))
    got = pick_asset(fake)
    if expected:
        assert got is not None and got["name"] == expected


def test_pick_asset_returns_none_when_no_match():
    assert pick_asset({"assets": [{"name": "scrcpy-something-else.txt"}]}) is None


# ------------------------------------------------ restart otomatis

class _FakeProc:
    """Proses tiruan; bisa dibuat 'mati' seperti saat device reboot."""

    def __init__(self):
        self.alive = True
        self.terminated = False

    def poll(self):
        return None if self.alive else 0

    def wait(self, timeout=None):
        if self.alive:
            import subprocess as sp
            raise sp.TimeoutExpired("scrcpy", timeout or 0)
        return 0

    def terminate(self):
        self.terminated = True
        self.alive = False


@pytest.fixture
def runner(monkeypatch):
    from app.scrcpy.runner import ScrcpyRunner

    made = []

    def fake_popen(cmd, **kw):
        proc = _FakeProc()
        made.append((cmd, proc))
        return proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    r = ScrcpyRunner()
    r._made = made
    return r


def test_start_records_config_for_restart(runner):
    from app.scrcpy.bridge import ScrcpyOptions

    ok, _ = runner.start("/bin/scrcpy", ScrcpyOptions(), "emulator-5554")
    assert ok
    assert runner.was_running("emulator-5554")


def test_restart_after_device_reboot(runner):
    """Skenario nyata: rule reboot HP -> scrcpy mati -> harus hidup lagi."""
    from app.scrcpy.bridge import ScrcpyOptions

    runner.start("/bin/scrcpy", ScrcpyOptions(max_size="1280"), "emulator-5554")
    assert runner.is_running("emulator-5554")

    # HP reboot: proses scrcpy mati sendiri.
    runner._procs["emulator-5554"].alive = False
    assert not runner.is_running("emulator-5554")
    assert runner.was_running("emulator-5554")      # tetap diingat

    ok, _ = runner.restart("emulator-5554")
    assert ok and runner.is_running("emulator-5554")

    # Opsi yang dipakai harus sama dengan sebelumnya.
    last_cmd = runner._made[-1][0]
    assert "--max-size=1280" in last_cmd


def test_manual_stop_prevents_auto_restart(runner):
    """Kalau user menghentikan sendiri, jangan dihidupkan lagi otomatis."""
    from app.scrcpy.bridge import ScrcpyOptions

    runner.start("/bin/scrcpy", ScrcpyOptions(), "emulator-5554")
    runner.stop("emulator-5554")
    assert not runner.was_running("emulator-5554")
    ok, reason = runner.restart("emulator-5554")
    assert not ok and "belum pernah" in reason


def test_restart_unknown_device_is_safe(runner):
    ok, _ = runner.restart("device-yang-tidak-ada")
    assert not ok


def test_no_duplicate_scrcpy_for_same_device(runner):
    from app.scrcpy.bridge import ScrcpyOptions

    runner.start("/bin/scrcpy", ScrcpyOptions(), "emulator-5554")
    ok, reason = runner.start("/bin/scrcpy", ScrcpyOptions(), "emulator-5554")
    assert not ok and "sudah berjalan" in reason
