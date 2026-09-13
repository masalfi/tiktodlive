"""Menjalankan & memantau proses scrcpy."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from app.scrcpy.bridge import ScrcpyOptions, build_args

from app.i18n import tr
log = logging.getLogger(__name__)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class ScrcpyRunner:
    """Satu proses scrcpy per device, dilacak supaya bisa dihentikan."""

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}
        # Konfigurasi terakhir per device, dipakai untuk menjalankan ulang
        # otomatis setelah device reboot.
        self._last: dict[str, tuple[str, ScrcpyOptions, str, str]] = {}

    def is_running(self, serial: str = "") -> bool:
        proc = self._procs.get(serial or "_default")
        return proc is not None and proc.poll() is None

    def running_serials(self) -> list[str]:
        return [s for s, p in self._procs.items() if p.poll() is None]

    def start(
        self,
        scrcpy_path: str,
        options: ScrcpyOptions,
        serial: str = "",
        adb_path: str = "",
    ) -> tuple[bool, str]:
        """Jalankan scrcpy. Kembalikan (berhasil, pesan)."""
        if not scrcpy_path:
            return False, tr("scrcpy belum tersedia. Klik 'Unduh scrcpy' dulu.")

        key = serial or "_default"
        if self.is_running(key):
            return False, tr("scrcpy sudah berjalan untuk device ini.")

        cmd = [scrcpy_path] + build_args(options, serial)

        env = None
        if adb_path:
            # scrcpy memakai adb dari PATH; arahkan ke adb yang sama dengan
            # aplikasi supaya tidak bentrok versi.
            import os

            env = dict(os.environ)
            env["ADB"] = adb_path

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
                env=env,
            )
        except OSError as exc:
            return False, tr("Gagal menjalankan scrcpy: {sebab}", sebab=exc)

        # Kalau langsung mati, ambil pesan errornya supaya user tahu sebabnya.
        try:
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            self._procs[key] = proc
            self._last[key] = (scrcpy_path, options, serial, adb_path)
            return True, "scrcpy berjalan."

        output = ""
        if proc.stdout is not None:
            try:
                output = proc.stdout.read().decode(errors="replace").strip()
            except Exception:                       # noqa: BLE001
                pass
        tail = output.splitlines()[-3:] if output else []
        return False, "scrcpy berhenti: " + (" | ".join(tail) or f"exit {proc.returncode}")

    def stop(self, serial: str = "") -> bool:
        key = serial or "_default"
        proc = self._procs.get(key)
        # Stop selalu berarti "user tidak mau ini jalan lagi", termasuk saat
        # prosesnya sudah mati duluan - jangan restart otomatis setelahnya.
        self._last.pop(key, None)
        if proc is None or proc.poll() is not None:
            self._procs.pop(key, None)
            return False
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._procs.pop(key, None)
        return True

    def was_running(self, serial: str = "") -> bool:
        """Apakah scrcpy pernah dijalankan untuk device ini?

        Dipakai setelah reboot: hanya jalankan ulang kalau memang tadi
        sedang berjalan, jangan memunculkan jendela yang tak diminta.
        """
        return (serial or "_default") in self._last

    def restart(self, serial: str = "") -> tuple[bool, str]:
        """Jalankan ulang scrcpy dengan konfigurasi terakhir."""
        key = serial or "_default"
        saved = self._last.get(key)
        if saved is None:
            return False, tr("belum pernah dijalankan")
        # Bersihkan proses lama yang sudah mati.
        self._procs.pop(key, None)
        path, options, dev_serial, adb_path = saved
        return self.start(path, options, dev_serial, adb_path)

    def forget(self, serial: str = "") -> None:
        """Lupakan konfigurasi - dipakai saat user menghentikan manual,
        supaya tidak dijalankan ulang otomatis."""
        self._last.pop(serial or "_default", None)

    def stop_all(self) -> int:
        count = 0
        for serial in list(self._procs):
            if self.stop(serial):
                count += 1
        return count
