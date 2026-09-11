"""Konversi event TikTokLive -> LiveEvent seragam.

Nama field diverifikasi terhadap TikTokLive 7.0.0:
  - user.unique_id (alias display_id), user.nickname, user.id
  - gift.name, gift.diamond_count, gift.type (1 = streakable)
  - CommentEvent.content, LikeEvent.count
"""

from __future__ import annotations

from typing import Any

from app.models import LiveEvent


def _user_bits(event: Any) -> dict[str, str]:
    """Ambil identitas user secara defensif - field bisa None."""
    user = getattr(event, "user", None)
    if user is None:
        return {"user_id": "", "username": "", "nickname": ""}
    return {
        "user_id": str(getattr(user, "id", "") or ""),
        "username": str(getattr(user, "unique_id", "") or ""),
        "nickname": str(getattr(user, "nickname", "") or ""),
    }


def normalize_gift(event: Any, repeat_count: int) -> LiveEvent:
    """repeat_count diteruskan oleh pemanggil karena logika streak
    ditentukan di client (hanya hitung saat streak selesai)."""
    gift = getattr(event, "gift", None)
    diamonds = int(getattr(gift, "diamond_count", 0) or 0) if gift else 0
    return LiveEvent(
        kind="gift",
        gift_name=str(getattr(gift, "name", "") or "") if gift else "",
        gift_id=int(getattr(gift, "id", 0) or 0) if gift else None,
        repeat_count=repeat_count,
        diamond_count=diamonds,
        total_coins=diamonds * repeat_count,
        **_user_bits(event),
    )


def normalize_comment(event: Any) -> LiveEvent:
    return LiveEvent(
        kind="comment",
        comment=str(getattr(event, "content", "") or ""),
        **_user_bits(event),
    )


def normalize_like(event: Any) -> LiveEvent:
    return LiveEvent(
        kind="like",
        like_count=int(getattr(event, "count", 0) or 0),
        **_user_bits(event),
    )


def normalize_simple(event: Any, kind: str) -> LiveEvent:
    """Untuk follow / share / join yang tidak punya payload tambahan."""
    return LiveEvent(kind=kind, **_user_bits(event))
