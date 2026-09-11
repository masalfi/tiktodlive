"""Test katalog gift: parsing, dedupe, pencarian, cache."""

import json

import pytest

from app.live import gifts as gifts_mod
from app.live.gifts import Gift, GiftCatalog, _dedupe, _parse

RAW = [
    {"id": 5655, "name": "Rose", "diamond_count": 1, "type": 1},
    {"id": 6369, "name": "Lion", "diamond_count": 29999, "type": 2},
    {"id": 5487, "name": "Finger Heart", "diamond_count": 5, "type": 1},
]


def test_parse_basic():
    out = _parse(RAW)
    assert len(out) == 3
    assert out[0] == Gift(id=5655, name="Rose", diamond_count=1, type=1)


def test_parse_skips_broken_entries():
    raw = RAW + [
        {"name": "tanpa id"},
        {"id": "bukan angka", "name": "x", "diamond_count": 1, "type": 1},
        {"id": 1, "name": "   ", "diamond_count": 1, "type": 1},
        {},
    ]
    assert len(_parse(raw)) == 3


def test_streakable_flag():
    rose, lion = _parse(RAW)[0], _parse(RAW)[1]
    assert rose.streakable is True
    assert lion.streakable is False


def test_label_shows_price_and_streak():
    assert _parse(RAW)[0].label() == "Rose - 1 koin (streak)"
    assert _parse(RAW)[1].label() == "Lion - 29999 koin"


def test_dedupe_keeps_cheapest_of_same_name():
    raw = [
        {"id": 1, "name": "Level Ship", "diamond_count": 21000, "type": 2},
        {"id": 2, "name": "Level Ship", "diamond_count": 1500, "type": 2},
    ]
    out = _dedupe(_parse(raw))
    assert len(out) == 1
    assert out[0].id == 2 and out[0].diamond_count == 1500


def test_dedupe_is_case_insensitive():
    raw = [
        {"id": 1, "name": "Rose", "diamond_count": 5, "type": 1},
        {"id": 2, "name": "rose", "diamond_count": 1, "type": 1},
    ]
    assert len(_dedupe(_parse(raw))) == 1


def test_dedupe_sorts_by_price():
    out = _dedupe(_parse(RAW))
    assert [g.diamond_count for g in out] == [1, 5, 29999]


# ---------------------------------------------------------------- catalog

def test_find_case_insensitive():
    cat = GiftCatalog()
    cat.gifts = _dedupe(_parse(RAW))
    assert cat.find("rose").id == 5655
    assert cat.find("  ROSE  ").id == 5655
    assert cat.find("tidak ada") is None


def test_search_matches_substring():
    cat = GiftCatalog()
    cat.gifts = _dedupe(_parse(RAW))
    assert [g.name for g in cat.search("ro")] == ["Rose"]
    assert [g.name for g in cat.search("heart")] == ["Finger Heart"]
    # query kosong -> semua
    assert len(cat.search("")) == 3


def test_set_from_raw_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(gifts_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(gifts_mod, "CACHE_PATH", tmp_path / "gifts.json")
    cat = GiftCatalog()
    assert cat.set_from_raw(RAW, "api") == 3
    assert (tmp_path / "gifts.json").exists()

    data = json.loads((tmp_path / "gifts.json").read_text())
    assert len(data["gifts"]) == 3
    assert data["updated_at"] > 0


def test_load_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(gifts_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(gifts_mod, "CACHE_PATH", tmp_path / "gifts.json")
    GiftCatalog().set_from_raw(RAW, "api")

    loaded = GiftCatalog()
    assert loaded.load_cache() is True
    assert len(loaded) == 3
    assert loaded.find("Rose").id == 5655
    assert loaded.source == "cache"


def test_load_cache_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(gifts_mod, "CACHE_PATH", tmp_path / "tidak_ada.json")
    assert GiftCatalog().load_cache() is False


def test_load_cache_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "gifts.json"
    path.write_text("{ ini bukan json valid")
    monkeypatch.setattr(gifts_mod, "CACHE_PATH", path)
    assert GiftCatalog().load_cache() is False


def test_set_from_raw_ignores_empty():
    cat = GiftCatalog()
    cat.gifts = _dedupe(_parse(RAW))
    assert cat.set_from_raw([], "api") == 0
    assert len(cat) == 3          # daftar lama dipertahankan


def test_merge_adds_only_new_gifts(tmp_path, monkeypatch):
    monkeypatch.setattr(gifts_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(gifts_mod, "CACHE_PATH", tmp_path / "gifts.json")
    cat = GiftCatalog()
    cat.set_from_raw(RAW, "api")

    room = RAW + [{"id": 99, "name": "Gift Room Khusus", "diamond_count": 500, "type": 2}]
    assert cat.merge_from_raw(room, "room") == 1
    assert len(cat) == 4
    assert cat.find("Gift Room Khusus") is not None
    # merge ulang tidak menambah duplikat
    assert cat.merge_from_raw(room, "room") == 0
    assert len(cat) == 4


def test_is_empty_and_stale():
    cat = GiftCatalog()
    assert cat.is_empty is True
    assert cat.is_stale is True          # updated_at = 0
    cat.gifts = _dedupe(_parse(RAW))
    assert cat.is_empty is False
