"""Escalation / handoff layer tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import handoff


def test_escalate_to_human_creates_ticket():
    result = handoff.escalate_to_human("Customer suspects fraudulent charge")
    assert result["ticket_id"].startswith("CASE-")
