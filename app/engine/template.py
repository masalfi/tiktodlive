"""Substitusi placeholder pada parameter aksi.

Rule bisa menulis "{user} kirim {count}x {gift}" dan nilainya diisi dari
event yang memicu rule tersebut.
"""

from __future__ import annotations

from typing import Any

from app.models import LiveEvent


def context_from_event(event: LiveEvent) -> dict[str, str]:
    """Nilai placeholder yang tersedia untuk sebuah event."""
    return {
        "user": event.nickname or event.username or "seseorang",
        "username": event.username,
        "nickname": event.nickname,
        "gift": event.gift_name or "",
        "count": str(event.repeat_count),
        "coins": str(event.total_coins),
        "comment": event.comment or "",
        "likes": str(event.like_count),
        "kind": event.kind,
    }


def render(value: Any, context: dict[str, str]) -> Any:
    """Ganti {placeholder} di string; tipe lain dibiarkan apa adanya."""
    if not isinstance(value, str) or "{" not in value:
        return value
    out = value
    for key, replacement in context.items():
        out = out.replace("{" + key + "}", replacement)
    return out


def render_params(params: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    return {key: render(value, context) for key, value in params.items()}
