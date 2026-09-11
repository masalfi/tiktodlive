"""Pengaman: kill switch global + hard cap aksi berbahaya.

Hard cap di sini TIDAK bisa dilewati oleh konfigurasi rule - ini lapisan
terakhir supaya live tidak hancur karena salah setting.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SafetyGate:
    """Kill switch dan pembatas aksi berbahaya, aman lintas thread."""

    def __init__(self, reboot_max_per_hour: int = 2) -> None:
        self._lock = threading.Lock()
        self._armed = True                      # True = aksi boleh jalan (kendali user)
        self._device_ready = True               # False = device offline (otomatis)
        self.reboot_max_per_hour = reboot_max_per_hour
        self._reboot_times: deque[float] = deque()

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._armed

    def panic(self) -> None:
        """Hentikan semua aksi sampai resume() dipanggil."""
        with self._lock:
            self._armed = False

    def resume(self) -> None:
        with self._lock:
            self._armed = True

    @property
    def device_ready(self) -> bool:
        with self._lock:
            return self._device_ready

    def set_device_ready(self, ready: bool) -> None:
        """Dipanggil pemantau device. Terpisah dari PANIC: device yang
        kembali online tidak boleh membatalkan PANIC yang ditekan user."""
        with self._lock:
            self._device_ready = ready

    def check_action(self, action_type: str) -> tuple[bool, str]:
        """Cek apakah satu aksi boleh dijalankan sekarang."""
        with self._lock:
            if not self._armed:
                return False, "PANIC aktif - semua aksi dihentikan"

            # Aksi ADB butuh device; aksi host (overlay/suara) tetap boleh.
            if not self._device_ready and action_type.startswith("adb."):
                return False, "device offline (mungkin sedang reboot) - aksi dijeda"

            if action_type == "adb.reboot":
                now = time.time()
                while self._reboot_times and now - self._reboot_times[0] > 3600:
                    self._reboot_times.popleft()
                if len(self._reboot_times) >= self.reboot_max_per_hour:
                    return False, (
                        f"batas keamanan reboot tercapai "
                        f"({self.reboot_max_per_hour}/jam)"
                    )
        return True, ""

    def note_action(self, action_type: str) -> None:
        """Catat aksi berbahaya yang benar-benar dijalankan."""
        if action_type == "adb.reboot":
            with self._lock:
                self._reboot_times.append(time.time())

    def reboot_count_last_hour(self) -> int:
        with self._lock:
            now = time.time()
            while self._reboot_times and now - self._reboot_times[0] > 3600:
                self._reboot_times.popleft()
            return len(self._reboot_times)
