"""Tests for session context and clock injection in chat_payload."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import chat_payload as cp


def test_format_agent_user_message_includes_now_and_timezone(monkeypatch):
    monkeypatch.setenv("DEFAULT_TIMEZONE", "America/New_York")
    fixed = datetime(2026, 5, 27, 15, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    msg = cp.format_agent_user_message(
        "Find mail from March",
        user_email="user@example.com",
        now=fixed,
    )
    assert "<now_iso>2026-05-27T15:30:00-04:00</now_iso>" in msg
    assert "<timezone>America/New_York</timezone>" in msg
    assert "<user_email>user@example.com</user_email>" in msg
    assert "<user_message>\nFind mail from March\n</user_message>" in msg


def test_extract_user_text_from_chat_event_wraps_with_clock(monkeypatch):
    monkeypatch.setenv("DEFAULT_TIMEZONE", "UTC")
    monkeypatch.setattr(
        cp,
        "now_iso",
        lambda **_: ("2026-03-15T12:00:00+00:00", "UTC"),
    )
    event = {
        "eventType": "MESSAGE",
        "message": {"text": "Hello"},
        "user": {"email": "lex@example.com"},
    }
    text = cp.extract_user_text_from_chat_event(event)
    assert text is not None
    assert "<now_iso>2026-03-15T12:00:00+00:00</now_iso>" in text
    assert "Hello" in text


def test_extract_invocation_input_prompt_includes_now(monkeypatch):
    monkeypatch.setenv("DEFAULT_TIMEZONE", "UTC")
    monkeypatch.setattr(
        cp,
        "now_iso",
        lambda **_: ("2026-01-02T08:00:00+00:00", "UTC"),
    )
    inv = cp.extract_invocation_input({"prompt": "What happened yesterday?"})
    assert inv is not None
    assert inv.source == "prompt"
    assert "<now_iso>2026-01-02T08:00:00+00:00</now_iso>" in inv.user_message
    assert "What happened yesterday?" in inv.user_message
