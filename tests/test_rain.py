"""Test efek hujan: emoji, gambar pilihan, dan ikon gift yang masuk."""

import pytest

from app.actions.base import HANDLERS, coerce_params, get_spec
from app.actions.host import HostExecutor, register_host_actions
from app.engine.template import context_from_event, render_params
from app.models import LiveEvent
from app.overlay.media import MediaRegistry, kind_of, mime_of, sniff

register_host_actions()

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
WEBP = b"RIFF\x20\x13\x00\x00WEBPVP8X" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60


class FakeOverlay:
    running = True

    def __init__(self):
        self.sent = []
        self.registry = MediaRegistry()

    def media_url(self, path):
        media_id, kind = self.registry.register(path)
        return f"/media/{media_id}", kind

    def send(self, payload, channel=None):
        self.sent.append(payload)
        return 1


@pytest.fixture
def host():
    return HostExecutor(FakeOverlay())


def rain(host, params, event=None):
    if event is not None:
        params = render_params(params, context_from_event(event))
    return HANDLERS["host.overlay_effect"](
        host, coerce_params("host.overlay_effect", {"effect": "rain", **params})
    )


# ------------------------------------------------- deteksi tipe berkas

@pytest.mark.parametrize("data,expected_mime", [
    (PNG, "image/png"), (WEBP, "image/webp"), (JPEG, "image/jpeg"),
])
def test_image_detected_without_extension(tmp_path, data, expected_mime):
    """Ikon gift disimpan sebagai '.img' apa pun formatnya. Tanpa membaca
    isi berkas, registry menolaknya dan hujan ikon gift tidak jalan."""
    path = tmp_path / "ikon.img"
    path.write_bytes(data)
    assert sniff(path) == ("image", expected_mime)
    assert kind_of(path) == "image"
    assert mime_of(path) == expected_mime


def test_unknown_content_still_rejected(tmp_path):
    path = tmp_path / "misteri.img"
    path.write_bytes(b"bukan gambar sama sekali" * 4)
    assert kind_of(path) == ""


def test_known_extension_wins_over_sniffing(tmp_path):
    path = tmp_path / "lagu.mp3"
    path.write_bytes(b"\x00" * 64)
    assert kind_of(path) == "audio"


# ----------------------------------------------------------- emoji

def test_emoji_rain(host):
    result = rain(host, {"sumber": "emoji", "emoji": "\U0001F339", "count": 20})
    assert result.ok
    payload = host.overlay.sent[-1]
    assert payload["emoji"] == "\U0001F339"
    assert "image" not in payload
    assert payload["count"] == 20


def test_default_source_is_emoji(host):
    assert rain(host, {"emoji": "\U0001F381"}).ok
    assert "emoji" in host.overlay.sent[-1]


def test_size_included_and_clamped(host):
    rain(host, {"sumber": "emoji", "size_px": 9999})
    assert host.overlay.sent[-1]["size"] <= 200
    rain(host, {"sumber": "emoji", "size_px": 1})
    assert host.overlay.sent[-1]["size"] >= 16


# ----------------------------------------------------------- gambar

def test_image_rain(tmp_path, host):
    image = tmp_path / "hati.png"
    image.write_bytes(PNG)
    result = rain(host, {"sumber": "gambar", "file": str(image), "size_px": 64})
    assert result.ok
    payload = host.overlay.sent[-1]
    assert payload["image"].startswith("/media/")
    assert payload["size"] == 64
    assert "emoji" not in payload


def test_image_source_without_file_fails(host):
    result = rain(host, {"sumber": "gambar", "file": ""})
    assert not result.ok and "belum diisi" in result.message


def test_image_source_rejects_audio(tmp_path, host):
    audio = tmp_path / "lagu.mp3"
    audio.write_bytes(b"\x00" * 64)
    result = rain(host, {"sumber": "gambar", "file": str(audio)})
    assert not result.ok and "bukan gambar" in result.message


def test_image_source_missing_file_fails(tmp_path, host):
    result = rain(host, {"sumber": "gambar", "file": str(tmp_path / "hilang.png")})
    assert not result.ok


# -------------------------------------------------------- ikon gift

@pytest.fixture
def gift_icons(tmp_path, monkeypatch):
    """Cache ikon palsu supaya test tidak menyentuh jaringan."""
    import app.live.gifts as gifts

    folder = tmp_path / "gift_icons"
    folder.mkdir()
    (folder / "5655.img").write_bytes(WEBP)          # Rose
    monkeypatch.setattr(gifts, "ICON_DIR", folder)
    monkeypatch.setattr(gifts, "icon_path", lambda gid: folder / f"{gid}.img")
    return folder


def test_gift_icon_rain_uses_incoming_gift(host, gift_icons):
    """Gift Rose masuk -> hujan ikon Rose, tanpa user memilih gambar."""
    event = LiveEvent(kind="gift", gift_name="Rose", gift_id=5655, repeat_count=3)
    result = rain(host, {"sumber": "gift", "gift_id": "{gift_id}", "count": 30}, event)
    assert result.ok
    payload = host.overlay.sent[-1]
    assert payload["image"].startswith("/media/")
    assert "emoji" not in payload


def test_different_gifts_give_different_images(host, gift_icons):
    (gift_icons / "6369.img").write_bytes(PNG)       # Lion, isi berbeda
    rose = LiveEvent(kind="gift", gift_name="Rose", gift_id=5655)
    lion = LiveEvent(kind="gift", gift_name="Lion", gift_id=6369)

    rain(host, {"sumber": "gift", "gift_id": "{gift_id}"}, rose)
    rain(host, {"sumber": "gift", "gift_id": "{gift_id}"}, lion)

    assert host.overlay.sent[-2]["image"] != host.overlay.sent[-1]["image"]


def test_gift_source_falls_back_to_emoji_for_comment(host, gift_icons):
    """Rule bisa dipicu komentar - jangan gagal, cukup pakai emoji."""
    event = LiveEvent(kind="comment", comment="halo")
    result = rain(host, {"sumber": "gift", "gift_id": "{gift_id}",
                         "emoji": "\U0001F4AC"}, event)
    assert result.ok
    payload = host.overlay.sent[-1]
    assert payload.get("emoji") == "\U0001F4AC"
    assert "image" not in payload


def test_gift_without_cached_icon_falls_back(host, gift_icons, monkeypatch):
    """Ikon belum ada dan unduhan gagal - tetap tampilkan sesuatu."""
    import app.live.gifts as gifts

    monkeypatch.setattr(gifts, "ensure_icon", lambda gid, timeout=15.0: None)
    event = LiveEvent(kind="gift", gift_name="Baru", gift_id=999999)
    result = rain(host, {"sumber": "gift", "gift_id": "{gift_id}"}, event)
    assert result.ok and "emoji" in host.overlay.sent[-1]


# ------------------------------------------------------- placeholder

def test_gift_id_placeholder_available():
    event = LiveEvent(kind="gift", gift_name="Rose", gift_id=5655)
    assert context_from_event(event)["gift_id"] == "5655"


def test_gift_id_empty_for_non_gift():
    assert context_from_event(LiveEvent(kind="comment"))["gift_id"] == ""


def test_effect_spec_has_source_params():
    names = {p.name for p in get_spec("host.overlay_effect").params}
    assert {"sumber", "file", "gift_id", "size_px"} <= names
