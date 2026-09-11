"""Test multi-channel overlay: satu server, banyak Browser Source."""

import asyncio
import json
import pytest

from app.overlay.server import (
    ALL_CHANNELS,
    DEFAULT_CHANNEL,
    OverlayServer,
    normalize_channel,
)


# ------------------------------------------------------- normalisasi

@pytest.mark.parametrize("raw,expected", [
    ("", "main"), ("   ", "main"), (None, "main"),
    ("alert", "alert"), ("Alert", "alert"), ("  ALERT  ", "alert"),
    ("efek besar", "efek-besar"),
    ("a/b?c", "a-b-c"),          # karakter URL berbahaya dibersihkan
    ("---", "main"),             # hasil kosong jatuh ke default
    ("gift_A-1", "gift_a-1"),
])
def test_normalize_channel(raw, expected):
    assert normalize_channel(raw) == expected


def test_normalize_is_idempotent():
    """Menormalkan dua kali harus sama - kalau tidak, pengirim dan penerima
    bisa berakhir di channel berbeda."""
    for raw in ["Alert", "efek besar", "a/b", "---", ""]:
        once = normalize_channel(raw)
        assert normalize_channel(once) == once


def test_default_channel_constant():
    assert normalize_channel("") == DEFAULT_CHANNEL


# ------------------------------------------------------- routing channel
#
# Bagian ini menguji logika penyaringan channel secara langsung, tanpa
# menjalankan server sungguhan. Menjalankan banyak event loop asyncio di
# dalam satu proses pytest (bersama tes Qt) tidak stabil, sementara
# logika yang benar-benar penting ada di _broadcast().


class FakeWS:
    """Pengganti WebSocketResponse: mencatat apa yang dikirim padanya."""

    def __init__(self, closed: bool = False):
        self.closed = closed
        self.sent: list[dict] = []

    async def send_str(self, data: str) -> None:
        if self.closed:
            raise ConnectionResetError("sudah tertutup")
        self.sent.append(json.loads(data))


def make_server(clients: dict) -> OverlayServer:
    srv = OverlayServer(port=0)
    srv._clients = clients
    return srv


def broadcast(srv: OverlayServer, payload: dict, channel: str) -> int:
    return asyncio.run(srv._broadcast(payload, channel))


def test_message_reaches_only_its_channel():
    """Inti fitur: gift A ke overlay A, gift B ke overlay B."""
    main, alert, efek = FakeWS(), FakeWS(), FakeWS()
    srv = make_server({main: "main", alert: "alert", efek: "efek"})

    assert broadcast(srv, {"m": "ke-main"}, "main") == 1
    assert broadcast(srv, {"m": "ke-alert"}, "alert") == 1

    assert [m["m"] for m in main.sent] == ["ke-main"]
    assert [m["m"] for m in alert.sent] == ["ke-alert"]
    assert efek.sent == []


def test_send_to_unopened_channel_returns_zero():
    """Harus melaporkan 0, bukan diam-diam dianggap berhasil."""
    alert = FakeWS()
    srv = make_server({alert: "alert"})
    assert broadcast(srv, {"m": "x"}, "channel-yang-belum-dibuka") == 0
    assert alert.sent == []


def test_all_channels_reaches_everyone():
    a, b, c = FakeWS(), FakeWS(), FakeWS()
    srv = make_server({a: "main", b: "alert", c: "efek"})
    assert broadcast(srv, {"m": "semua"}, ALL_CHANNELS) == 3
    assert all(len(x.sent) == 1 for x in (a, b, c))


def test_multiple_clients_same_channel():
    """Dua Browser Source di channel sama harus dua-duanya menerima."""
    a, b = FakeWS(), FakeWS()
    srv = make_server({a: "alert", b: "alert"})
    assert broadcast(srv, {"m": "x"}, "alert") == 2
    assert a.sent and b.sent


def test_closed_client_is_removed():
    """Overlay yang ditutup di OBS harus dibuang dari daftar."""
    alive, dead = FakeWS(), FakeWS(closed=True)
    clients = {alive: "alert", dead: "alert"}
    srv = make_server(clients)
    assert broadcast(srv, {"m": "x"}, "alert") == 1
    assert dead not in clients


