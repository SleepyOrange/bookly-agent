"""Unit tests for the tool-dispatch error handling in app/orchestrator.py --
the only place an unexpected bug inside a tool call would otherwise surface
(see _run_tool's docstring-equivalent comments). No live model needed here;
run_turn's actual reasoning/tool-selection behavior is covered live in
test_conversations.py -- the exception is the VERIFICATION_CONFIRMATION
prepend logic below, which is deterministic code (not model behavior) and
so gets a fast mocked-client test instead of relying on a live eval alone.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import orchestrator
from app.memory import Session


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(block_id, name, tool_input):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def _response(stop_reason, content):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def _fake_client(responses):
    """responses: one Response per call to .messages.create(), in order."""
    queue = list(responses)

    class FakeMessages:
        def create(self, **kwargs):
            return queue.pop(0)

    return SimpleNamespace(messages=FakeMessages())


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


def test_run_turn_prepends_verification_confirmation_on_first_authenticated_lookup(monkeypatch):
    session = Session()
    session.authenticated_email = "alice@example.com"
    monkeypatch.setitem(
        orchestrator.DISPATCH,
        "lookup_order",
        lambda order_id, email: {"status": "Delivered", "order_id": order_id},
    )
    monkeypatch.setattr(
        orchestrator,
        "_get_client",
        lambda: _fake_client(
            [
                _response("tool_use", [_tool_use_block("t1", "lookup_order", {"order_id": "BK-10234", "email": "alice@example.com"})]),
                _response("end_turn", [_text_block("Your order was delivered.")]),
            ]
        ),
    )

    reply = orchestrator.run_turn(session, "what's the status of my order BK-10234?")

    assert reply.startswith(orchestrator.VERIFICATION_CONFIRMATION)
    assert "Your order was delivered." in reply


def test_run_turn_does_not_repeat_confirmation_once_already_verified_this_conversation(monkeypatch):
    session = Session()
    session.authenticated_email = "alice@example.com"
    session.case_state = {"order_id": "BK-10234", "email": "alice@example.com"}  # already verified earlier
    monkeypatch.setattr(
        orchestrator,
        "_get_client",
        lambda: _fake_client([_response("end_turn", [_text_block("It's eligible for return.")])]),
    )

    reply = orchestrator.run_turn(session, "is it eligible for a return?")

    assert reply == "It's eligible for return."


def test_run_turn_never_prepends_for_an_anonymous_session(monkeypatch):
    session = Session()  # authenticated_email is None
    monkeypatch.setattr(
        orchestrator,
        "_get_client",
        lambda: _fake_client([_response("end_turn", [_text_block("Could you share your order ID and email?")])]),
    )

    reply = orchestrator.run_turn(session, "what's my order status?")

    assert orchestrator.VERIFICATION_CONFIRMATION not in reply
