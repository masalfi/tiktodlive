"""Audit menyeluruh: aksi, parameter, dan rule bawaan.

Ini menjaga hal-hal yang mudah lolos dari perhatian: parameter yang tidak
pernah dibaca handler, rule yang menyebut tombol tak terkalibrasi,
placeholder salah ketik, atau efek layar-penuh yang dikirim ke Browser
Source kecil di pojok.
"""

import inspect
import re
from pathlib import Path

import pytest

import app.actions.adb as adb_mod
import app.actions.apps as apps_mod
import app.actions.game as game_mod
import app.actions.host as host_mod
from app.actions.adb import register_adb_actions
from app.actions.apps import register_app_actions
from app.actions.base import HANDLERS, REGISTRY, get_spec, grouped_specs
from app.actions.game import register_game_actions
from app.actions.host import register_host_actions
from app.config import active_profile, load_rules
from app.engine.rules import COMMON_CONDITIONS, CONDITION_SPECS
from app.engine.template import context_from_event
from app.models import LiveEvent

@pytest.fixture(autouse=True)
def _fresh_registry():
    """Daftarkan ulang sebelum tiap test.

    Test lain ada yang mengganti aksi sementara; audit harus memeriksa
    pendaftaran yang sebenarnya, bukan sisa milik test sebelumnya.
    """
    for register in (register_adb_actions, register_app_actions,
                     register_game_actions, register_host_actions):
        register()

MODULES = {"adb": adb_mod, "app": apps_mod, "game": game_mod,
           "overlay": host_mod, "host": host_mod}

PLACEHOLDERS = set(context_from_event(LiveEvent(kind="gift")))

# Efek yang memenuhi layar tidak boleh dikirim ke Browser Source notifikasi
# yang biasanya kecil dan diletakkan di pojok.
FULLSCREEN = {"overlay.rain", "overlay.confetti", "overlay.shake", "overlay.flash"}
NOTIF = {"host.overlay", "host.overlay_sound"}
MUSIC = {"host.overlay_music"}
EXPECTED_CHANNEL = (
    {t: "efek" for t in FULLSCREEN}
    | {t: "alert" for t in NOTIF}
    | {t: "musik" for t in MUSIC}
)


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture(scope="module")
def profile():
    return active_profile()


@pytest.fixture(scope="module")
def button_names(profile):
    return set(profile.get("buttons") or {}) | set(profile.get("aliases") or {})


# ----------------------------------------------------------- pendaftaran

def test_every_action_has_a_handler():
    missing = [t for t in REGISTRY if t not in HANDLERS]
    assert not missing, f"aksi tanpa handler: {missing}"


def test_every_param_is_read_by_its_handler():
    """Parameter yang tidak pernah dibaca = kolom yang tidak berpengaruh."""
    unused = []
    for action_type, spec in REGISTRY.items():
        module = MODULES.get(spec.category)
        if module is None:
            continue
        source = inspect.getsource(module)
        for param in spec.params:
            pattern = rf'''get\(\s*["']{re.escape(param.name)}["']'''
            if not re.search(pattern, source):
                unused.append(f"{action_type}.{param.name}")
    assert not unused, f"parameter tidak pernah dibaca: {unused}"


def test_choice_defaults_are_valid():
    """Nilai bawaan di luar daftar pilihan membuat combo terlihat kosong."""
    bad = []
    for action_type, spec in REGISTRY.items():
        for param in spec.params:
            if param.kind == "choice" and param.default not in param.choices:
                bad.append(f"{action_type}.{param.name}={param.default!r}")
    assert not bad, bad


def test_no_duplicate_labels_within_a_group():
    """Dua aksi bernama sama dalam satu kelompok mustahil dibedakan."""
    for title, specs in grouped_specs():
        labels = [s.label for s in specs]
        duplicates = {x for x in labels if labels.count(x) > 1}
        assert not duplicates, f"{title}: label ganda {duplicates}"


# ----------------------------------------------------- rule vs spesifikasi

def test_rules_use_registered_actions(rules):
    unknown = [
        (r.name, a.type) for r in rules for a in r.actions if get_spec(a.type) is None
    ]
    assert not unknown, f"aksi tidak terdaftar: {unknown}"


def test_rules_have_no_unknown_params(rules):
    """Parameter salah ketik diam-diam diabaikan saat rule dijalankan."""
    bad = []
    for rule in rules:
        for action in rule.actions:
            spec = get_spec(action.type)
            known = {p.name for p in spec.params}
            for key in action.params:
                if key not in known:
                    bad.append(f"[{rule.name}] {action.type}.{key}")
    assert not bad, bad


def test_rule_choice_values_are_valid(rules):
    bad = []
    for rule in rules:
        for action in rule.actions:
            for param in get_spec(action.type).params:
                if param.kind != "choice" or param.name not in action.params:
                    continue
                value = str(action.params[param.name])
                if value and value not in param.choices:
                    bad.append(f"[{rule.name}] {param.name}={value!r}")
    assert not bad, bad


