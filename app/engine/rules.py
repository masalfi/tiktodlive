"""Rule engine: cocokkan LiveEvent dengan Rule, plus cooldown & rate limit."""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Any

from app.i18n import tr
from app.models import LiveEvent, Rule

# Kondisi yang valid per jenis event (dipakai juga oleh editor GUI)
CONDITION_SPECS: dict[str, list[tuple[str, str, str]]] = {
    # (nama, label, tipe)
    "gift": [
        ("gift_name", "Nama gift", "gift"),
        ("gift_name_mode", "Cocokkan nama", "choice:exact,contains"),
        ("gift_id", "Gift ID", "int"),
        ("min_coins", "Min total koin", "int"),
        ("max_coins", "Maks total koin", "int"),
        ("min_repeat", "Min jumlah kirim", "int"),
    ],
    "comment": [
        ("contains", "Mengandung kata", "str"),
        ("equals", "Sama persis dengan", "str"),
        ("starts_with", "Diawali dengan", "str"),
        ("regex", "Regex", "str"),
        ("case_sensitive", "Peka huruf besar/kecil", "bool"),
    ],
    "like": [("min_likes", "Min jumlah like", "int")],
    "follow": [],
    "share": [],
    "join": [],
}

# Berlaku untuk semua jenis event
COMMON_CONDITIONS = [("from_user", "Hanya dari user", "str")]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _match_gift(event: LiveEvent, cond: dict[str, Any]) -> bool:
    name = cond.get("gift_name")
    if name:
        mode = str(cond.get("gift_name_mode") or "exact")
        actual = (event.gift_name or "").lower()
        wanted = str(name).lower()
        if mode == "contains":
            if wanted not in actual:
                return False
        elif actual != wanted:
            return False

    gift_id = _as_int(cond.get("gift_id"))
    if gift_id is not None and event.gift_id != gift_id:
        return False

    min_coins = _as_int(cond.get("min_coins"))
    if min_coins is not None and event.total_coins < min_coins:
        return False

    max_coins = _as_int(cond.get("max_coins"))
    if max_coins is not None and event.total_coins > max_coins:
        return False

    min_repeat = _as_int(cond.get("min_repeat"))
    if min_repeat is not None and event.repeat_count < min_repeat:
        return False

    return True


def _match_comment(event: LiveEvent, cond: dict[str, Any]) -> bool:
    text = event.comment or ""
    case_sensitive = bool(cond.get("case_sensitive", False))
    haystack = text if case_sensitive else text.lower()

    def norm(value: Any) -> str:
        s = str(value)
        return s if case_sensitive else s.lower()

    if cond.get("contains") and norm(cond["contains"]) not in haystack:
        return False
    if cond.get("equals") and haystack.strip() != norm(cond["equals"]).strip():
        return False
    if cond.get("starts_with") and not haystack.strip().startswith(norm(cond["starts_with"]).strip()):
        return False
    if cond.get("regex"):
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            if not re.search(str(cond["regex"]), text, flags):
                return False
        except re.error:
            # Regex rusak -> rule tidak pernah cocok, tapi jangan crash.
            return False
    return True


def _match_like(event: LiveEvent, cond: dict[str, Any]) -> bool:
    min_likes = _as_int(cond.get("min_likes"))
    if min_likes is not None and event.like_count < min_likes:
        return False
    return True


_MATCHERS = {
    "gift": _match_gift,
    "comment": _match_comment,
    "like": _match_like,
}


def matches(rule: Rule, event: LiveEvent) -> bool:
    """Apakah rule cocok dengan event (tanpa cek cooldown)."""
    if not rule.enabled or rule.event_kind != event.kind:
        return False

    cond = rule.conditions or {}

    # Filter user berlaku untuk semua jenis event.
    from_user = cond.get("from_user")
    if from_user:
        allowed = {u.strip().lstrip("@").lower() for u in str(from_user).split(",") if u.strip()}
        if allowed and event.username.lower() not in allowed:
            return False

    matcher = _MATCHERS.get(event.kind)
    return matcher(event, cond) if matcher else True


class RuleEngine:
    """Menyimpan rule dan melacak cooldown/rate-limit per rule."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules: list[Rule] = list(rules or [])
        self._last_fired: dict[str, float] = {}
        self._fire_times: dict[str, deque[float]] = {}

    def set_rules(self, rules: list[Rule]) -> None:
        """Hot reload - riwayat cooldown rule yang masih ada dipertahankan."""
        self.rules = list(rules)
        live_ids = {r.id for r in self.rules}
        for store in (self._last_fired, self._fire_times):
            for rule_id in list(store.keys()):
                if rule_id not in live_ids:
                    del store[rule_id]

    def check_cooldown(self, rule: Rule, now: float | None = None) -> tuple[bool, str]:
        """(boleh_jalan, alasan_kalau_ditolak)"""
        now = now if now is not None else time.time()

        if rule.cooldown_sec > 0:
            last = self._last_fired.get(rule.id)
            if last is not None:
                remaining = rule.cooldown_sec - (now - last)
                if remaining > 0:
                    return False, tr("cooldown {detik}s lagi", detik=f"{remaining:.1f}")

        if rule.max_per_hour:
            times = self._fire_times.setdefault(rule.id, deque())
            while times and now - times[0] > 3600:
                times.popleft()
            if len(times) >= rule.max_per_hour:
                return False, f"limit {rule.max_per_hour}/jam tercapai"

        return True, ""

    def mark_fired(self, rule: Rule, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._last_fired[rule.id] = now
        self._fire_times.setdefault(rule.id, deque()).append(now)

    def match(self, event: LiveEvent, now: float | None = None) -> tuple[list[Rule], list[tuple[Rule, str]]]:
        """Kembalikan (rule_yang_lolos, [(rule, alasan_ditolak)])."""
        passed: list[Rule] = []
        blocked: list[tuple[Rule, str]] = []
        for rule in self.rules:
            if not matches(rule, event):
                continue
            allowed, reason = self.check_cooldown(rule, now)
            if allowed:
                passed.append(rule)
            else:
                blocked.append((rule, reason))
        return passed, blocked
