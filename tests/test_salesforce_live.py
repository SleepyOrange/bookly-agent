"""Opt-in live tests against a REAL Salesforce org. Gated hard, on purpose:
these create real Case records in whatever org SALESFORCE_INSTANCE_URL
points at -- a production org, in this project's case -- so they must never
run as part of a normal `pytest tests/` invocation. Being skipped is the
correct default outcome for this file.

To run deliberately:
    set -a && source .env && set +a   # loads SALESFORCE_CLIENT_ID/SECRET/INSTANCE_URL
    BOOKLY_SALESFORCE_LIVE_TEST=1 pytest tests/test_salesforce_live.py -v

Every Case created here is clearly marked as a test in its Subject and
Description, and safe to close/delete in the org afterward. This formalizes
the manual verification already run once against 00Dfj00000cNBkr into a
repeatable check, rather than leaving "does this actually work against the
real org" as a one-off fact nobody can reconfirm later.
"""
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import salesforce

LIVE_TEST_ENABLED = os.environ.get("BOOKLY_SALESFORCE_LIVE_TEST", "").lower() in ("1", "true", "yes")
HAS_CREDENTIALS = bool(
    os.environ.get("SALESFORCE_CLIENT_ID")
    and os.environ.get("SALESFORCE_CLIENT_SECRET")
    and os.environ.get("SALESFORCE_INSTANCE_URL")
)

pytestmark = pytest.mark.skipif(
    not (LIVE_TEST_ENABLED and HAS_CREDENTIALS),
    reason=(
        "live Salesforce test skipped by default -- set BOOKLY_SALESFORCE_LIVE_TEST=1 "
        "plus SALESFORCE_CLIENT_ID/SECRET/INSTANCE_URL to run this against a real org deliberately"
    ),
)


@pytest.fixture(autouse=True)
def force_real_mode(monkeypatch):
    monkeypatch.setattr(salesforce, "MODE", "real")


def test_live_case_creation_has_the_real_salesforce_shape():
    result = salesforce.create_case(
        subject="[TEST -- Bookly automated live test, safe to close]",
        description="Created by tests/test_salesforce_live.py. Not a real customer issue.",
        origin="Chat",
        priority="Low",
    )
    assert result["Id"].startswith("500")  # Case object key prefix
    assert re.fullmatch(r"\d{8}", result["CaseNumber"]), f"not a real Salesforce case number: {result['CaseNumber']!r}"
    assert result["Status"] == "New"
    assert "TEST" in result["Subject"]


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="this scenario also needs a live model")
def test_live_escalation_through_the_full_agent_reaches_real_salesforce():
    """The scenario actually run manually to verify this integration:
    Claude -> orchestrator -> handoff.py -> salesforce.py -> the real API,
    not just a direct function call."""
    from app.memory import Session
    from app.orchestrator import run_turn

    session = Session()
    reply = run_turn(
        session,
        "This is an automated TEST message for integration verification -- please escalate "
        "this to a human and mention it is a test, safe to close.",
    )
    match = re.search(r"\b(\d{8})\b", reply)
    assert match, f"expected a real 8-digit Salesforce case number in the reply, got: {reply!r}"
