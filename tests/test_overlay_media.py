"""Test registry media & aksi overlay (audio + efek)."""

import math
import struct
import wave

import pytest

from app.overlay.media import (
    AUDIO_SUFFIXES,
    MediaError,
    MediaRegistry,
    kind_of,
    mime_of,
)
from pathlib import Path


@pytest.fixture
def audio_file(tmp_path) -> Path:
    path = tmp_path / "nada.wav"
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i * 0.25))) for i in range(800)))
    return path


# ------------------------------------------------------------- deteksi

@pytest.mark.parametrize("name,expected", [
    ("a.mp3", "audio"), ("a.WAV", "audio"), ("a.ogg", "audio"),
    ("a.png", "image"), ("a.GIF", "image"),
    ("a.mp4", "video"), ("a.webm", "video"),
    ("a.txt", ""), ("a", ""), ("a.exe", ""),
])
def test_kind_detection(name, expected):
    assert kind_of(Path(name)) == expected


@pytest.mark.parametrize("name", ["a.mp3", "a.wav", "a.ogg", "a.opus", "a.flac", "a.m4a"])
def test_audio_mime_always_audio_type(name):
    """Browser menolak memutar media yang Content-Type-nya salah."""
    assert mime_of(Path(name)).startswith("audio/")


def test_video_and_image_mime():
    assert mime_of(Path("a.mp4")).startswith("video/")
    assert mime_of(Path("a.png")).startswith("image/")


# ------------------------------------------------------------ keamanan

def test_registry_rejects_missing_file(tmp_path):
    with pytest.raises(MediaError, match="tidak ditemukan"):
        MediaRegistry().register(str(tmp_path / "hilang.mp3"))


def test_registry_rejects_empty_path():
    with pytest.raises(MediaError, match="kosong"):
        MediaRegistry().register("")


def test_registry_rejects_unsupported_type(tmp_path):
    path = tmp_path / "rahasia.txt"
    path.write_text("data")
    with pytest.raises(MediaError, match="tidak didukung"):
        MediaRegistry().register(str(path))


def test_registry_rejects_directory(tmp_path):
    with pytest.raises(MediaError):
        MediaRegistry().register(str(tmp_path))


def test_registry_rejects_empty_file(tmp_path):
    path = tmp_path / "kosong.mp3"
    path.write_bytes(b"")
    with pytest.raises(MediaError, match="kosong"):
        MediaRegistry().register(str(path))


def test_unregistered_id_resolves_to_none():
    """Inti keamanan: ID sembarangan tidak boleh menghasilkan file apa pun."""
    registry = MediaRegistry()
    assert registry.resolve("id-palsu") is None
    assert registry.resolve("../../etc/passwd") is None
    assert registry.resolve("") is None


def test_resolve_returns_none_if_file_deleted(audio_file):
    registry = MediaRegistry()
    media_id, _ = registry.register(str(audio_file))
    assert registry.resolve(media_id) is not None
    audio_file.unlink()
    assert registry.resolve(media_id) is None


# ------------------------------------------------------------ registry

def test_register_returns_id_and_kind(audio_file):
    media_id, kind = MediaRegistry().register(str(audio_file))
    assert kind == "audio"
    assert len(media_id) == 16
    # ID tidak boleh membocorkan path
    assert audio_file.name not in media_id


def test_same_file_gets_same_id(audio_file):
    registry = MediaRegistry()
    first, _ = registry.register(str(audio_file))
    second, _ = registry.register(str(audio_file))
    assert first == second
    assert len(registry) == 1


def test_registry_resolves_back_to_path(audio_file):
    registry = MediaRegistry()
    media_id, _ = registry.register(str(audio_file))
    assert registry.resolve(media_id) == audio_file.resolve()


def test_clear_empties_registry(audio_file):
    registry = MediaRegistry()
    registry.register(str(audio_file))
    registry.clear()
    assert len(registry) == 0


# -------------------------------------------------------- aksi overlay

class FakeOverlay:
    running = True

    def __init__(self):
        self.sent = []
        self.channels_used = []
        self.registry = MediaRegistry()

    def media_url(self, path):
        media_id, kind = self.registry.register(path)
        return f"/media/{media_id}", kind

    def send(self, payload, channel=None):
        self.sent.append(payload)
        self.channels_used.append(channel)
        return 1


@pytest.fixture
def host():
    from app.actions.host import HostExecutor, register_host_actions

    register_host_actions()
    executor = HostExecutor(FakeOverlay())
    return executor


def run(host, action_type, params):
    from app.actions.base import HANDLERS, coerce_params

    return HANDLERS[action_type](host, coerce_params(action_type, params))


def test_overlay_sound_sends_url(host, audio_file):
    result = run(host, "host.overlay_sound", {"file": str(audio_file), "volume": 0.7})
    assert result.ok
    payload = host.overlay.sent[-1]
    assert payload["type"] == "sound"
    assert payload["url"].startswith("/media/")
    assert payload["volume"] == 0.7