def test_client_that_errors_is_removed():
    """Koneksi yang putus di tengah kirim tidak boleh menggagalkan sisanya."""
    good, broken = FakeWS(), FakeWS()

    async def boom(_data):
        raise ConnectionResetError("putus")

    broken.send_str = boom
    clients = {good: "alert", broken: "alert"}
    srv = make_server(clients)

    assert broadcast(srv, {"m": "x"}, "alert") == 1
    assert good.sent and broken not in clients


def test_channels_listing():
    a, b, c = FakeWS(), FakeWS(), FakeWS()
    srv = make_server({a: "main", b: "alert", c: "alert"})
    counts = srv.channels()
    assert counts == {"main": 1, "alert": 2}


def test_channels_listing_ignores_closed():
    a, b = FakeWS(), FakeWS(closed=True)
    srv = make_server({a: "alert", b: "alert"})
    assert srv.channels() == {"alert": 1}


def test_channel_url_format():
    srv = OverlayServer(port=8777)
    assert srv.channel_url("") == srv.url
    assert srv.channel_url("main") == srv.url
    assert srv.channel_url("alert") == f"{srv.url}?ch=alert"
    # nama tidak rapi tetap menghasilkan URL yang benar
    assert srv.channel_url("  ALERT ") == f"{srv.url}?ch=alert"


def test_send_normalizes_channel_name():
    """Pengirim menulis 'ALERT', overlay membuka '?ch=alert' - harus nyambung."""
    alert = FakeWS()
    srv = make_server({alert: "alert"})
    assert broadcast(srv, {"m": "x"}, normalize_channel("  ALERT  ")) == 1


# -------------------------------------------------------- aksi + channel

def test_actions_carry_channel():
    from app.actions.base import HANDLERS, coerce_params
    from app.actions.host import HostExecutor, register_host_actions

    register_host_actions()

    class Fake:
        running = True

        def __init__(self):
            self.calls = []

        def send(self, payload, channel=None):
            self.calls.append((payload, channel))
            return 1

    fake = Fake()
    host = HostExecutor(fake)

    handler = HANDLERS["host.overlay_effect"]
    handler(host, coerce_params("host.overlay_effect",
                                {"effect": "confetti", "channel": "alert"}))
    payload, channel = fake.calls[-1]
    assert payload["effect"] == "confetti"
    assert channel == "alert"


@pytest.mark.parametrize("action", [
    "host.overlay", "host.overlay_sound", "host.overlay_music", "host.overlay_effect",
])
def test_all_overlay_actions_have_channel_param(action):
    from app.actions.base import get_spec
    from app.actions.host import register_host_actions

    register_host_actions()
    names = [p.name for p in get_spec(action).params]
    assert "channel" in names, f"{action} tidak punya parameter channel"


# ------------------------------------------------------------ end-to-end

def test_query_param_reaches_server_and_routes():
    """Satu tes sungguhan: klien membuka '?ch=alert' lalu server harus
    mengelompokkannya ke channel itu.

    Unit test di atas memakai _clients palsu, jadi tidak membuktikan
    bahwa parameter URL benar-benar terbaca. Ini yang membuktikannya.
    """
    import websockets

    srv = OverlayServer(port=8843)
    srv.start()
    if not srv.running:
        pytest.skip(f"server tidak bisa start: {srv.error}")

    try:
        async def scenario():
            base = f"ws://127.0.0.1:{srv.port}/ws"
            async with websockets.connect(f"{base}?ch=alert") as alert, \
                       websockets.connect(base) as main:
                await asyncio.sleep(0.4)
                assert srv.channels() == {"alert": 1, "main": 1}

                assert srv.send({"m": "hanya-alert"}, "alert") == 1
                raw = await asyncio.wait_for(alert.recv(), timeout=3)
                assert json.loads(raw)["m"] == "hanya-alert"

                # main tidak boleh menerima apa pun
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(main.recv(), timeout=0.6)

        asyncio.run(scenario())
    finally:
        srv.stop()
