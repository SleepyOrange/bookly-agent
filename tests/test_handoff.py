"""Escalation / handoff layer tests."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import handoff, salesforce


def test_escalate_to_human_creates_salesforce_case():
    result = handoff.escalate_to_human("Customer suspects fraudulent charge")
    assert re.fullmatch(r"\d{8}", result["case_number"])
    assert result["status"] == "escalated"


def test_escalate_to_human_includes_order_id_in_case_description():
    handoff.escalate_to_human("Wrong item received", order_id="BK-10234")
    case = list(salesforce._CASES.values())[-1]
    assert "BK-10234" in case["Description"]


def test_salesforce_case_shape_matches_real_object():
    case = salesforce.create_case(subject="Test", description="Test case")
    assert case["Id"].startswith("500")  # Case object key prefix
    assert case["Status"] == "New"
    assert case["Origin"] == "Chat"
