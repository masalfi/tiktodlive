"""Test antrian aksi, safety gate, dan registry."""

import time

import pytest

from app.actions.base import ActionSpec, ParamSpec, REGISTRY, HANDLERS, coerce_params, register
from app.engine.queue import ActionQueue
from app.engine.safety import SafetyGate
from app.models import Action, ActionResult, LiveEvent, Rule


@pytest.fixture
def fake_actions():
    """Daftarkan aksi palsu untuk tes, lalu bersihkan lagi."""
    calls = []

    def handler(ctx, params):
        calls.append(params)
        return ActionResult("test.ok", True, "ok")

    def failing(ctx, params):
        return ActionResult("test.fail", False, "sengaja gagal")

    def boom(ctx, params):
        raise RuntimeError("meledak")

    def danger(ctx, params):
        calls.append(("danger", params))
        return ActionResult("adb.reboot", True, "reboot")

    register(ActionSpec("test.ok", "OK", "adb", [ParamSpec("x", "X", "int", 1)]), handler)
    register(ActionSpec("test.fail", "Fail", "adb"), failing)
    register(ActionSpec("test.boom", "Boom", "adb"), boom)
    register(ActionSpec("adb.reboot", "Reboot", "adb", dangerous=True), danger)
    yield calls
    for t in ("test.ok", "test.fail", "test.boom", "adb.reboot"):
        REGISTRY.pop(t, None)
        HANDLERS.pop(t, None)


def make_queue(safety=None, max_queue=50):
    q = ActionQueue(adb_executor=object(), host_executor=object(),
                    safety=safety or SafetyGate(), max_queue=max_queue)
    return q


def run_job(q, rule, event=None, timeout=3.0):
    """Jalankan satu job dan kumpulkan hasilnya."""
    results = []
    q.on_result = lambda job, i, r: results.append(r)
    q.start()
    q.submit(rule, event or LiveEvent(kind="gift"))
    deadline = time.time() + timeout
    while time.time() < deadline and q.pending() > 0:
        time.sleep(0.02)
    time.sleep(0.2)
    q.stop()
    return results


# ------------------------------------------------------------ coerce_params

def test_coerce_applies_defaults_and_types():
    register(ActionSpec("tmp.c", "C", "adb", [
        ParamSpec("n", "N", "int", 7),
        ParamSpec("f", "F", "float", 1.5),
        ParamSpec("b", "B", "bool", False),
        ParamSpec("s", "S", "str", "hi"),
    ]), lambda c, p: ActionResult("tmp.c", True))
    out = coerce_params("tmp.c", {"n": "42", "b": "true"})
    assert out == {"n": 42, "f": 1.5, "b": True, "s": "hi"}
    REGISTRY.pop("tmp.c"); HANDLERS.pop("tmp.c")


def test_coerce_bad_value_falls_back_to_default():
    register(ActionSpec("tmp.d", "D", "adb", [ParamSpec("n", "N", "int", 9)]),
             lambda c, p: ActionResult("tmp.d", True))
    assert coerce_params("tmp.d", {"n": "bukan angka"}) == {"n": 9}
    REGISTRY.pop("tmp.d"); HANDLERS.pop("tmp.d")


# --------------------------------------------------------------- safety

def test_panic_blocks_actions():
    gate = SafetyGate()
    assert gate.check_action("adb.tap")[0]
    gate.panic()
    ok, reason = gate.check_action("adb.tap")
    assert not ok and "PANIC" in reason
    gate.resume()
    assert gate.check_action("adb.tap")[0]


def test_reboot_hard_cap():
    gate = SafetyGate(reboot_max_per_hour=2)
    for _ in range(2):
        assert gate.check_action("adb.reboot")[0]
        gate.note_action("adb.reboot")
    ok, reason = gate.check_action("adb.reboot")
    assert not ok and "reboot" in reason
    # Aksi lain tetap boleh jalan.
    assert gate.check_action("adb.tap")[0]


def test_reboot_cap_does_not_affect_other_actions():
    gate = SafetyGate(reboot_max_per_hour=1)
    gate.note_action("adb.reboot")
    assert not gate.check_action("adb.reboot")[0]
    assert gate.check_action("adb.shell")[0]


# ---------------------------------------------------------------- queue

