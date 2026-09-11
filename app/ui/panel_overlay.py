"""Tab Overlay: status server, pemilih media, dan uji coba efek.

Tujuannya supaya kamu bisa mencoba suara/musik/efek langsung tanpa
menunggu gift asli, dan tahu persis tampilannya sebelum live.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.overlay.server import DEFAULT_CHANNEL
from app.ui.theme import ACCENT, DANGER, OK, TEXT_DIM, WARN

AUDIO_FILTER = "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac *.opus);;Semua file (*)"

EFFECTS = [
    ("confetti", "Confetti"),
    ("shake", "Layar bergetar"),
    ("flash", "Kilat warna"),
    ("text", "Teks melayang"),
    ("rain", "Hujan emoji"),
]


class OverlayPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, overlay, host, settings: dict) -> None:
        super().__init__()
        self.overlay = overlay
        self.host = host
        self.settings = settings
        saved = settings.setdefault("overlay", {}).setdefault("test", {})
        self._rule_channels: list[str] = []

        # Isi tab ini cukup tinggi (status + 2 kotak audio + efek). Tanpa
        # area gulir, kotak paling bawah terhimpit di jendela kecil.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(self._build_status())
        root.addWidget(self._build_audio(saved))
        root.addWidget(self._build_effects(saved))
        # Tanpa stretch: tinggi konten = jumlah isinya, jadi area gulir
        # bekerja dan kotak terakhir tidak ikut ditekan.

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._scroll_content = content

        # Hasil aksi tetap di bawah, di luar area gulir, supaya selalu terlihat.
        result = self._build_result()
        result.setContentsMargins(10, 4, 10, 8)
        outer.addWidget(result)

        self.refresh_status()

    def showEvent(self, event) -> None:
        # Server overlay menyala setelah panel dibuat, jadi status awal
        # selalu basi. Segarkan tiap kali tab ini dibuka.
        super().showEvent(event)
        self._lock_content_height()
        self.refresh_status()

    def _lock_content_height(self) -> None:
        """Kunci tinggi minimum isi area gulir.

        Tanpa ini QScrollArea memampatkan kotak paling bawah saat jendela
        pendek, bukan menampilkan scrollbar.
        """
        content = getattr(self, "_scroll_content", None)
        if content is None:
            return
        needed = content.layout().sizeHint().height()
        if needed > content.minimumHeight():
            content.setMinimumHeight(needed)

    # ------------------------------------------------------------ status

    def _build_status(self) -> QWidget:
        box = QGroupBox("Server overlay")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        self.status_label = QLabel("-")
        layout.addWidget(self.status_label)

        # Satu server melayani banyak Browser Source. Channel dibuat sebagai
        # combo yang bisa diketik: pilihan yang sudah dipakai muncul otomatis,
        # tapi channel baru tetap bisa diketik langsung.
        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("Channel:"))

        self.channel_combo = QComboBox()
        self.channel_combo.setEditable(True)
        self.channel_combo.setInsertPolicy(QComboBox.NoInsert)
        self.channel_combo.setMinimumWidth(200)
        self.channel_combo.lineEdit().setPlaceholderText("main")
        self.channel_combo.currentTextChanged.connect(self._on_channel_changed)
        ch_row.addWidget(self.channel_combo, 1)

        self.copy_button = QPushButton("Salin URL")
        self.copy_button.setToolTip("Salin URL untuk ditempel ke OBS Browser Source")
        self.copy_button.clicked.connect(self._copy_url)
        ch_row.addWidget(self.copy_button)

        self.clear_button = QPushButton("Bersihkan")
        self.clear_button.setToolTip("Hapus alert & efek di channel ini")
        self.clear_button.clicked.connect(self._clear_overlay)
        ch_row.addWidget(self.clear_button)

        self.clear_all_button = QPushButton("Semua")
        self.clear_all_button.setToolTip("Bersihkan semua channel sekaligus")
        self.clear_all_button.clicked.connect(self._clear_all_channels)
        ch_row.addWidget(self.clear_all_button)
        layout.addLayout(ch_row)

        self.url_label = QLabel("-")
        self.url_label.setProperty("class", "mono")
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.url_label)

        self.channel_state = QLabel("-")
        layout.addWidget(self.channel_state)

        self._reload_channels()
        saved = self.settings.get("overlay", {}).get("test", {}).get("channel", "")
        if saved:
            self.channel_combo.setCurrentText(saved)
        return box

    # ----------------------------------------------------------- channel

    def known_channels(self) -> list[str]:
        """Channel yang layak ditawarkan: bawaan + dari rule + yang terhubung."""
        from app.overlay.server import normalize_channel

        names = [DEFAULT_CHANNEL]
        for source in (self._rule_channels, list(self.overlay.channels()) if self.overlay.running else []):
            for raw in source:
                name = normalize_channel(raw)
                if name not in names:
                    names.append(name)
        return names

    def set_rule_channels(self, channels) -> None:
        """Dipanggil MainWindow saat rule berubah, supaya channel yang
        dipakai rule ikut muncul di daftar."""
        self._rule_channels = list(channels)
        self._reload_channels()

    def _reload_channels(self) -> None:
        """Isi ulang combo tanpa mengubah teks yang sedang diketik."""
        current = self.channel_combo.currentText() if hasattr(self, "channel_combo") else ""
        names = self.known_channels()
        connected = self.overlay.channels() if self.overlay.running else {}

        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        for name in names:
            count = connected.get(name, 0)
            label = f"{name}  ({count} terbuka)" if count else name
            self.channel_combo.addItem(label, name)
        self.channel_combo.blockSignals(False)

        if current:
            self.channel_combo.setCurrentText(current)

    def current_channel(self) -> str:
        """Nama channel terpilih, tanpa embel-embel '(n terbuka)'."""
        text = self.channel_combo.currentText().strip()
        index = self.channel_combo.findText(text)
        if index >= 0:
            data = self.channel_combo.itemData(index)
            if data:
                return str(data)
        return text.split("  (")[0].strip()

    def refresh_status(self) -> None:
        if not self.overlay.running:
            error = self.overlay.error or "tidak aktif"
            self.status_label.setText(f"Server overlay mati: {error}")
            self.status_label.setStyleSheet(f"color:{DANGER};")
            self.url_label.setText("-")
            self.channel_state.setText("-")
            self.channel_state.setStyleSheet(f"color:{TEXT_DIM};")
            return

        total = self.overlay.client_count
        self.status_label.setText(f"Server aktif  \u2014  {total} overlay terbuka")
        self.status_label.setStyleSheet(f"color:{OK if total else TEXT_DIM};")

        channel = self.current_channel()
        self.url_label.setText(self.overlay.channel_url(channel))

        from app.overlay.server import normalize_channel

        name = normalize_channel(channel)
        count = self.overlay.channels().get(name, 0)
        if count:
            self.channel_state.setText(f"\u25cf {count} overlay terhubung di channel '{name}'")
            self.channel_state.setStyleSheet(f"color:{OK};")
        else:
            self.channel_state.setText(
                f"Belum ada Browser Source untuk channel '{name}' \u2014 "
                "tempel URL di atas ke OBS."
            )
            self.channel_state.setStyleSheet(f"color:{WARN};")

        self._reload_channels()

    def _on_channel_changed(self, *_args) -> None:
        if self.overlay.running:
            self.url_label.setText(self.overlay.channel_url(self.current_channel()))
        self._save()

    def _copy_url(self) -> None:
        url = self.overlay.channel_url(self.current_channel())
        QApplication.clipboard().setText(url)
        self._report(True, f"URL disalin: {url}")

    def _clear_overlay(self) -> None:
        if not self.overlay.running:
            self._report(False, "Server overlay tidak aktif.")
            return
        from app.overlay.server import normalize_channel

        name = normalize_channel(self.current_channel())
        sent = self.overlay.send({"type": "clear"}, self.current_channel())
        self._report(True, f"Channel '{name}' dibersihkan ({sent} overlay).")

    def _clear_all_channels(self) -> None:
        if not self.overlay.running:
            self._report(False, "Server overlay tidak aktif.")
            return
        from app.overlay.server import ALL_CHANNELS

        sent = self.overlay.send({"type": "clear"}, ALL_CHANNELS)
        self._report(True, f"Semua channel dibersihkan ({sent} overlay).")

    # ------------------------------------------------------------- audio

    def _build_audio(self, saved: dict) -> QWidget:
        """Dua kotak terpisah: efek suara sekali jalan vs musik latar.

        Sebelumnya digabung dan muncul dua label "Volume" berturut-turut,
        yang membingungkan karena tidak jelas volume mana milik siapa.
        """
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # ---- efek suara
        sfx_box = QGroupBox("Efek suara (sekali jalan)")
        sfx_form = QFormLayout(sfx_box)

        sfx_row = QHBoxLayout()
        self.sfx_edit = QLineEdit(saved.get("sound_file", ""))
        self.sfx_edit.setPlaceholderText("pilih file mp3/wav dari mana saja di komputer")
        self.sfx_edit.editingFinished.connect(self._save)
        sfx_row.addWidget(self.sfx_edit, 1)
        sfx_browse = QPushButton("Pilih...")
        sfx_browse.clicked.connect(lambda: self._browse(self.sfx_edit))
        sfx_row.addWidget(sfx_browse)
        sfx_form.addRow("File:", sfx_row)

        sfx_ctl = QHBoxLayout()
        self.sfx_volume = self._volume(saved.get("sound_volume", 1.0))
        sfx_ctl.addWidget(self.sfx_volume)
        sfx_ctl.addSpacing(12)
        self.sfx_test = QPushButton("Uji suara")
        self.sfx_test.clicked.connect(self._test_sound)
        sfx_ctl.addWidget(self.sfx_test)
        sfx_ctl.addStretch(1)
        sfx_form.addRow("Volume:", sfx_ctl)
        outer.addWidget(sfx_box)

        # ---- musik latar
        music_box = QGroupBox("Musik latar (diulang terus)")
        music_form = QFormLayout(music_box)

        music_row = QHBoxLayout()
        self.music_edit = QLineEdit(saved.get("music_file", ""))
        self.music_edit.setPlaceholderText("musik yang diputar berulang selama live")
        self.music_edit.editingFinished.connect(self._save)
        music_row.addWidget(self.music_edit, 1)
        music_browse = QPushButton("Pilih...")
        music_browse.clicked.connect(lambda: self._browse(self.music_edit))
        music_row.addWidget(music_browse)
        music_form.addRow("File:", music_row)

        music_ctl = QHBoxLayout()
        self.music_volume = self._volume(saved.get("music_volume", 0.5))
        music_ctl.addWidget(self.music_volume)
        music_ctl.addSpacing(12)
        music_ctl.addWidget(QLabel("Fade:"))
        self.fade_spin = QSpinBox()
        self.fade_spin.setRange(0, 10000)
        self.fade_spin.setSingleStep(100)
        self.fade_spin.setSuffix(" ms")
        self.fade_spin.setValue(int(saved.get("music_fade", 800)))
        self.fade_spin.valueChanged.connect(self._save)
        music_ctl.addWidget(self.fade_spin)
        music_ctl.addSpacing(12)
        self.loop_check = QCheckBox("Ulangi")
        self.loop_check.setChecked(bool(saved.get("music_loop", True)))
        self.loop_check.toggled.connect(self._save)
        music_ctl.addWidget(self.loop_check)
        music_ctl.addStretch(1)
        music_form.addRow("Volume:", music_ctl)

        buttons = QHBoxLayout()
        for label, slot in (("Putar", self._music_play),
                            ("Ubah volume", self._music_volume),
                            ("Hentikan", self._music_stop)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        music_form.addRow("", buttons)
        outer.addWidget(music_box)
        return wrap

    def _volume(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(float(value))
        spin.valueChanged.connect(self._save)
        return spin

    def _browse(self, target: QLineEdit) -> None:
        start = str(Path(target.text()).parent) if target.text().strip() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Pilih file audio", start, AUDIO_FILTER)
        if path:
            target.setText(path)
            self._save()

    # ------------------------------------------------------------ efek

    def _build_effects(self, saved: dict) -> QWidget:
        box = QGroupBox("Efek visual")
        form = QFormLayout(box)

        self.effect_combo = QComboBox()
        for value, label in EFFECTS:
            self.effect_combo.addItem(label, value)
        index = self.effect_combo.findData(saved.get("effect", "confetti"))
        self.effect_combo.setCurrentIndex(index if index >= 0 else 0)
        self.effect_combo.currentIndexChanged.connect(self._on_effect_changed)
        form.addRow("Efek:", self.effect_combo)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 400)
        self.count_spin.setValue(int(saved.get("effect_count", 80)))
        self.count_spin.valueChanged.connect(self._save)
        form.addRow("Jumlah:", self.count_spin)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(60, 5000)
        self.duration_spin.setSingleStep(50)
        self.duration_spin.setSuffix(" ms")
        self.duration_spin.setValue(int(saved.get("effect_duration", 500)))
        self.duration_spin.valueChanged.connect(self._save)
        form.addRow("Durasi:", self.duration_spin)

        self.color_edit = QLineEdit(saved.get("effect_color", "#ff4d94"))
        self.color_edit.setPlaceholderText("#ff4d94")
        self.color_edit.editingFinished.connect(self._save)
        form.addRow("Warna:", self.color_edit)

        self.text_edit = QLineEdit(saved.get("effect_text", "Terima kasih!"))
        self.text_edit.editingFinished.connect(self._save)
        form.addRow("Teks:", self.text_edit)

        self.emoji_edit = QLineEdit(saved.get("effect_emoji", "\U0001F381"))
        self.emoji_edit.setMaxLength(8)
        self.emoji_edit.editingFinished.connect(self._save)
        form.addRow("Emoji:", self.emoji_edit)

        row = QHBoxLayout()
        test = QPushButton("Uji efek")
        test.setStyleSheet("font-weight:bold;")
        test.clicked.connect(self._test_effect)
        row.addWidget(test)
        alert = QPushButton("Uji alert")
        alert.clicked.connect(self._test_alert)
        row.addWidget(alert)
        row.addStretch(1)
        form.addRow("", row)

        self._on_effect_changed()
        return box

    def _on_effect_changed(self) -> None:
        """Sembunyikan field yang tidak relevan untuk efek terpilih."""
        effect = self.effect_combo.currentData()
        visible = {
            "confetti": {"count"},
            "shake": {"duration"},
            "flash": {"duration", "color"},
            "text": {"text", "color"},
            "rain": {"count", "emoji"},
        }.get(effect, set())

        form = self.effect_combo.parentWidget().layout()
        for name, widget in (("count", self.count_spin), ("duration", self.duration_spin),
                             ("color", self.color_edit), ("text", self.text_edit),
                             ("emoji", self.emoji_edit)):
            show = name in visible
            widget.setVisible(show)
            label = form.labelForField(widget)
            if label is not None:
                label.setVisible(show)
        self._save()

    # ----------------------------------------------------------- eksekusi

    def _build_result(self) -> QWidget:
        self.result_label = QLabel("-")
        self.result_label.setWordWrap(True)
        return self.result_label

    def _report(self, ok: bool, message: str) -> None:
        self.result_label.setText(message)
        if not ok:
            color = DANGER
        elif "belum ada overlay" in message:
            # Aksi berhasil dikirim, tapi tidak ada yang menerima - itu
            # hampir selalu berarti Browser Source-nya belum dibuka.
            color = WARN
        else:
            color = OK
        self.result_label.setStyleSheet(f"color:{color};")

    def _run(self, action_type: str, params: dict) -> None:
        from app.actions.base import HANDLERS, coerce_params

        handler = HANDLERS.get(action_type)
        if handler is None:
            self._report(False, f"Aksi {action_type} tidak terdaftar.")
            return
        result = handler(self.host, coerce_params(action_type, params))
        self._report(result.ok, result.message)
        self.refresh_status()

    def _test_sound(self) -> None:
        self._run("host.overlay_sound", {
            "file": self.sfx_edit.text(), "volume": self.sfx_volume.value(),
            "channel": self.current_channel(),
        })

    def _music_play(self) -> None:
        self._run("host.overlay_music", {
            "action": "play", "file": self.music_edit.text(),
            "volume": self.music_volume.value(), "fade_ms": self.fade_spin.value(),
            "loop": self.loop_check.isChecked(), "channel": self.current_channel(),
        })

    def _music_volume(self) -> None:
        self._run("host.overlay_music", {
            "action": "volume", "volume": self.music_volume.value(),
            "fade_ms": self.fade_spin.value(), "channel": self.current_channel(),
        })

    def _music_stop(self) -> None:
        self._run("host.overlay_music", {
            "action": "stop", "fade_ms": self.fade_spin.value(),
            "channel": self.current_channel(),
        })

    def _test_effect(self) -> None:
        self._run("host.overlay_effect", {
            "effect": self.effect_combo.currentData(),
            "count": self.count_spin.value(),
            "duration_ms": self.duration_spin.value(),
            "color": self.color_edit.text(),
            "text": self.text_edit.text(),
            "emoji": self.emoji_edit.text(),
            "channel": self.current_channel(),
        })

    def _test_alert(self) -> None:
        self._run("host.overlay", {
            "title": "Budi mengirim 5x Rose",
            "subtitle": "5 koin",
            "style": "gift",
            "duration_ms": 4000, "channel": self.current_channel(),
        })

    # ------------------------------------------------------------ simpan

    def _save(self, *_args) -> None:
        # Sinyal bisa terpicu saat UI masih dibangun (combo channel dibuat
        # sebelum widget audio), jadi jangan simpan sebelum semuanya ada.
        if not hasattr(self, "emoji_edit"):
            return

        self.settings.setdefault("overlay", {})["test"] = {
            "sound_file": self.sfx_edit.text(),
            "sound_volume": self.sfx_volume.value(),
            "music_file": self.music_edit.text(),
            "music_volume": self.music_volume.value(),
            "music_fade": self.fade_spin.value(),
            "music_loop": self.loop_check.isChecked(),
            "effect": self.effect_combo.currentData(),
            "effect_count": self.count_spin.value(),
            "effect_duration": self.duration_spin.value(),
            "effect_color": self.color_edit.text(),
            "effect_text": self.text_edit.text(),
            "effect_emoji": self.emoji_edit.text(),
            "channel": self.current_channel(),
        }
        self.settings_changed.emit()
