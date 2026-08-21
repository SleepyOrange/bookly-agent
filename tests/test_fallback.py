"""Tests for automatic fallback to the local mock service when the
configured primary (REST or MCP) backend is unreachable. This is what
actually protects a customer conversation from a real outage -- previous
tests only checked that failure produced a clean error message; these check
that the agent keeps working.
"""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store

UNREACHABLE_URL = "http://127.0.0.1:1"  # nothing listens on port 1; connection fails immediately


@pytest.fixture(autouse=True)
def force_unreachable_primary(monkeypatch):
    """conftest.py's autouse fixture wires store._client to a working
    in-process TestClient before every test; these tests need a REST call
    that actually fails, so point the client at an address nothing answers."""
    monkeypatch.setattr(store, "EXTERNAL_API_URL", UNREACHABLE_URL)
    monkeypatch.setattr(store, "_client", httpx.Client(base_url=UNREACHABLE_URL, timeout=1.0))


def test_find_order_falls_back_to_local_data():
    result = store.find_order("BK-10234")
    assert result["customer_email"] == "alice@example.com"


def test_check_eligibility_falls_back():
    result = store.check_eligibility("BK-10234", "Project Hail Mary")
    assert result["eligible"] is True


def test_create_return_falls_back():
    result = store.create_return("BK-10234", "Project Hail Mary", "Changed my mind")
    assert result["status"] == "label_sent"
    assert result["refund_amount"] == 14.99


def test_search_policy_falls_back():
    matches, err = store.search_policy("how many days to return an item")
    assert err is None
    assert any("30 days" in m["text"] for m in matches)


def test_not_found_still_not_found_via_fallback():
    """The fallback shouldn't paper over a genuinely missing order -- only
    an unreachable primary, not a legitimate 404."""
    result = store.find_order("BK-99999")
    assert result["error"] == "not_found"


def test_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setattr(store, "ENABLE_FALLBACK", False)
    result = store.find_order("BK-10234")
    assert result["error"] == "external_service_unavailable"
