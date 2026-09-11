"""Test klasifikasi error koneksi TikTok."""

import pytest

from app.live.client import TikTokWorker


class FakeWSError(Exception):
    """Meniru websockets.InvalidStatusCode / InvalidStatus."""

    def __init__(self, status_code, message="server rejected WebSocket connection"):
        super().__init__(f"{message}: HTTP {status_code}")
        self.status_code = status_code


class FakeSignError(Exception):
    pass


FakeSignError.__name__ = "SignAPIError"


# --------------------------------------------------------------- fatal

@pytest.mark.parametrize("status", [400, 401, 403])
def test_ws_rejection_is_fatal(status):
    """400/401/403 tidak akan sembuh dengan retry - jangan bakar kuota."""
    assert TikTokWorker._is_fatal(FakeWSError(status)) is True


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_retryable(status):
    assert TikTokWorker._is_fatal(FakeWSError(status)) is False


def test_generic_error_is_retryable():
    assert TikTokWorker._is_fatal(ConnectionError("jaringan putus")) is False


def test_status_attribute_also_recognised():
    """websockets versi baru memakai .status, bukan .status_code."""
    exc = ConnectionError("ditolak")
    exc.status = 400
    assert TikTokWorker._is_fatal(exc) is True


# ------------------------------------------------------------- pesan

@pytest.mark.parametrize("status", [400, 401, 403])
def test_ws_rejection_message_mentions_api_key(status):
    msg = TikTokWorker._explain_error(FakeWSError(status))
    assert f"HTTP {status}" in msg
    assert "API key" in msg
    # Harus jelas ini bukan salah aplikasi, supaya user tidak bingung.
    assert "bukan kesalahan aplikasi" in msg


def test_sign_error_message_mentions_rate_limit():
    msg = TikTokWorker._explain_error(FakeSignError("rate limited"))
    assert "rate limit" in msg.lower()


def test_generic_error_keeps_type_and_message():
    msg = TikTokWorker._explain_error(ConnectionError("jaringan putus"))
    assert "ConnectionError" in msg and "jaringan putus" in msg


def test_error_without_message_still_readable():
    assert TikTokWorker._explain_error(ValueError()) == "ValueError"
