"""Test substitusi placeholder pada parameter aksi."""

from app.engine.template import context_from_event, render, render_params
from app.models import LiveEvent


def test_gift_placeholders():
    event = LiveEvent(kind="gift", username="budi123", nickname="Budi",
                      gift_name="Rose", repeat_count=5, diamond_count=1, total_coins=5)
    ctx = context_from_event(event)
    assert render("{user} kirim {count}x {gift} ({coins} koin)", ctx) == "Budi kirim 5x Rose (5 koin)"


def test_falls_back_to_username_then_generic():
    ctx = context_from_event(LiveEvent(kind="follow", username="budi123"))
    assert render("{user}", ctx) == "budi123"
    assert render("{user}", context_from_event(LiveEvent(kind="follow"))) == "seseorang"


def test_comment_placeholder():
    ctx = context_from_event(LiveEvent(kind="comment", nickname="Siti", comment="halo semua"))
    assert render("{user}: {comment}", ctx) == "Siti: halo semua"


def test_non_string_values_untouched():
    ctx = context_from_event(LiveEvent(kind="gift"))
    assert render(500, ctx) == 500
    assert render(True, ctx) is True


def test_render_params_only_touches_strings():
    ctx = context_from_event(LiveEvent(kind="gift", nickname="Budi"))
    out = render_params({"title": "hai {user}", "x": 540, "on": True}, ctx)
    assert out == {"title": "hai Budi", "x": 540, "on": True}


def test_unknown_placeholder_left_alone():
    ctx = context_from_event(LiveEvent(kind="gift", nickname="Budi"))
    assert render("{user} {tidakada}", ctx) == "Budi {tidakada}"
