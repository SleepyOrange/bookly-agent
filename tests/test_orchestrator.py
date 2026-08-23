"""Unit tests for the tool-dispatch error handling in app/orchestrator.py --
the only place an unexpected bug inside a tool call would otherwise surface
(see _run_tool's docstring-equivalent comments). No live model needed here;
run_turn's actual reasoning loop is covered live in test_conversations.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import orchestrator


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
