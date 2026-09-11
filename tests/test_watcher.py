"""Test pemantau device: siklus reboot tanpa perlu device sungguhan."""

import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.engine.queue import ActionQueue
from app.engine.safety import SafetyGate
from app.models import Action, LiveEvent, Rule
from app.scrcpy import watcher as watcher_mod
from app.scrcpy.watcher import OFFLINE, ONLINE, RECONNECTING, DeviceWatcher


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeAdb:
    """adb tiruan yang bisa dibuat 'hilang' seperti saat HP reboot."""

    def __init__(self, serial="emulator-5554", present=True):
        self.serial = serial
        self.present = present
        self.connect_calls = []

    def list_devices(self):
        if not self.present:
            return []
        return [{"serial": self.serial, "state": "device", "model": "test"}]

    def run(self, args, timeout=None):
        if args and args[0] == "connect":
            self.connect_calls.append(args[1])
            # Berhasil hanya kalau device memang sudah kembali.
            out = f"connected to {args[1]}" if self.present else "unable to connect"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def drain(qapp, seconds=1.0):
    """Jalankan event loop Qt supaya signal dari thread tersampaikan."""
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)


@pytest.fixture
def fast_poll(monkeypatch):
    """Percepat polling supaya test tidak lama."""
    monkeypatch.setattr(watcher_mod, "POLL_INTERVAL", 0.1)


# ------------------------------------------------------------- deteksi

def test_detects_device_lost_and_back(qapp, fast_poll):
    """Inti fitur: reboot terdeteksi, lalu device kembali."""
    adb = FakeAdb()
    w = DeviceWatcher(adb, "emulator-5554")
    events = []
    w.state_changed.connect(lambda s, m: events.append(s))
    w.device_lost.connect(lambda s: events.append("LOST"))
    w.device_back.connect(lambda s: events.append("BACK"))

    w.start()
    drain(qapp, 0.4)
    assert w.state == ONLINE

    adb.present = False                  # HP mulai reboot
    drain(qapp, 0.8)
    assert "LOST" in events
    assert w.state in (OFFLINE, RECONNECTING)

    adb.present = True                   # HP selesai boot
    drain(qapp, 0.8)
    assert "BACK" in events
    assert w.state == ONLINE

    w.stop(); w.wait(2000)


def test_unauthorized_device_counts_as_offline(qapp, fast_poll):
    """Device 'unauthorized' belum bisa dipakai - jangan dianggap online."""
    adb = FakeAdb()
    adb.list_devices = lambda: [{"serial": "emulator-5554", "state": "unauthorized"}]
    w = DeviceWatcher(adb, "emulator-5554")
    lost = []
    w.device_lost.connect(lambda s: lost.append(s))
    w.start(); drain(qapp, 0.6)
    assert lost
    w.stop(); w.wait(2000)


def test_other_device_does_not_count(qapp, fast_poll):
    """Device lain yang tersambung tidak boleh dianggap device kita."""
    adb = FakeAdb(serial="hp-lain")
    w = DeviceWatcher(adb, "emulator-5554")
    lost = []
    w.device_lost.connect(lambda s: lost.append(s))
    w.start(); drain(qapp, 0.6)
    assert lost
    w.stop(); w.wait(2000)


def test_wireless_reconnect_attempted(qapp, fast_poll, monkeypatch):
    """Device wireless perlu 'adb connect' ulang setelah reboot."""
    monkeypatch.setattr(watcher_mod, "POLL_INTERVAL", 0.1)
    adb = FakeAdb(serial="192.168.1.5:5555")
    w = DeviceWatcher(adb, "192.168.1.5:5555")
    w._last_connect_try = 0.0
    w.start(); drain(qapp, 0.3)

    adb.present = False
    drain(qapp, 1.2)
    assert adb.connect_calls, "adb connect tidak pernah dicoba untuk device wireless"
    assert adb.connect_calls[0] == "192.168.1.5:5555"
    w.stop(); w.wait(2000)