def test_rule_conditions_match_their_event(rules):
    """min_coins pada event komentar tidak akan pernah cocok."""
    bad = []
    for rule in rules:
        valid = ({n for n, _, _ in CONDITION_SPECS.get(rule.event_kind, [])}
                 | {n for n, _, _ in COMMON_CONDITIONS})
        for name in rule.conditions:
            if name not in valid:
                bad.append(f"[{rule.name}] '{name}' untuk event {rule.event_kind}")
    assert not bad, bad


def test_rule_placeholders_are_known(rules):
    bad = []
    for rule in rules:
        for action in rule.actions:
            for value in action.params.values():
                if not isinstance(value, str):
                    continue
                for name in re.findall(r"\{(\w+)\}", value):
                    if name not in PLACEHOLDERS:
                        bad.append(f"[{rule.name}] {{{name}}}")
    assert not bad, f"placeholder tidak dikenal: {bad} (tersedia: {sorted(PLACEHOLDERS)})"


def test_rule_game_buttons_exist(rules, button_names):
    """Tombol yang tidak ada di profil = rule menekan tempat kosong."""
    bad = []
    for rule in rules:
        for action in rule.actions:
            if not action.type.startswith("game."):
                continue
            names = []
            if "button" in action.params:
                names.append(str(action.params["button"]))
            if "buttons" in action.params:
                names += [x.strip() for x in str(action.params["buttons"]).split(",") if x.strip()]
            for name in names:
                if name and name not in button_names:
                    bad.append(f"[{rule.name}] tombol '{name}'")
    assert not bad, f"{bad} (tersedia: {sorted(button_names)})"


# --------------------------------------------------------------- keamanan

def test_dangerous_actions_require_confirmation(rules):
    bad = [
        f"[{r.name}] {a.type}"
        for r in rules for a in r.actions
        if get_spec(a.type).dangerous and not r.require_confirm
    ]
    assert not bad, f"aksi berbahaya tanpa konfirmasi: {bad}"


def test_dangerous_rules_have_cooldown(rules):
    bad = [
        f"[{r.name}] cooldown={r.cooldown_sec}s"
        for r in rules for a in r.actions
        if get_spec(a.type).dangerous and r.cooldown_sec < 10
    ]
    assert not bad, bad


# ------------------------------------------------------------- konsistensi

def test_overlay_channels_are_consistent(rules):
    """Confetti di Browser Source notifikasi yang kecil akan terpotong."""
    bad = []
    for rule in rules:
        for action in rule.actions:
            expected = EXPECTED_CHANNEL.get(action.type)
            if expected is None:
                continue
            actual = str(action.params.get("channel") or "")
            if actual != expected:
                bad.append(f"[{rule.name}] {action.type} -> "
                           f"'{actual or '(utama)'}', seharusnya '{expected}'")
    assert not bad, bad


def test_rule_names_match_their_actions(rules):
    """Nama rule yang menjanjikan sesuatu tapi aksinya tidak ada akan
    membuat pengguna mengira fiturnya rusak."""
    promises = {
        "musik": {"host.overlay_music"},
        "confetti": {"overlay.confetti"},
        "hujan": {"overlay.rain"},
        "getar": {"overlay.shake"},
        "reboot": {"adb.reboot"},
        "combo": {"game.combo"},
    }
    bad = []
    for rule in rules:
        types = {a.type for a in rule.actions}
        lowered = rule.name.lower()
        for word, expected in promises.items():
            if word in lowered and not (expected & types):
                bad.append(f"[{rule.name}] menyebut '{word}'")
    assert not bad, bad


def test_no_rule_without_actions(rules):
    assert not [r.name for r in rules if not r.actions]


def test_rule_ids_unique(rules):
    ids = [r.id for r in rules]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"id ganda: {duplicates}"


# --------------------------------------------------- kesiapan rule aktif

def test_enabled_rules_have_the_files_they_need(rules):
    """Rule aktif yang menunjuk berkas kosong akan gagal saat live."""
    bad = []
    for rule in rules:
        if not rule.enabled:
            continue
        for action in rule.actions:
            if action.type == "overlay.rain" and action.params.get("sumber") != "gambar":
                continue
            if action.type == "host.overlay_music" and action.params.get("action") != "play":
                continue
            for param in get_spec(action.type).params:
                if param.kind != "file" or param.name not in action.params:
                    continue
                value = str(action.params[param.name] or "").strip()
                if not value:
                    bad.append(f"[{rule.name}] {action.type}.{param.name} kosong")
                elif not Path(value).expanduser().exists():
                    bad.append(f"[{rule.name}] berkas hilang: {value}")
    assert not bad, bad


def test_enabled_game_rules_need_calibrated_profile(rules, profile):
    if profile.get("calibrated"):
        pytest.skip("profil sudah dikalibrasi")
    bad = [r.name for r in rules
           if r.enabled and any(a.type.startswith("game.") for a in r.actions)]
    assert not bad, f"rule game aktif tapi profil belum dikalibrasi: {bad}"
