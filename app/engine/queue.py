"""Antrian aksi serial.

Satu worker thread menjalankan job berurutan, supaya gift bertubi-tubi
tidak membuat aksi saling tumpang tindih di device.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

from app.actions.base import HANDLERS, coerce_params, get_spec
from app.engine.safety import SafetyGate
from app.engine.template import context_from_event, render_params
from app.i18n import tr
from app.models import ActionResult, Job, LiveEvent, Rule

log = logging.getLogger(__name__)

# callback(job, action_index, result)
ResultCallback = Callable[[Job, int, ActionResult], None]
# callback(job, alasan)
DropCallback = Callable[[Job, str], None]
# callback(rule, action_type) -> bool (True = user setuju)
ConfirmCallback = Callable[[Rule, str], bool]


class ActionQueue:
    """Worker thread tunggal yang mengeksekusi rangkaian aksi."""

    def __init__(
        self,
        adb_executor,
        host_executor,
        safety: SafetyGate,
        max_queue: int = 50,
    ) -> None:
        self.adb = adb_executor
        self.host = host_executor
        self.safety = safety
        self.max_queue = max_queue

        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.on_result: ResultCallback | None = None
        self.on_dropped: DropCallback | None = None
        self.on_job_start: Callable[[Job], None] | None = None
        self.confirm_handler: ConfirmCallback | None = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ActionQueue", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._queue.put(None)          # bangunkan worker yang sedang blocking
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    # ---------------------------------------------------------------- enqueue

    def submit(self, rule: Rule, event: LiveEvent) -> tuple[bool, str]:
        """Masukkan job ke antrian. (diterima, alasan_kalau_ditolak)"""
        if not self.safety.armed:
            return False, tr("PANIC aktif")
        if not self.safety.device_ready and any(
            a.type.startswith("adb.") for a in rule.actions
        ):
            return False, tr("device offline - rule dilewati")
        if self._queue.qsize() >= self.max_queue:
            return False, tr("antrian penuh ({maks})", maks=self.max_queue)
        self._queue.put(Job(rule=rule, event=event))
        return True, ""

    def clear(self) -> int:
        """Kosongkan antrian; kembalikan jumlah job yang dibuang."""
        dropped = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            self._queue.task_done()
            if item is not None:
                dropped += 1
        return dropped

    def pending(self) -> int:
        return self._queue.qsize()

    # ----------------------------------------------------------------- worker

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if job is None:
                self._queue.task_done()
                break
            try:
                self._execute(job)
            except Exception:                       # noqa: BLE001 - worker tak boleh mati
                log.exception("Job gagal total: %s", job.rule.name)
            finally:
                self._queue.task_done()

    def _execute(self, job: Job) -> None:
        if self.on_job_start:
            self.on_job_start(job)

        for index, action in enumerate(job.rule.actions):
            if self._stop.is_set():
                return

            # Kill switch dicek per aksi, bukan hanya per job, supaya PANIC
            # menghentikan rangkaian panjang di tengah jalan.
            allowed, reason = self.safety.check_action(action.type)
            if not allowed:
                self._emit(job, index, ActionResult(action.type, False, reason))
                return

            spec = get_spec(action.type)
            if spec is None:
                self._emit(job, index, ActionResult(action.type, False, tr("Tipe aksi tidak dikenal")))
                continue

            # Konfirmasi untuk aksi berbahaya bila rule memintanya.
            if spec.dangerous and job.rule.require_confirm:
                if self.confirm_handler is None:
                    self._emit(job, index, ActionResult(action.type, False, tr("Butuh konfirmasi, tidak ada handler")))
                    return
                if not self.confirm_handler(job.rule, action.type):
                    self._emit(job, index, ActionResult(action.type, False, "Dibatalkan user"))
                    return

            handler = HANDLERS.get(action.type)
            # Placeholder seperti {user}/{gift} diisi dari event pemicu,
            # baru kemudian dikonversi ke tipe sesuai spec.
            rendered = render_params(action.params, context_from_event(job.event))
            params = coerce_params(action.type, rendered)
            target = self.adb if spec.category == "adb" else self.host

            try:
                result = handler(target, params)
            except Exception as exc:                # noqa: BLE001
                log.exception("Aksi %s error", action.type)
                result = ActionResult(action.type, False, f"Error: {exc}")

            if result.ok:
                self.safety.note_action(action.type)

            self._emit(job, index, result)

            if action.delay_after > 0:
                # Tidur bertahap supaya PANIC tetap responsif.
                deadline = time.time() + action.delay_after
                while time.time() < deadline and not self._stop.is_set():
                    time.sleep(min(0.1, deadline - time.time()))

    def _emit(self, job: Job, index: int, result: ActionResult) -> None:
        if self.on_result:
            self.on_result(job, index, result)
