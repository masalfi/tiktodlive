"""Pemantau device ADB.

Kenapa perlu: scrcpy hanya untuk mirroring, sedangkan semua aksi (tap,
reboot, dll) lewat adb. Ketika sebuah rule me-reboot HP, dua hal terjadi:

  1. Device hilang dari `adb devices` selama ~30-60 detik
  2. scrcpy ikut mati karena kehilangan koneksi

Pemantau ini mendeteksi keduanya, menjeda antrian aksi selama device
offline, lalu menyambung ulang dan menjalankan scrcpy lagi saat device
kembali - tanpa perlu klik apa pun.

Untuk device wireless (IP:port), reboot juga memutus adb-over-TCP, jadi
`adb connect` dicoba berkala sampai berhasil.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QThread, Signal

from app.i18n import tr
log = logging.getLogger(__name__)

# Status device
ONLINE = "online"
OFFLINE = "offline"
RECONNECTING = "reconnecting"

POLL_INTERVAL = 2.0          # detik antar pengecekan `adb devices`
# Reboot HP biasanya 30-60 detik; beri kelonggaran sebelum menyerah.
RECONNECT_TIMEOUT = 240.0


class DeviceWatcher(QThread):
    """Memantau satu device dan memancarkan perubahan statusnya."""

    state_changed = Signal(str, str)      # status, pesan
    device_lost = Signal(str)             # serial
    device_back = Signal(str)             # serial

    def __init__(self, adb, serial: str = "") -> None:
        super().__init__()
        self.adb = adb
        self.serial = serial
        self._stop = False
        self._state = ONLINE
        self._lost_at = 0.0
        self._last_connect_try = 0.0

    @property
    def state(self) -> str:
        return self._state

    def set_serial(self, serial: str) -> None:
        """Ganti device yang dipantau (mis. setelah pindah ke wireless)."""
        self.serial = serial
        self._state = ONLINE
        self._lost_at = 0.0

    def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------- logika

    def _is_present(self) -> bool:
        """Apakah device target ada dan siap dipakai?"""
        try:
            devices = self.adb.list_devices()
        except Exception:                           # noqa: BLE001
            return False
        if not devices:
            return False
        if not self.serial:
            # Tanpa serial spesifik, cukup ada satu device siap.
            return any(d.get("state") == "device" for d in devices)
        for device in devices:
            if device.get("serial") == self.serial:
                # "unauthorized"/"offline" berarti belum siap dipakai.
                return device.get("state") == "device"
        return False

    def _try_reconnect_wireless(self) -> bool:
        """Untuk device wireless, adb connect perlu diulang setelah reboot."""
        if ":" not in (self.serial or ""):
            return False
        now = time.time()
        # Jangan spam; cukup tiap ~3 detik.
        if now - self._last_connect_try < 3.0:
            return False
        self._last_connect_try = now
        try:
            proc = self.adb.run(["connect", self.serial], timeout=10)
        except Exception:                           # noqa: BLE001
            return False
        output = ((proc.stdout or "") + (proc.stderr or "")).lower()
        return "connected to" in output

    def run(self) -> None:
        while not self._stop:
            present = self._is_present()

            if present and self._state != ONLINE:
                # Device kembali.
                waited = time.time() - self._lost_at if self._lost_at else 0
                self._state = ONLINE
                self.state_changed.emit(
                    ONLINE, f"Device kembali online setelah {waited:.0f} detik"
                )
                self.device_back.emit(self.serial)

            elif not present and self._state == ONLINE:
                # Device baru saja hilang.
                self._state = OFFLINE
                self._lost_at = time.time()
                self.state_changed.emit(
                    OFFLINE, tr("Device terputus (reboot atau kabel lepas). Aksi dijeda.")
                )
                self.device_lost.emit(self.serial)

            elif not present and self._state in (OFFLINE, RECONNECTING):
                elapsed = time.time() - self._lost_at
                if elapsed > RECONNECT_TIMEOUT:
                    if self._state != RECONNECTING:
                        pass
                    self._state = OFFLINE
                    self.state_changed.emit(
                        OFFLINE,
                        tr("Device belum kembali setelah 4 menit. "
                           "Colok kabel USB, atau sambungkan lagi lewat tab Wireless."),
                    )
                    self._lost_at = time.time()     # jangan spam pesan ini
                else:
                    if self._state != RECONNECTING:
                        self._state = RECONNECTING
                        self.state_changed.emit(RECONNECTING, "Menunggu device kembali...")
                    self._try_reconnect_wireless()

            # Tidur bertahap supaya stop() cepat direspons.
            deadline = time.time() + POLL_INTERVAL
            while time.time() < deadline and not self._stop:
                time.sleep(0.1)