def test_overlay_sound_clamps_volume(host, audio_file):
    run(host, "host.overlay_sound", {"file": str(audio_file), "volume": 5.0})
    assert host.overlay.sent[-1]["volume"] == 1.0


def test_overlay_sound_rejects_bad_file(host, tmp_path):
    result = run(host, "host.overlay_sound", {"file": str(tmp_path / "x.mp3")})
    assert not result.ok and "tidak ditemukan" in result.message


def test_overlay_sound_rejects_non_audio(host, tmp_path):
    image = tmp_path / "gambar.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    result = run(host, "host.overlay_sound", {"file": str(image)})
    assert not result.ok and "bukan audio" in result.message


def test_music_play_includes_url_and_loop(host, audio_file):
    result = run(host, "host.overlay_music",
                 {"action": "play", "file": str(audio_file), "volume": 0.3, "loop": True})
    assert result.ok
    payload = host.overlay.sent[-1]
    assert payload["action"] == "play" and payload["loop"] is True
    assert "url" in payload


def test_music_stop_needs_no_file(host):
    """Menghentikan musik tidak boleh memaksa memilih file."""
    result = run(host, "host.overlay_music", {"action": "stop", "fade_ms": 500})
    assert result.ok
    payload = host.overlay.sent[-1]
    assert payload["action"] == "stop"
    assert "url" not in payload


def test_music_volume_needs_no_file(host):
    result = run(host, "host.overlay_music", {"action": "volume", "volume": 0.2})
    assert result.ok and "url" not in host.overlay.sent[-1]


@pytest.mark.parametrize("effect", ["confetti", "shake", "flash", "text", "rain"])
def test_all_effects_send(host, effect):
    result = run(host, "host.overlay_effect", {"effect": effect, "text": "hai"})
    assert result.ok
    assert host.overlay.sent[-1]["effect"] == effect


def test_confetti_count_capped(host):
    run(host, "host.overlay_effect", {"effect": "confetti", "count": 99999})
    assert host.overlay.sent[-1]["count"] <= 400


def test_actions_fail_clearly_when_overlay_off(audio_file):
    from app.actions.host import HostExecutor, register_host_actions

    register_host_actions()
    offline = FakeOverlay()
    offline.running = False
    executor = HostExecutor(offline)

    for action, params in (
        ("host.overlay_sound", {"file": str(audio_file)}),
        ("host.overlay_music", {"action": "stop"}),
        ("host.overlay_effect", {"effect": "confetti"}),
    ):
        result = run(executor, action, params)
        assert not result.ok and "tidak aktif" in result.message


# --------------------------------------------- keamanan file rules

def test_corrupt_rules_raises_instead_of_returning_empty(tmp_path, monkeypatch):
    """Mengembalikan [] diam-diam berbahaya: penyimpanan berikutnya akan
    menimpa SELURUH rule dengan daftar kosong."""
    import app.config as cfg
    from app.config import RulesLoadError

    bad = tmp_path / "rules.yaml"
    bad.write_text("rules: [ini: tidak: valid: yaml")
    monkeypatch.setattr(cfg, "RULES_PATH", bad)

    with pytest.raises(RulesLoadError):
        cfg.load_rules()


def test_save_rules_makes_backup(tmp_path, monkeypatch):
    import app.config as cfg
    from app.models import Action, Rule

    path = tmp_path / "rules.yaml"
    monkeypatch.setattr(cfg, "RULES_PATH", path)
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)

    cfg.save_rules([Rule(name="pertama", actions=[Action("adb.tap")])])
    assert path.exists()

    cfg.save_rules([Rule(name="kedua", actions=[Action("adb.tap")])])
    backup = path.with_suffix(".yaml.bak")
    assert backup.exists(), "cadangan tidak dibuat"
    assert "pertama" in backup.read_text()
    assert "kedua" in path.read_text()


def test_save_rules_leaves_no_temp_file(tmp_path, monkeypatch):
    import app.config as cfg
    from app.models import Action, Rule

    path = tmp_path / "rules.yaml"
    monkeypatch.setattr(cfg, "RULES_PATH", path)
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    cfg.save_rules([Rule(name="x", actions=[Action("adb.tap")])])
    assert not path.with_suffix(".yaml.tmp").exists()


def test_broken_single_rule_does_not_lose_the_others(tmp_path, monkeypatch):
    import app.config as cfg

    path = tmp_path / "rules.yaml"
    path.write_text(
        "rules:\n"
        "- {id: a, name: bagus, event_kind: gift, actions: []}\n"
        "- 12345\n"                                   # entri rusak
        "- {id: b, name: bagus2, event_kind: gift, actions: []}\n"
    )
    monkeypatch.setattr(cfg, "RULES_PATH", path)
    rules = cfg.load_rules()
    assert [r.name for r in rules] == ["bagus", "bagus2"]
