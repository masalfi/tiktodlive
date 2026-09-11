"""Model data inti yang dipakai lintas modul.

LiveEvent adalah bentuk seragam dari semua event TikTok, supaya rule engine
tidak perlu tahu detail objek TikTokLive.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

# Jenis event yang dikenali sistem
EVENT_KINDS = ("gift", "comment", "like", "follow", "share", "join")


@dataclass
class LiveEvent:
    """Event dari TikTok LIVE yang sudah dinormalisasi."""

    kind: str
    user_id: str = ""
    username: str = ""       # unique_id, mis. "isaackogz"
    nickname: str = ""       # nama tampilan

    # gift
    gift_name: str | None = None
    gift_id: int | None = None
    repeat_count: int = 1
    diamond_count: int = 0   # koin per satu gift
    total_coins: int = 0     # diamond_count * repeat_count

    # comment
    comment: str | None = None

    # like
    like_count: int = 0

    raw: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def display(self) -> str:
        """Ringkasan satu baris untuk panel log."""
        who = self.nickname or self.username or "?"
        if self.kind == "gift":
            return f"{who} mengirim {self.repeat_count}x {self.gift_name} ({self.total_coins} koin)"
        if self.kind == "comment":
            return f"{who}: {self.comment}"
        if self.kind == "like":
            return f"{who} memberi {self.like_count} like"
        if self.kind == "follow":
            return f"{who} mem-follow"
        if self.kind == "share":
            return f"{who} membagikan live"
        if self.kind == "join":
            return f"{who} bergabung"
        return f"{who} - {self.kind}"


@dataclass
class Action:
    """Satu aksi yang dieksekusi saat rule terpicu."""

    type: str                                    # kunci registry, mis. "adb.tap"
    params: dict[str, Any] = field(default_factory=dict)
    delay_after: float = 0.0                     # jeda detik sebelum aksi berikutnya

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Action":
        return cls(
            type=data["type"],
            params=dict(data.get("params") or {}),
            delay_after=float(data.get("delay_after", 0.0)),
        )


@dataclass
class Rule:
    """Aturan: event + kondisi -> rangkaian aksi."""

    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    enabled: bool = True
    event_kind: str = "gift"
    conditions: dict[str, Any] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    cooldown_sec: float = 0.0
    max_per_hour: int | None = None
    require_confirm: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["actions"] = [a.to_dict() for a in self.actions]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        return cls(
            id=data.get("id") or uuid.uuid4().hex[:8],
            name=data.get("name", "Rule tanpa nama"),
            enabled=bool(data.get("enabled", True)),
            event_kind=data.get("event_kind", "gift"),
            conditions=dict(data.get("conditions") or {}),
            actions=[Action.from_dict(a) for a in (data.get("actions") or [])],
            cooldown_sec=float(data.get("cooldown_sec", 0.0)),
            max_per_hour=data.get("max_per_hour"),
            require_confirm=bool(data.get("require_confirm", False)),
        )

    def summary_conditions(self) -> str:
        """Ringkasan kondisi untuk ditampilkan di tabel GUI."""
        if not self.conditions:
            return "(semua)"
        return ", ".join(f"{k}={v}" for k, v in self.conditions.items())


@dataclass
class ActionResult:
    """Hasil eksekusi satu aksi."""

    action_type: str
    ok: bool
    message: str = ""
    duration_ms: int = 0
    ts: float = field(default_factory=time.time)


@dataclass
class Job:
    """Satu rule terpicu oleh satu event, menunggu di antrian."""

    rule: Rule
    event: LiveEvent
    ts: float = field(default_factory=time.time)
