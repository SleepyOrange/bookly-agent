"""Tests for app/memory.py -- the system_context() function that builds the
dynamic part of the prompt every turn, and update_case_state()'s rule that
memory is only ever derived from a successful tool result, never a
customer's claim.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.memory import Session, system_context, update_case_state

BASE = "BASE PROMPT"


def test_no_authenticated_email_no_case_state_returns_base_unchanged():
    session = Session()
    assert system_context(session, BASE) == BASE


def test_authenticated_email_included_in_context():
    session = Session()
    session.authenticated_email = "alice@example.com"
    context = system_context(session, BASE)
    assert "AUTHENTICATED CUSTOMER" in context
    assert "alice@example.com" in context


def test_case_state_included_regardless_of_authentication():
    session = Session()
    session.case_state = {"order_id": "BK-10234", "email": "alice@example.com"}
    context = system_context(session, BASE)
    assert "SESSION CONTEXT" in context
    assert "BK-10234" in context


def test_update_case_state_only_on_success():
    session = Session()
    update_case_state(session, "lookup_order", {"order_id": "BK-10234", "email": "alice@example.com"}, {"error": "not_found"})
    assert session.case_state == {}


def test_update_case_state_only_for_identity_gated_tools():
    session = Session()
    update_case_state(session, "search_policy", {"query": "returns"}, {"matches": []})
    assert session.case_state == {}


def test_update_case_state_sets_order_id_and_email_on_success():
    session = Session()
    update_case_state(session, "lookup_order", {"order_id": "BK-10234", "email": "alice@example.com"}, {"status": "Delivered"})
    assert session.case_state == {"order_id": "BK-10234", "email": "alice@example.com"}
