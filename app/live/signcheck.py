"""Cek status & kuota sign server (EulerStream).

Berguna untuk membedakan tiga hal yang gejalanya mirip:
  - kuota habis (harus menunggu)
  - sign server sedang tidak bisa memberi koneksi langsung (butuh API key)
  - masalah jaringan lokal
"""

from __future__ import annotations

from typing import Any

RATE_LIMIT_URL = "https://api.eulerstream.com/webcast/rate_limits"


def fetch_rate_limits(api_key: str = "", timeout: float = 15.0) -> dict[str, Any]:
    """Ambil sisa kuota sign server. Lempar Exception kalau gagal."""
    import httpx

    headers = {"X-API-Key": api_key} if api_key else {}
    with httpx.Client(timeout=timeout) as client:
        response = client.get(RATE_LIMIT_URL, headers=headers)
        response.raise_for_status()
        return response.json()


def format_rate_limits(data: dict[str, Any]) -> str:
    """Ringkas jadi satu baris untuk ditampilkan di GUI."""
    parts = []
    for window, label in (("minute", "menit"), ("hour", "jam"), ("day", "hari")):
        bucket = data.get(window)
        if isinstance(bucket, dict):
            parts.append(f"{label}: {bucket.get('remaining', '?')}/{bucket.get('max', '?')}")
    return "Kuota sign server -> " + ", ".join(parts) if parts else "Kuota tidak diketahui"


def is_exhausted(data: dict[str, Any]) -> bool:
    """True kalau salah satu jendela kuota sudah habis."""
    for window in ("minute", "hour", "day"):
        bucket = data.get(window)
        if isinstance(bucket, dict):
            try:
                if int(bucket.get("remaining", 1)) <= 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False
