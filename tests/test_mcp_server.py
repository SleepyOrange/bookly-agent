"""Tests for the MCP-wrapped external service (external_service/mcp_server.py)
and the sync bridge that consumes it (app/mcp_client.py, app/store.py with
TRANSPORT="mcp").

Unlike the REST tests, this spins up a real server on a real local port
(matching app/mcp_client.py's default URL) in a background thread rather
than using an in-process transport -- MCP's streamable-HTTP client needs an
actual HTTP connection to negotiate against, and app/mcp_client.py caches
its session at module scope for the process lifetime by design (see its
docstring), so these tests share one server + one persistent client
connection across the whole file, resetting only the underlying data
between tests.

Switching store.TRANSPORT via monkeypatch.setattr (not env var + reload) so
it's automatically reverted after each test regardless of what order pytest
runs the files in -- other test files rely on TRANSPORT staying "rest".
"""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store
from external_service import data_store
from external_service.mcp_server import mcp

_started = False
_start_lock = threading.Lock()


def _ensure_server_running():
    global _started
    with _start_lock:
        if _started:
            return
        threading.Thread(
            target=lambda: mcp.run(transport="streamable-http", host="127.0.0.1", port=8200),
            daemon=True,
        ).start()
        time.sleep(1.5)  # let uvicorn finish starting before the first test connects
        _started = True


@pytest.fixture(autouse=True)
def mcp_transport(monkeypatch):
    _ensure_server_running()
    data_store.reset()
    monkeypatch.setattr(store, "TRANSPORT", "mcp")
    yield
    data_store.reset()


def test_find_order_via_mcp():
    result = store.find_order("BK-10234")
    assert result["customer_email"] == "alice@example.com"


def test_find_order_not_found_via_mcp():
    result = store.find_order("BK-99999")
    assert result["error"] == "not_found"


def test_full_return_flow_via_mcp():
    elig = store.check_eligibility("BK-10234", "Project Hail Mary")
    assert elig["eligible"] is True

    result = store.create_return("BK-10234", "Project Hail Mary", "test via MCP")
    assert result["status"] == "label_sent"
    assert result["refund_amount"] == 14.99

    elig2 = store.check_eligibility("BK-10234", "Project Hail Mary")
    assert elig2["eligible"] is False
    assert "already been returned" in elig2["reason"]


def test_cancel_return_via_mcp():
    created = store.create_return("BK-10234", "Project Hail Mary", "test via MCP")
    result = store.cancel_return("BK-10234", created["return_id"])
    assert result["status"] == "cancelled"

    elig = store.check_eligibility("BK-10234", "Project Hail Mary")
    assert elig["eligible"] is True


def test_search_policy_via_mcp():
    matches, err = store.search_policy("how many days to return an item")
    assert err is None
    assert any("30 days" in m["text"] for m in matches)


def test_guardrails_still_enforced_via_mcp():
    """The point of the whole design: identity verification never moves to
    the transport layer, MCP or otherwise."""
    from app import guardrails

    order, err = guardrails.verify_identity("BK-10234", "not-alice@example.com")
    assert order is None
    assert err["error"] == "identity_mismatch"
