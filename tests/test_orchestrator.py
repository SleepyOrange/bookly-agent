"""Unit tests for the tool-dispatch error handling in app/orchestrator.py --
the only place an unexpected bug inside a tool call would otherwise surface
(see _run_tool's docstring-equivalent comments). No live model needed here;
run_turn's actual reasoning loop is covered live in test_conversations.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import orchestrator
from app.memory import Session


def test_unknown_tool_returns_error_and_logs(caplog):
    with caplog.at_level("WARNING", logger="bookly.orchestrator"):
        result = orchestrator._run_tool("not_a_real_tool", {})
    assert result["error"] == "unknown_tool"
    assert "not_a_real_tool" in caplog.text


def test_bad_arguments_returns_error_and_logs(caplog, monkeypatch):
    monkeypatch.setitem(orchestrator.DISPATCH, "fake_tool", lambda order_id: order_id)
    with caplog.at_level("WARNING", logger="bookly.orchestrator"):
        result = orchestrator._run_tool("fake_tool", {"wrong_arg": "x"})
    assert result["error"] == "bad_arguments"
    assert "fake_tool" in caplog.text


def test_unexpected_exception_is_caught_logged_and_not_leaked_to_customer(caplog, monkeypatch):
    def boom(**kwargs):
        raise ValueError("some internal detail that shouldn't reach the customer")

    monkeypatch.setitem(orchestrator.DISPATCH, "fake_tool", boom)
    with caplog.at_level("ERROR", logger="bookly.orchestrator"):
        result = orchestrator._run_tool("fake_tool", {})

    assert result["error"] == "tool_error"
    assert "internal detail" not in result["message"]
    # the real detail must still land in the server log, even though the
    # customer-facing message stays generic
    assert "internal detail" in caplog.text


def test_effective_tool_input_overrides_email_when_authenticated():
    session = Session()
    session.authenticated_email = "alice@example.com"

    effective = orchestrator._effective_tool_input(
        session, "lookup_order", {"order_id": "BK-10234", "email": "someone-else@evil.example"}
    )

    assert effective["email"] == "alice@example.com"
    assert effective["order_id"] == "BK-10234"  # untouched


def test_effective_tool_input_leaves_non_identity_tools_alone():
    session = Session()
    session.authenticated_email = "alice@example.com"

    effective = orchestrator._effective_tool_input(session, "search_policy", {"query": "returns"})

    assert effective == {"query": "returns"}


def test_effective_tool_input_no_override_when_not_authenticated():
    session = Session()  # authenticated_email is None by default

    effective = orchestrator._effective_tool_input(
        session, "lookup_order", {"order_id": "BK-10234", "email": "alice@example.com"}
    )

    assert effective["email"] == "alice@example.com"  # unchanged, just not overridden
