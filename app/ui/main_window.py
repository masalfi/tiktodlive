"""Window utama: menyatukan koneksi TikTok, rule engine, antrian, dan overlay."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QWidget,
)

from app.i18n import tr

from app.actions.adb import AdbExecutor, register_adb_actions
from app.actions.apps import register_app_actions
from app.actions.game import register_game_actions
from app.actions.host import HostExecutor, register_host_actions
from app.config import RulesLoadError, find_adb, load_rules, load_settings, save_rules, save_settings
from app.engine.queue import ActionQueue
from app.engine.rules import RuleEngine
from app.engine.safety import SafetyGate
from app.live.client import STATE_DISCONNECTED, STATE_ERROR, STATE_LIVE, TikTokWorker
from app.live.euler_client import EulerWorker
from app.live.gifts import CATALOG
from app.models import ActionResult, Job, LiveEvent, Rule
from app.overlay.server import OverlayServer
from app.ui.confirm_dialog import ask_confirm
from app.ui.gift_picker import GiftFetchWorker
from app.ui.theme import DANGER, OK, TEXT_DIM
from app.ui.panel_connect import ConnectPanel
from app.ui.gift_icons import ICONS
from app.ui.panel_devices import DevicesPanel
from app.ui.panel_game import GamePanel
from app.ui.panel_home import HomePanel
from app.ui.panel_gifts import GiftsPanel
from app.scrcpy.watcher import OFFLINE, ONLINE, RECONNECTING, DeviceWatcher
from app.ui.panel_scrcpy import ScrcpyPanel
from app.ui.panel_log import LogPanel
from app.ui.panel_overlay import OverlayPanel
from app.ui.panel_rules import RulesPanel
from app.ui.sound import make_sound_player

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    # Hasil dari worker thread harus masuk GUI lewat signal, bukan
    # pemanggilan widget langsung.
    result_ready = Signal(object, int, object)     # Job, index, ActionResult
    job_started = Signal(object)                   # Job

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("TikTok Live Controller"))
        self.resize(940, 620)
        self.setMinimumSize(820, 560)

        register_adb_actions()
        register_host_actions()
        register_game_actions()
        register_app_actions()

        self.settings = load_settings()
        try:
            self.rules: list[Rule] = load_rules()
            self._rules_ok = True
        except RulesLoadError as exc:
            # Jangan menimpa file yang rusak - biarkan user memperbaikinya.
            self.rules = []
            self._rules_ok = False
            self._rules_error = str(exc)

        # --- inti sistem
        adb_cfg = self.settings["adb"]
        self.adb = AdbExecutor(adb_cfg["path"], adb_cfg["serial"], int(adb_cfg["timeout_sec"]))
        self.overlay = OverlayServer(self.settings["overlay"]["host"], int(self.settings["overlay"]["port"]))
        self.host = HostExecutor(self.overlay, self.settings["scrcpy"]["path"])
        self.host.set_sound_player(make_sound_player())

        self.safety = SafetyGate(int(self.settings["safety"]["reboot_max_per_hour"]))
        self.engine = RuleEngine(self.rules)
        self.queue = ActionQueue(self.adb, self.host, self.safety, int(self.settings["safety"]["max_queue"]))
        self.queue.on_result = self._on_result_threadsafe
        self.queue.on_job_start = self.job_started.emit
        self.queue.confirm_handler = self._confirm_threadsafe
        self.queue.start()

        self.worker: TikTokWorker | EulerWorker | None = None
        self._event_count = 0

        # Cache gift dimuat sebelum UI dibangun, supaya tabel & dropdown
        # gift langsung terisi tanpa perlu di-refresh manual.
        self._gift_cache_loaded = CATALOG.load_cache()

        self._build_ui()
        self._wire()

        if self.settings["overlay"]["enabled"]:
            self._start_overlay()

        # Pilih device otomatis kalau belum diset.
        if not self.adb.serial:
            devices = self.adb.list_devices()
            if devices:
                self.adb.set_serial(devices[0]["serial"])
                self.host.adb_serial = self.adb.serial
        self.devices_panel.refresh()

        if not getattr(self, "_rules_ok", True):
            self.log_panel.add_system(
                tr("{sebab} - perbaiki file itu, atau hapus supaya dibuat ulang.", sebab=self._rules_error),
                error=True,
            )

        self._sync_overlay_channels()
        self._sync_game_profile()
        self._install_package_provider()
        self._start_device_watcher()
        self._init_gift_catalog()

        if not self.adb.available:
            self.log_panel.add_system(
                tr("adb tidak ditemukan. Install Android platform-tools, atau isi adb.path di config/settings.yaml."),
                error=True,
            )

    # ------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.connect_panel = ConnectPanel(self.settings)
        self.rules_panel = RulesPanel(self.rules)
        self.devices_panel = DevicesPanel(self.adb, self.queue, self.settings)
        self.game_panel = GamePanel(self.adb, self.queue)
        self.gifts_panel = GiftsPanel()
        self.overlay_panel = OverlayPanel(self.overlay, self.host, self.settings)
        self.scrcpy_panel = ScrcpyPanel(self.adb, self.settings)
        # Aksi rule "Jalankan scrcpy" memakai runner & opsi yang sama
        # dengan tab scrcpy, jadi pengaturannya konsisten.
        self.host.scrcpy_runner = self.scrcpy_panel.runner
        self.host.scrcpy_options = self.scrcpy_panel.options
        self.log_panel = LogPanel()

        # Dibuat setelah panel lain karena memeriksa statusnya.
        self.home_panel = HomePanel(self)
        self.home_panel.open_tab.connect(self._open_tab_by_name)

        self.tabs.addTab(self.home_panel, tr("Mulai"))
        self.tabs.addTab(self.connect_panel, tr("Koneksi"))
        self.tabs.addTab(self.rules_panel, tr("Rules"))
        self.tabs.addTab(self.devices_panel, tr("Devices"))
        self.tabs.addTab(self.scrcpy_panel, "scrcpy")
        self.tabs.addTab(self.game_panel, tr("Game"))
        self.tabs.addTab(self.overlay_panel, tr("Overlay"))
        self.tabs.addTab(self.gifts_panel, tr("Gift"))
        self.tabs.addTab(self.log_panel, tr("Log"))
        self.setCentralWidget(self.tabs)

        # Status bar permanen: status live, antrian, dan tombol PANIC.
        bar = self.statusBar()
        self.status_label = QLabel(tr("Belum terhubung"))
        bar.addWidget(self.status_label, 1)

        self.device_label = QLabel(tr("Device online"))
        self.device_label.setStyleSheet(f"color:{TEXT_DIM};")
        bar.addPermanentWidget(self.device_label)

        self.queue_label = QLabel(tr("Antrian: 0"))
        bar.addPermanentWidget(self.queue_label)

        self.overlay_label = QLabel(tr("Overlay: mati"))
        bar.addPermanentWidget(self.overlay_label)

        self.panic_button = QPushButton(tr("PANIC - HENTIKAN SEMUA"))
        self.panic_button.setCheckable(True)
        self.panic_button.setStyleSheet(
            "QPushButton { background:#c62828; color:white; font-weight:bold; padding:6px 14px; border-radius:4px; }QPushButton:checked { background:#7b1fa2; }"
        )
        bar.addPermanentWidget(self.panic_button)

        # Timer ringan untuk indikator antrian/overlay.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)

    def _open_tab_by_name(self, name: str) -> None:
        """Dipakai tombol di tab Mulai untuk melompat ke tab terkait."""
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                self.tabs.setCurrentIndex(index)
                return

    def _wire(self) -> None:
        self.connect_panel.connect_requested.connect(self._start_live)
        self.connect_panel.disconnect_requested.connect(self._stop_live)
        self.connect_panel.settings_changed.connect(self._save_settings)

        self.rules_panel.rules_changed.connect(self._on_rules_changed)
        self.rules_panel.test_requested.connect(self._test_rule)

        self.devices_panel.serial_changed.connect(self._on_serial_changed)
        self.scrcpy_panel.serial_changed.connect(self._on_wireless_connected)
        self.scrcpy_panel.settings_changed.connect(self._save_settings)
        self.scrcpy_panel.tools_installed.connect(self._on_tools_installed)
        self.overlay_panel.settings_changed.connect(self._save_settings)
        self.game_panel.profile_changed.connect(self._sync_game_profile)

        self.panic_button.toggled.connect(self._on_panic_toggled)

        self.result_ready.connect(self._on_result)
        self.job_started.connect(self._on_job_start)

    # -------------------------------------------------------- pemantau device

    def _start_device_watcher(self) -> None:
        """Pantau device supaya reboot (dari rule atau manual) tertangani."""
        self.watcher = DeviceWatcher(self.adb, self.adb.serial)
        self.watcher.state_changed.connect(self._on_device_state)
        self.watcher.device_lost.connect(self._on_device_lost)
        self.watcher.device_back.connect(self._on_device_back)
        self.watcher.start()

    def _on_device_state(self, state: str, message: str) -> None:
        self.log_panel.add_system(message, error=(state == OFFLINE))
        colors = {ONLINE: OK, RECONNECTING: "#e0a52e", OFFLINE: DANGER}
        labels = {ONLINE: tr("Device online"), RECONNECTING: tr("Device menyambung ulang..."),
                  OFFLINE: tr("Device offline")}
        self.device_label.setText(labels.get(state, state))
        self.device_label.setStyleSheet(f"color:{colors.get(state, TEXT_DIM)};")

    def _on_device_lost(self, serial: str) -> None:
        """Device hilang: jeda aksi ADB dan catat kalau scrcpy tadi jalan."""
        self.safety.set_device_ready(False)
        dropped = self.queue.clear()
        if dropped:
            self.log_panel.add_system(f"{dropped} aksi dibatalkan karena device offline.")

        # scrcpy pasti ikut mati; ingat serial mana yang tadi berjalan supaya
        # bisa dijalankan lagi. Serial dari signal bisa kosong, jadi pakai
        # daftar yang benar-benar tercatat di runner.
        runner = self.scrcpy_panel.runner
        # dict.fromkeys menjaga urutan sekaligus membuang duplikat - serial
        # dari signal dan serial adb aktif biasanya sama.
        candidates = list(dict.fromkeys(
            s for s in (serial, self.adb.serial) if s and runner.was_running(s)
        ))
        if not candidates and runner.was_running(""):
            candidates = [""]
        self._scrcpy_pending = candidates

    def _on_device_back(self, serial: str) -> None:
        """Device kembali: lanjutkan aksi dan hidupkan lagi scrcpy."""
        self.safety.set_device_ready(True)
        self.devices_panel.refresh()

        for pending in getattr(self, "_scrcpy_pending", []):
            ok, message = self.scrcpy_panel.runner.restart(pending)
            self.log_panel.add_system(
                tr("scrcpy dijalankan ulang: {pesan}", pesan=message) if ok
                else tr("Gagal menjalankan ulang scrcpy: {pesan}", pesan=message),
                error=not ok,
            )
        self._scrcpy_pending = []

    # ---------------------------------------------------------- katalog gift

    def _init_gift_catalog(self) -> None:
        """Cache sudah dimuat sebelum UI; di sini hanya urusan penyegaran."""
        self._gift_worker: GiftFetchWorker | None = None

        if self._gift_cache_loaded:
            self.log_panel.add_system(tr("Katalog gift: {n} gift (dari cache)", n=len(CATALOG)))
            if not CATALOG.is_stale:
                return
            self.log_panel.add_system(tr("Katalog gift sudah lama, menyegarkan..."))
        else:
            self.log_panel.add_system("Mengambil daftar gift TikTok...")

        # Ambil di background supaya window tetap responsif.
        self._gift_worker = GiftFetchWorker()
        self._gift_worker.finished_ok.connect(self._on_gifts_fetched)
        self._gift_worker.failed.connect(self._on_gifts_failed)
        self._gift_worker.start()

    def _on_gifts_fetched(self, count: int) -> None:
        self.log_panel.add_system(f"Katalog gift diperbarui: {count} gift")
        self.gifts_panel.reload()

    def _on_gifts_failed(self, message: str) -> None:
        if CATALOG.is_empty:
            self.log_panel.add_system(
                tr("Gagal mengambil daftar gift ({sebab}). Nama gift masih bisa diketik manual di editor rule.",
                   sebab=message),
                error=True,
            )
        else:
            self.log_panel.add_system(tr("Gagal menyegarkan gift, pakai daftar lama ({sebab})", sebab=message))

    def _on_room_gifts(self, added: int) -> None:
        self.log_panel.add_system(tr("{n} gift khusus room ini ditambahkan ke katalog", n=added))
        self.gifts_panel.reload()

    # -------------------------------------------------------------- overlay

    def _start_overlay(self) -> None:
        self.overlay.start()
        if hasattr(self, "overlay_panel"):
            self.overlay_panel.refresh_status()
        if self.overlay.running:
            self.log_panel.add_system(tr("Overlay aktif: {url}", url=self.overlay.url))
        else:
            self.log_panel.add_system(tr("Overlay gagal: {sebab}", sebab=self.overlay.error), error=True)

    # ----------------------------------------------------------------- live

    def _start_live(self, username: str) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not username:
            QMessageBox.warning(self, tr("Username kosong"), tr("Isi username TikTok dulu."))
            return

        self.settings["tiktok"]["username"] = username
        self._save_settings()

        self._event_count = 0
        self.connect_panel.set_event_count(0)

        api_key = self.settings["tiktok"]["sign_api_key"].strip()
        backend = self.settings["tiktok"].get("backend", "auto")
        auto_reconnect = bool(self.settings["tiktok"]["auto_reconnect"])

        # Dengan API key, jalur EulerStream terkelola jauh lebih andal:
        # koneksi langsung lewat TikTokLive sering ditolak (HTTP 400) karena
        # sign server mengalihkan ke fallback proxy berbayar.
        use_euler = (backend == "eulerstream") or (backend == "auto" and bool(api_key))

        if use_euler and not api_key:
            QMessageBox.warning(
                self, tr("Butuh API key"),
                tr("Backend EulerStream memerlukan Sign API key. Isi di tab Koneksi "
                   "atau pilih backend 'tiktoklive'."),
            )
            return

        if use_euler:
            self.worker = EulerWorker(username, api_key, auto_reconnect)
            self.log_panel.add_system(tr("Backend: EulerStream (WebSocket terkelola)"))
        else:
            self.worker = TikTokWorker(username, api_key, auto_reconnect)
            self.log_panel.add_system(tr("Backend: TikTokLive (koneksi langsung)"))
        self.worker.event_received.connect(self._on_live_event)
        self.worker.status_changed.connect(self._on_status)
        self.worker.viewer_count.connect(self.connect_panel.set_viewer_count)
        self.worker.gifts_updated.connect(self._on_room_gifts)
        self.worker.start()
        self.connect_panel.set_connecting()

    def _stop_live(self) -> None:
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
        self.connect_panel.set_state(STATE_DISCONNECTED, "Terputus")

    def _on_status(self, state: str, message: str) -> None:
        self.connect_panel.set_state(state, message)
        self.status_label.setText(message)
        colors = {STATE_LIVE: OK, STATE_ERROR: DANGER}
        self.status_label.setStyleSheet(
            f"color:{colors.get(state, TEXT_DIM)}; font-weight:600;"
        )
        self.log_panel.add_system(message, error=(state == STATE_ERROR))

    # ---------------------------------------------------------------- event

    def _on_live_event(self, event: LiveEvent) -> None:
        """Event masuk dari TikTok -> cocokkan rule -> antrikan aksi."""
        self._event_count += 1
        self.connect_panel.set_event_count(self._event_count)
        self.log_panel.add_event(event)

        passed, blocked = self.engine.match(event)
        for rule, reason in blocked:
            self.log_panel.add_system(tr("[{rule}] dilewati: {sebab}", rule=rule.name, sebab=reason))

        for rule in passed:
            accepted, reason = self.queue.submit(rule, event)
            if accepted:
                self.engine.mark_fired(rule)
            else:
                self.log_panel.add_system(tr("[{rule}] ditolak: {sebab}", rule=rule.name, sebab=reason), error=True)

    def _test_rule(self, rule: Rule) -> None:
        """Test Run: jalankan rule tanpa menunggu event asli."""
        event = LiveEvent(
            kind=rule.event_kind, username="tester", nickname="Tester",
            gift_name="Rose", gift_id=5655, repeat_count=1,
            diamond_count=1, total_coins=1, comment="test", like_count=1,
        )
        accepted, reason = self.queue.submit(rule, event)
        if accepted:
            self.log_panel.add_system(tr("[{rule}] test dijalankan", rule=rule.name))
            self.tabs.setCurrentWidget(self.log_panel)
        else:
            QMessageBox.warning(self, tr("Tidak bisa dijalankan"), reason)

    # --------------------------------------------------------------- result

    def _on_result_threadsafe(self, job: Job, index: int, result: ActionResult) -> None:
        # Dipanggil dari worker thread -> lempar ke GUI thread via signal.
        self.result_ready.emit(job, index, result)

    def _on_job_start(self, job: Job) -> None:
        self.log_panel.add_system(f"[{job.rule.name}] terpicu oleh {job.event.display()}")

    def _on_result(self, job: Job, index: int, result: ActionResult) -> None:
        self.log_panel.add_result(job, index, result)

    def _confirm_threadsafe(self, rule: Rule, action_type: str) -> bool:
        """Dipanggil dari worker thread; ask_confirm menjembatani ke GUI thread."""
        return ask_confirm(self, rule.name, action_type, int(self.settings["safety"]["confirm_timeout_sec"]))

    # ---------------------------------------------------------------- panic

    def _on_panic_toggled(self, checked: bool) -> None:
        if checked:
            self.safety.panic()
            dropped = self.queue.clear()
            self.panic_button.setText(tr("PANIC AKTIF - klik untuk lanjut"))
            self.log_panel.add_system(tr("PANIC aktif. {n} aksi dibatalkan.", n=dropped), error=True)
        else:
            self.safety.resume()
            self.panic_button.setText(tr("PANIC - HENTIKAN SEMUA"))
            self.log_panel.add_system(tr("PANIC dimatikan, aksi berjalan lagi."))

    # --------------------------------------------------------------- lainnya

    def _install_package_provider(self) -> None:
        """Sediakan daftar aplikasi HP untuk dropdown di editor rule.

        Hasilnya di-cache: `pm list packages` butuh beberapa detik lewat
        WiFi dan form bisa dibangun ulang berkali-kali.
        """
        from app.actions.apps import list_packages
        from app.ui.param_form import set_package_provider

        cache: dict[str, list[str]] = {}

        def provider() -> list[str]:
            if "v" not in cache:
                cache["v"] = list_packages(self.adb) if self.adb.available else []
            return cache["v"]

        self._package_cache = cache
        set_package_provider(provider)

    def _sync_game_profile(self) -> None:
        """Aksi game membaca profil lewat adb.game_profile, jadi profil
        yang sedang dipilih harus selalu disalurkan ke sana."""
        self.adb.game_profile = self.game_panel.current_profile()
        self._install_button_provider()

    def _install_button_provider(self) -> None:
        """Sediakan daftar tombol game untuk dropdown di editor rule.

        Tanpa ini pengguna harus mengetik nama tombol hasil kalibrasi
        dari ingatan.
        """
        from app.ui.param_form import set_button_provider

        def provider() -> list[tuple[str, str]]:
            profile = self.game_panel.current_profile()
            buttons = profile.get("buttons") or {}
            if not buttons:
                return []

            aliases = profile.get("aliases") or {}
            groups = profile.get("groups") or {}

            # Nama umum ditempelkan sebagai keterangan, bukan jadi baris
            # tersendiri - kalau tidak daftarnya penuh duplikat.
            extra: dict[str, list[str]] = {}
            for alias, target in aliases.items():
                extra.setdefault(target, []).append(alias)

            def row(name: str) -> tuple[str, str]:
                names = extra.get(name)
                label = f"{name}  ({', '.join(sorted(names))})" if names else name
                return name, label

            rows: list[tuple[str, str]] = []
            seen: set[str] = set()
            for title, members in groups.items():
                grup = [m for m in members if m in buttons]
                if not grup:
                    continue
                rows.append(("", f"— {title} —"))     # pemisah kelompok
                for name in grup:
                    rows.append(row(name))
                    seen.add(name)
            sisa = [n for n in sorted(buttons) if n not in seen]
            if sisa:
                rows.append(("", "— Lainnya —"))
                rows.extend(row(n) for n in sisa)
            return rows

        set_button_provider(provider)

    def _rule_channels(self) -> list[str]:
        """Channel yang dipakai rule, supaya muncul di dropdown tab Overlay."""
        names = []
        for rule in self.rules:
            for action in rule.actions:
                if not action.type.startswith("host.overlay"):
                    continue
                channel = str(action.params.get("channel") or "").strip()
                if channel and channel not in names:
                    names.append(channel)
        return names

    def _sync_overlay_channels(self) -> None:
        self.overlay_panel.set_rule_channels(self._rule_channels())

    def _on_rules_changed(self, rules: list[Rule]) -> None:
        if not getattr(self, "_rules_ok", True):
            QMessageBox.warning(
                self, tr("Rules tidak tersimpan"),
                tr("config/rules.yaml rusak dan belum diperbaiki. Penyimpanan dibatalkan "
                   "agar rule lama tidak tertimpa."),
            )
            return
        self.rules = rules
        self.engine.set_rules(rules)
        save_rules(rules)
        self._sync_overlay_channels()

    def _on_tools_installed(self) -> None:
        """scrcpy baru diunduh - adb bawaannya sekarang bisa dipakai."""
        from app.config import find_adb

        before = self.adb.adb_path
        self.adb.adb_path = find_adb(self.settings["adb"]["path"])
        if self.adb.adb_path and self.adb.adb_path != before:
            self.log_panel.add_system(tr("adb sekarang memakai bawaan scrcpy: {path}", path=self.adb.adb_path))
            self.devices_panel.refresh()

    def _on_wireless_connected(self, serial: str) -> None:
        """Device wireless baru tersambung - jadikan target aktif."""
        self._on_serial_changed(serial)
        self.devices_panel.refresh()
        self.log_panel.add_system(tr("Device wireless tersambung: {serial}", serial=serial))

    def _on_serial_changed(self, serial: str) -> None:
        self.adb.set_serial(serial)
        self.host.adb_serial = serial
        if hasattr(self, "scrcpy_panel"):
            self.scrcpy_panel._update_preview()
        if hasattr(self, "watcher"):
            self.watcher.set_serial(serial)
        self.settings["adb"]["serial"] = serial
        self._save_settings()

    def _save_settings(self) -> None:
        self.connect_panel.apply_to_settings(self.settings)
        save_settings(self.settings)

    def _tick(self) -> None:
        self.queue_label.setText(tr("Antrian: {n}", n=self.queue.pending()))
        if self.tabs.currentWidget() is getattr(self, "home_panel", None):
            self.home_panel.refresh()
        if self.overlay.running:
            self.overlay_label.setText(f"Overlay: {self.overlay.client_count} klien")
            if self.tabs.currentWidget() is self.overlay_panel:
                self.overlay_panel.refresh_status()
        else:
            self.overlay_label.setText(tr("Overlay: mati"))

    def closeEvent(self, event) -> None:
        self._stop_live()
        self.queue.stop()
        self.host.cleanup()
        self.overlay.stop()
        # Tunggu worker pengambil gift, kalau tidak Qt protes
        # "QThread: Destroyed while thread is still running" saat keluar.
        for widget in (self, self.gifts_panel):
            worker = getattr(widget, "_gift_worker", None)
            if worker is not None and worker.isRunning():
                worker.wait(3000)
        quota = getattr(self.connect_panel, "_quota_worker", None)
        if quota is not None and quota.isRunning():
            quota.wait(3000)
        gift_worker = getattr(self.gifts_panel, "_worker", None)
        if gift_worker is not None and gift_worker.isRunning():
            gift_worker.wait(3000)
        if hasattr(self, "watcher"):
            self.watcher.stop()
            self.watcher.wait(3000)
        self.game_panel.shutdown()
        self.scrcpy_panel.shutdown()
        ICONS.shutdown()
        super().closeEvent(event)
