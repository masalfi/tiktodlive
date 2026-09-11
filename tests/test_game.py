"""Test aksi game: resolusi koordinat, orientasi, dan perintah adb."""

from types import SimpleNamespace

import pytest

from app.actions.base import HANDLERS, coerce_params, get_spec
from app.actions.game import (
    DIRECTIONS,
    current_rotation,
    physical_size,
    register_game_actions,
    resolve_point,
    screen_awake,
    screen_size,
)

register_game_actions()

PROFILE = {
    "landscape": True,
    "buttons": {
        "ultimate": {"x": 0.865, "y": 0.450},
        "recall": {"x": 0.600, "y": 0.940},
        "skill1": {"x": 0.735, "y": 0.850},
        "joystick": {"x": 0.160, "y": 0.720},
    },
}


class FakeAdb:
    """adb tiruan.

    Meniru perilaku Android yang penting: `wm size` SELALU melaporkan
    ukuran fisik (tegak), sedangkan rotasi sebenarnya hanya terbaca dari
    `dumpsys window`.
    """

    def __init__(self, width=1080, height=2280, rotation=1, fail=False, awake=True):
        # width/height = ukuran FISIK (seperti yang dilaporkan wm size)
        self.width, self.height = width, height
        self.rotation = rotation          # 0/2 = tegak, 1/3 = mendatar
        self.fail = fail
        self.awake = awake
        self.commands: list[list[str]] = []
        self.game_profile = PROFILE

    def run(self, args, timeout=None, binary=False):
        self.commands.append(list(args))
        if self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr="device offline")
        if args[:3] == ["shell", "wm", "size"]:
            return SimpleNamespace(
                returncode=0, stdout=f"Physical size: {self.width}x{self.height}\n", stderr=""
            )
        if args[:3] == ["shell", "dumpsys", "window"]:
            return SimpleNamespace(
                returncode=0,
                stdout=f"  mRotation=0 mCurrentRotation=ROTATION_{self.rotation}\n",
                stderr="",
            )
        if args[:3] == ["shell", "dumpsys", "power"]:
            state = "Awake" if self.awake else "Dozing"
            return SimpleNamespace(returncode=0, stdout=f"mWakefulness={state}\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def input_commands(self):
        return [c for c in self.commands if len(c) > 2 and c[1] == "input"]


def run(adb, action_type, params):
    return HANDLERS[action_type](adb, coerce_params(action_type, params))


# ------------------------------------------------------------ ukuran layar

def test_physical_size_parsed():
    assert physical_size(FakeAdb(1080, 2280)) == (1080, 2280)


@pytest.mark.parametrize("rotation,expected", [
    (0, (1080, 2280)), (2, (1080, 2280)),        # tegak
    (1, (2280, 1080)), (3, (2280, 1080)),        # mendatar
])
def test_screen_size_follows_rotation(rotation, expected):
    """`wm size` selalu bilang 1080x2280; rotasi yang menentukan ruang
    koordinat yang dipakai `input tap`."""
    assert screen_size(FakeAdb(1080, 2280, rotation=rotation)) == expected


def test_rotation_read_from_dumpsys():
    assert current_rotation(FakeAdb(rotation=3)) == 3


def test_screen_awake_detected():
    assert screen_awake(FakeAdb(awake=True)) is True
    assert screen_awake(FakeAdb(awake=False)) is False


def test_screen_size_none_on_failure():
    assert screen_size(FakeAdb(fail=True)) is None


def test_override_size_wins():
    """Kalau ada Override size, itu yang berlaku - bukan Physical."""

    class Override(FakeAdb):
        def run(self, args, timeout=None, binary=False):
            if args[:3] == ["shell", "wm", "size"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout="Physical size: 1440x3040\nOverride size: 1080x2280\n",
                    stderr="",
                )
            return super().run(args, timeout, binary)

    # rotation=0 (tegak), jadi hasilnya apa adanya
    assert screen_size(Override(rotation=0)) == (1080, 2280)


# --------------------------------------------------------------- koordinat

def test_percentage_becomes_pixels():
    """0.865 x 2280 = 1972 - koordinat ikut resolusi, bukan angka tetap."""
    assert resolve_point(FakeAdb(1080, 2280, rotation=1), PROFILE, "ultimate") == (1972, 486)


def test_landscape_profile_uses_rotated_size():
    """Pixel 4: fisik 1080x2280, tapi saat mendatar ruang koordinatnya
    2280x1080. Inilah yang harus dipakai."""
    assert resolve_point(FakeAdb(1080, 2280, rotation=1), PROFILE, "ultimate") == (1972, 486)


def test_refuses_when_orientation_differs():
    """Menukar sisi diam-diam menghasilkan titik yang salah. Lebih baik
    memberi tahu daripada menekan tempat acak - inilah bug yang membuat
    'Tes tekan' seolah berhasil padahal tidak menekan apa pun."""
    message = resolve_point(FakeAdb(1080, 2280, rotation=0), PROFILE, "ultimate")
    assert isinstance(message, str)
    assert "mendatar" in message and "tegak" in message


def test_portrait_profile_works_in_portrait():
    portrait_profile = {"landscape": False, "buttons": {"x": {"x": 0.5, "y": 0.5}}}
    assert resolve_point(FakeAdb(1080, 2280, rotation=0), portrait_profile, "x") == (540, 1140)


def test_different_resolution_scales():
    """HP lain dengan resolusi lain harus tetap menekan tombol yang sama."""
    pixel4 = resolve_point(FakeAdb(1080, 2280, rotation=1), PROFILE, "ultimate")
    other = resolve_point(FakeAdb(1080, 1920, rotation=1), PROFILE, "ultimate")
    assert pixel4 != other
    assert other == (int(0.865 * 1920), int(0.450 * 1080))


def test_unknown_button_lists_available():
    message = resolve_point(FakeAdb(), PROFILE, "tidak-ada")
    assert isinstance(message, str)
    assert "belum dikalibrasi" in message
    assert "ultimate" in message          # sebutkan yang tersedia


def test_broken_entry_reported():
    bad = {"landscape": True, "buttons": {"x": {"x": "bukan angka", "y": 0.5}}}
    assert isinstance(resolve_point(FakeAdb(), bad, "x"), str)


def test_screen_read_failure_reported():
    assert "ukuran layar" in resolve_point(FakeAdb(fail=True), PROFILE, "ultimate")


# ----------------------------------------------------------------- aksi

def test_tap_button_sends_input_tap():
    adb = FakeAdb()
    result = run(adb, "game.tap_button", {"button": "ultimate"})
    assert result.ok
    assert adb.input_commands()[-1] == ["shell", "input", "tap", "1972", "486"]


def test_tap_button_repeat():
    adb = FakeAdb()
    run(adb, "game.tap_button", {"button": "skill1", "repeat": 3, "gap_ms": 0})
    assert len(adb.input_commands()) == 3


def test_repeat_is_capped():
    adb = FakeAdb()
    run(adb, "game.tap_button", {"button": "skill1", "repeat": 9999, "gap_ms": 0})
    assert len(adb.input_commands()) <= 20


def test_hold_uses_swipe_with_same_point():
    """Tekan-tahan di Android = swipe dari titik yang sama ke titik itu."""
    adb = FakeAdb()
    result = run(adb, "game.hold_button", {"button": "recall", "duration_ms": 2000})
    assert result.ok
    cmd = adb.input_commands()[-1]
    assert cmd[2] == "swipe"
    assert cmd[3] == cmd[5] and cmd[4] == cmd[6]     # x1==x2, y1==y2
    assert cmd[7] == "2000"


def test_aim_skill_drags_away_from_button():
    adb = FakeAdb()
    result = run(adb, "game.aim_skill", {"button": "skill1", "direction": "kiri", "distance": 0.1})
    assert result.ok
    cmd = adb.input_commands()[-1]
    x1, x2 = int(cmd[3]), int(cmd[5])
    assert x2 < x1                                   # 'kiri' harus ke kiri


@pytest.mark.parametrize("direction,check", [
    ("kanan", lambda x1, y1, x2, y2: x2 > x1),
    ("kiri", lambda x1, y1, x2, y2: x2 < x1),
    ("atas", lambda x1, y1, x2, y2: y2 < y1),
    ("bawah", lambda x1, y1, x2, y2: y2 > y1),
])
def test_directions_go_the_right_way(direction, check):
    adb = FakeAdb()
    run(adb, "game.move", {"direction": direction, "duration_ms": 500})
    cmd = adb.input_commands()[-1]
    assert check(int(cmd[3]), int(cmd[4]), int(cmd[5]), int(cmd[6]))


def test_unknown_direction_rejected():
    adb = FakeAdb()
    result = run(adb, "game.move", {"direction": "serong-aneh"})
    assert not result.ok and "tidak dikenal" in result.message


def test_drag_stays_inside_screen():
    """Jarak besar tidak boleh menghasilkan koordinat di luar layar."""
    adb = FakeAdb(1080, 2280, rotation=1)
    run(adb, "game.aim_skill", {"button": "ultimate", "direction": "kanan", "distance": 0.5})
    cmd = adb.input_commands()[-1]
    assert 0 < int(cmd[5]) < 2280
    assert 0 < int(cmd[6]) < 1080


def test_combo_taps_in_order():
    adb = FakeAdb()
    result = run(adb, "game.combo", {"buttons": "skill1,ultimate", "gap_ms": 0})
    assert result.ok
    taps = adb.input_commands()
    assert len(taps) == 2
    assert taps[0][3:5] == ["1675", "918"]           # skill1
    assert taps[1][3:5] == ["1972", "486"]           # ultimate


def test_combo_stops_and_reports_on_unknown_button():
    adb = FakeAdb()
    result = run(adb, "game.combo", {"buttons": "skill1,tidak-ada,ultimate", "gap_ms": 0})
    assert not result.ok
    assert "skill1" in result.message                # sebutkan yang sudah jalan
    assert len(adb.input_commands()) == 1


def test_move_needs_joystick_calibrated():
    adb = FakeAdb()
    adb.game_profile = {"landscape": True, "buttons": {"ultimate": {"x": 0.5, "y": 0.5}}}
    result = run(adb, "game.move", {"direction": "kanan"})
    assert not result.ok and "joystick" in result.message


def test_adb_failure_surfaces():
    adb = FakeAdb(fail=True)
    result = run(adb, "game.tap_button", {"button": "ultimate"})
    assert not result.ok


# ------------------------------------------------------------- registrasi

@pytest.mark.parametrize("action", [
    "game.tap_button", "game.hold_button", "game.aim_skill", "game.move", "game.combo",
])
def test_actions_registered_in_game_category(action):
    spec = get_spec(action)
    assert spec is not None and spec.category == "game"


def test_all_directions_have_sane_angles():
    assert set(DIRECTIONS) >= {"kanan", "kiri", "atas", "bawah"}
    assert DIRECTIONS["kanan"] == 0
    assert DIRECTIONS["bawah"] == 90                 # y bertambah ke bawah di layar