def test_queue_runs_actions_in_order(fake_actions):
    q = make_queue()
    rule = Rule(name="r", actions=[
        Action("test.ok", {"x": 1}), Action("test.ok", {"x": 2}), Action("test.ok", {"x": 3}),
    ])
    results = run_job(q, rule)
    assert len(results) == 3
    assert all(r.ok for r in results)
    assert [c["x"] for c in fake_actions] == [1, 2, 3]


def test_queue_continues_after_failed_action(fake_actions):
    q = make_queue()
    rule = Rule(name="r", actions=[Action("test.fail"), Action("test.ok", {"x": 1})])
    results = run_job(q, rule)
    assert len(results) == 2
    assert results[0].ok is False and results[1].ok is True


def test_queue_survives_exception_in_handler(fake_actions):
    q = make_queue()
    rule = Rule(name="r", actions=[Action("test.boom"), Action("test.ok", {"x": 1})])
    results = run_job(q, rule)
    assert len(results) == 2
    assert not results[0].ok and "meledak" in results[0].message
    assert results[1].ok


def test_unknown_action_type_reported(fake_actions):
    q = make_queue()
    rule = Rule(name="r", actions=[Action("tidak.ada"), Action("test.ok", {"x": 1})])
    results = run_job(q, rule)
    assert not results[0].ok and "tidak dikenal" in results[0].message
    assert results[1].ok


def test_panic_mid_job_stops_remaining_actions(fake_actions):
    """PANIC ditekan saat rangkaian aksi sedang berjalan -> sisanya batal."""
    gate = SafetyGate()
    q = make_queue(safety=gate)
    results = []

    def on_result(job, i, r):
        results.append(r)
        gate.panic()          # tekan PANIC tepat setelah aksi pertama selesai

    q.on_result = on_result
    rule = Rule(name="r", actions=[
        Action("test.ok", {"x": 1}), Action("test.ok", {"x": 2}), Action("test.ok", {"x": 3}),
    ])
    q.start()
    q.submit(rule, LiveEvent(kind="gift"))
    time.sleep(0.5)
    q.stop()

    # Aksi 1 jalan, aksi 2 ditolak gate, aksi 3 tidak pernah dicoba.
    assert len(results) == 2
    assert results[0].ok
    assert not results[1].ok and "PANIC" in results[1].message
    assert [c["x"] for c in fake_actions] == [1]


def test_submit_rejected_when_panic():
    gate = SafetyGate()
    gate.panic()
    q = make_queue(safety=gate)
    ok, reason = q.submit(Rule(name="r"), LiveEvent(kind="gift"))
    assert not ok and "PANIC" in reason


def test_submit_rejected_when_queue_full():
    q = make_queue(max_queue=2)
    rule = Rule(name="r", actions=[Action("test.ok")])
    assert q.submit(rule, LiveEvent(kind="gift"))[0]
    assert q.submit(rule, LiveEvent(kind="gift"))[0]
    ok, reason = q.submit(rule, LiveEvent(kind="gift"))
    assert not ok and "penuh" in reason


def test_clear_empties_queue():
    q = make_queue()
    rule = Rule(name="r", actions=[Action("test.ok")])
    for _ in range(5):
        q.submit(rule, LiveEvent(kind="gift"))
    assert q.clear() == 5
    assert q.pending() == 0


def test_dangerous_action_requires_confirm(fake_actions):
    q = make_queue()
    q.confirm_handler = lambda rule, action_type: False      # user menolak
    rule = Rule(name="r", require_confirm=True,
                actions=[Action("adb.reboot"), Action("test.ok", {"x": 1})])
    results = run_job(q, rule)
    assert len(results) == 1
    assert not results[0].ok and "Dibatalkan" in results[0].message
    assert fake_actions == []


def test_dangerous_action_runs_when_confirmed(fake_actions):
    q = make_queue()
    q.confirm_handler = lambda rule, action_type: True
    rule = Rule(name="r", require_confirm=True, actions=[Action("adb.reboot")])
    results = run_job(q, rule)
    assert len(results) == 1 and results[0].ok
    assert fake_actions and fake_actions[0][0] == "danger"


def test_no_confirm_needed_when_rule_does_not_require(fake_actions):
    q = make_queue()
    rule = Rule(name="r", require_confirm=False, actions=[Action("adb.reboot")])
    results = run_job(q, rule)
    assert results[0].ok