def test_usb_device_does_not_call_connect(qapp, fast_poll):
    """Device USB tidak butuh 'adb connect' - jangan panggil sia-sia."""
    adb = FakeAdb(serial="emulator-5554")
    w = DeviceWatcher(adb, "emulator-5554")
    w.start(); drain(qapp, 0.3)
    adb.present = False
    drain(qapp, 0.8)
    assert adb.connect_calls == []
    w.stop(); w.wait(2000)


def test_adb_error_treated_as_offline(qapp, fast_poll):
    """Kalau adb error, jangan crash - anggap device offline."""
    adb = FakeAdb()
    def boom():
        raise OSError("adb mati")
    adb.list_devices = boom
    w = DeviceWatcher(adb, "emulator-5554")
    lost = []
    w.device_lost.connect(lambda s: lost.append(s))
    w.start(); drain(qapp, 0.6)
    assert lost
    w.stop(); w.wait(2000)


# ---------------------------------------------------- jeda antrian aksi

def test_adb_actions_blocked_while_device_offline():
    gate = SafetyGate()
    gate.set_device_ready(False)
    ok, reason = gate.check_action("adb.tap")
    assert not ok and "offline" in reason


def test_host_actions_still_allowed_while_offline():
    """Overlay & suara tidak butuh device, jadi tetap boleh jalan."""
    gate = SafetyGate()
    gate.set_device_ready(False)
    assert gate.check_action("host.overlay")[0]
    assert gate.check_action("host.sound")[0]


def test_device_ready_does_not_override_panic():
    """Device kembali online TIDAK boleh membatalkan PANIC dari user."""
    gate = SafetyGate()
    gate.panic()
    gate.set_device_ready(True)
    ok, reason = gate.check_action("adb.tap")
    assert not ok and "PANIC" in reason


def test_panic_resume_does_not_override_offline():
    """Sebaliknya: resume PANIC tidak membuat device offline jadi siap."""
    gate = SafetyGate()
    gate.set_device_ready(False)
    gate.panic()
    gate.resume()
    ok, reason = gate.check_action("adb.tap")
    assert not ok and "offline" in reason


def test_queue_rejects_adb_rule_when_offline():
    gate = SafetyGate()
    gate.set_device_ready(False)
    q = ActionQueue(object(), object(), gate)
    rule = Rule(name="r", actions=[Action("adb.tap", {"x": 1, "y": 1})])
    ok, reason = q.submit(rule, LiveEvent(kind="gift"))
    assert not ok and "offline" in reason


def test_queue_accepts_host_only_rule_when_offline():
    """Rule yang hanya memakai overlay tetap jalan walau HP reboot."""
    gate = SafetyGate()
    gate.set_device_ready(False)
    q = ActionQueue(object(), object(), gate)
    rule = Rule(name="r", actions=[Action("host.overlay", {"title": "hai"})])
    assert q.submit(rule, LiveEvent(kind="gift"))[0]


# ------------------------------------------ restart scrcpy setelah reboot

def test_restart_candidates_deduplicated():
    """Serial dari signal dan serial adb aktif biasanya sama - jangan
    menjalankan scrcpy dua kali (jendela ganda)."""
    from app.scrcpy.bridge import ScrcpyOptions
    from app.scrcpy.runner import ScrcpyRunner

    runner = ScrcpyRunner()
    runner._last["emulator-5554"] = ("/x", ScrcpyOptions(), "emulator-5554", "")

    signal_serial = "emulator-5554"
    adb_serial = "emulator-5554"
    candidates = list(dict.fromkeys(
        s for s in (signal_serial, adb_serial) if s and runner.was_running(s)
    ))
    assert candidates == ["emulator-5554"]


def test_restart_falls_back_to_default_key():
    """Kalau scrcpy dijalankan tanpa serial, tetap bisa di-restart."""
    from app.scrcpy.bridge import ScrcpyOptions
    from app.scrcpy.runner import ScrcpyRunner

    runner = ScrcpyRunner()
    runner._last["_default"] = ("/x", ScrcpyOptions(), "", "")
    assert runner.was_running("")
    assert not runner.was_running("emulator-5554")
