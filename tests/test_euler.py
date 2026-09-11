"""Test normalisasi pesan EulerStream -> LiveEvent."""

import pytest

from app.live import gifts as gifts_mod
from app.live.euler_client import _social_kind, normalize
from app.live.gifts import GiftCatalog


@pytest.fixture(autouse=True)
def catalog(monkeypatch, tmp_path):
    """Katalog gift kecil supaya test tidak bergantung jaringan."""
    monkeypatch.setattr(gifts_mod, "CACHE_PATH", tmp_path / "g.json")
    monkeypatch.setattr(gifts_mod, "CONFIG_DIR", tmp_path)
    cat = GiftCatalog()
    cat.set_from_raw([
        {"id": 5655, "name": "Rose", "diamond_count": 1, "type": 1},      # streakable
        {"id": 6369, "name": "Lion", "diamond_count": 29999, "type": 2},  # non-streak
    ], "test")
    monkeypatch.setattr(gifts_mod, "CATALOG", cat)
    return cat


USER = {"userId": "123", "uniqueId": "budi", "nickname": "Budi"}


def test_comment():
    ev = normalize("WebcastChatMessage", {"user": USER, "comment": "halo semua"})
    assert ev.kind == "comment"
    assert ev.comment == "halo semua"
    assert ev.username == "budi" and ev.nickname == "Budi" and ev.user_id == "123"


def test_like():
    ev = normalize("WebcastLikeMessage", {"user": USER, "likeCount": 15})
    assert ev.kind == "like" and ev.like_count == 15


def test_join():
    ev = normalize("WebcastMemberMessage", {"user": USER})
    assert ev.kind == "join" and ev.nickname == "Budi"


def test_unknown_type_ignored():
    assert normalize("WebcastSomethingElse", {"user": USER}) is None


def test_missing_user_does_not_crash():
    ev = normalize("WebcastChatMessage", {"comment": "anon"})
    assert ev.username == "" and ev.nickname == ""


# ------------------------------------------------------------------ gift

def test_gift_name_resolved_from_catalog():
    """EulerStream hanya kirim giftId - nama diambil dari katalog."""
    ev = normalize("WebcastGiftMessage",
                   {"user": USER, "giftId": 5655, "repeatCount": 3, "repeatEnd": 1})
    assert ev.kind == "gift"
    assert ev.gift_name == "Rose"
    assert ev.diamond_count == 1
    assert ev.total_coins == 3          # 1 koin x 3


def test_streaking_gift_ignored_until_end():
    """Streak yang belum selesai tidak boleh memicu aksi."""
    mid = normalize("WebcastGiftMessage",
                    {"user": USER, "giftId": 5655, "repeatCount": 2, "repeatEnd": 0})
    assert mid is None

    end = normalize("WebcastGiftMessage",
                    {"user": USER, "giftId": 5655, "repeatCount": 9, "repeatEnd": 1})
    assert end is not None and end.repeat_count == 9


def test_non_streakable_gift_always_emitted():
    """Gift non-streak tidak punya repeatEnd yang berarti."""
    ev = normalize("WebcastGiftMessage",
                   {"user": USER, "giftId": 6369, "repeatCount": 1, "repeatEnd": 0})
    assert ev is not None and ev.gift_name == "Lion"
    assert ev.total_coins == 29999


def test_unknown_gift_id_still_produces_event():
    """Gift baru yang belum ada di katalog tidak boleh hilang diam-diam."""
    ev = normalize("WebcastGiftMessage",
                   {"user": USER, "giftId": 999999, "repeatCount": 1, "repeatEnd": 1})
    assert ev is not None
    assert "999999" in ev.gift_name
    assert ev.total_coins == 0


# ---------------------------------------------------------------- social

def test_social_follow():
    data = {"user": USER, "common": {"displayText": {"key": "pm_main_follow_message_viewer_2"}}}
    assert normalize("WebcastSocialMessage", data).kind == "follow"


def test_social_share():
    data = {"user": USER, "common": {"displayText": {"key": "pm_mt_guidance_share"}}}
    assert normalize("WebcastSocialMessage", data).kind == "share"


def test_social_unknown_ignored():
    data = {"user": USER, "common": {"displayText": {"key": "something_else"}}}
    assert normalize("WebcastSocialMessage", data) is None


def test_social_kind_helper_handles_missing_keys():
    assert _social_kind({}) == ""
    assert _social_kind({"common": {}}) == ""
