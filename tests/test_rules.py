"""Test rule matching, kondisi, cooldown, dan rate limit."""

import pytest

from app.engine.rules import RuleEngine, matches
from app.models import Action, LiveEvent, Rule


def gift_event(name="Rose", coins=1, repeat=1, user="budi"):
    return LiveEvent(
        kind="gift", username=user, nickname=user,
        gift_name=name, gift_id=5655, repeat_count=repeat,
        diamond_count=coins, total_coins=coins * repeat,
    )


def comment_event(text, user="budi"):
    return LiveEvent(kind="comment", username=user, nickname=user, comment=text)


def rule(**kw):
    kw.setdefault("name", "test")
    return Rule(**kw)


# ------------------------------------------------------------------- gift

def test_gift_name_exact():
    r = rule(event_kind="gift", conditions={"gift_name": "Rose"})
    assert matches(r, gift_event("Rose"))
    assert not matches(r, gift_event("Lion"))


def test_gift_name_case_insensitive():
    r = rule(event_kind="gift", conditions={"gift_name": "rose"})
    assert matches(r, gift_event("Rose"))


def test_gift_name_contains():
    r = rule(event_kind="gift", conditions={"gift_name": "ros", "gift_name_mode": "contains"})
    assert matches(r, gift_event("Rose"))
    assert not matches(r, gift_event("Lion"))


def test_gift_min_coins_uses_total():
    r = rule(event_kind="gift", conditions={"min_coins": 100})
    assert not matches(r, gift_event(coins=1, repeat=50))     # total 50
    assert matches(r, gift_event(coins=1, repeat=150))        # total 150


def test_gift_max_coins():
    r = rule(event_kind="gift", conditions={"max_coins": 10})
    assert matches(r, gift_event(coins=5))
    assert not matches(r, gift_event(coins=50))


def test_gift_min_repeat():
    r = rule(event_kind="gift", conditions={"min_repeat": 5})
    assert not matches(r, gift_event(repeat=3))
    assert matches(r, gift_event(repeat=5))


def test_gift_id():
    r = rule(event_kind="gift", conditions={"gift_id": 5655})
    assert matches(r, gift_event())
    r2 = rule(event_kind="gift", conditions={"gift_id": 9999})
    assert not matches(r2, gift_event())


# ---------------------------------------------------------------- comment

def test_comment_contains_default_case_insensitive():
    r = rule(event_kind="comment", conditions={"contains": "halo"})
    assert matches(r, comment_event("HALO semua"))


def test_comment_case_sensitive():
    r = rule(event_kind="comment", conditions={"contains": "halo", "case_sensitive": True})
    assert not matches(r, comment_event("HALO semua"))
    assert matches(r, comment_event("halo semua"))


def test_comment_starts_with_command():
    r = rule(event_kind="comment", conditions={"starts_with": "!home"})
    assert matches(r, comment_event("!home sekarang"))
    assert not matches(r, comment_event("tolong !home"))


def test_comment_equals_trims():
    r = rule(event_kind="comment", conditions={"equals": "!ping"})
    assert matches(r, comment_event("  !ping  "))
    assert not matches(r, comment_event("!ping pong"))


def test_comment_regex():
    r = rule(event_kind="comment", conditions={"regex": r"^!tap \d+ \d+$"})
    assert matches(r, comment_event("!tap 500 1200"))
    assert not matches(r, comment_event("!tap abc"))


def test_broken_regex_does_not_crash():
    r = rule(event_kind="comment", conditions={"regex": "[unclosed"})
    assert not matches(r, comment_event("apa saja"))


# ------------------------------------------------------------------ umum

def test_event_kind_must_match():
    r = rule(event_kind="gift", conditions={})
    assert not matches(r, comment_event("halo"))


def test_disabled_rule_never_matches():
    r = rule(event_kind="gift", enabled=False)
    assert not matches(r, gift_event())


def test_from_user_whitelist():
    r = rule(event_kind="gift", conditions={"from_user": "@budi, siti"})
    assert matches(r, gift_event(user="budi"))
    assert matches(r, gift_event(user="siti"))
    assert not matches(r, gift_event(user="andi"))


def test_follow_matches_without_conditions():
    r = rule(event_kind="follow")
    assert matches(r, LiveEvent(kind="follow", username="budi"))


def test_like_min_likes():
    r = rule(event_kind="like", conditions={"min_likes": 10})
    assert not matches(r, LiveEvent(kind="like", like_count=5))
    assert matches(r, LiveEvent(kind="like", like_count=15))


# -------------------------------------------------------------- cooldown

def test_cooldown_blocks_second_fire():
    r = rule(event_kind="gift", cooldown_sec=10)
    engine = RuleEngine([r])

    passed, blocked = engine.match(gift_event(), now=1000)
    assert passed == [r] and not blocked
    engine.mark_fired(r, now=1000)

    passed, blocked = engine.match(gift_event(), now=1005)
    assert not passed
    assert "cooldown" in blocked[0][1]

    passed, _ = engine.match(gift_event(), now=1011)
    assert passed == [r]


def test_max_per_hour():
    r = rule(event_kind="gift", max_per_hour=2)
    engine = RuleEngine([r])

    for t in (100, 200):
        passed, _ = engine.match(gift_event(), now=t)
        assert passed == [r]
        engine.mark_fired(r, now=t)

    passed, blocked = engine.match(gift_event(), now=300)
    assert not passed
    assert "limit" in blocked[0][1]

    # Setelah lewat 1 jam dari fire pertama, slot terbuka lagi.
    passed, _ = engine.match(gift_event(), now=100 + 3601)
    assert passed == [r]


def test_set_rules_keeps_cooldown_for_surviving_rule():
    r = rule(event_kind="gift", cooldown_sec=10)
    engine = RuleEngine([r])
    engine.mark_fired(r, now=1000)

    engine.set_rules([r])   # hot reload
    passed, blocked = engine.match(gift_event(), now=1002)
    assert not passed and blocked


def test_set_rules_drops_history_for_removed_rule():
    r = rule(event_kind="gift", cooldown_sec=10)
    engine = RuleEngine([r])
    engine.mark_fired(r, now=1000)
    engine.set_rules([])
    assert r.id not in engine._last_fired


def test_multiple_rules_can_match_one_event():
    r1 = rule(name="a", event_kind="gift", conditions={"gift_name": "Rose"})
    r2 = rule(name="b", event_kind="gift", conditions={"min_coins": 1})
    engine = RuleEngine([r1, r2])
    passed, _ = engine.match(gift_event("Rose", coins=1))
    assert len(passed) == 2
