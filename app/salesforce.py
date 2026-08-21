"""Salesforce Case integration -- the escalation/handoff boundary.

This follows Decagon's own documented Salesforce pattern: connect via OAuth,
sync knowledge base + historical tickets, and escalate by creating a
Salesforce Case so a human agent picks it up in the tool they already work
in, not a separate queue. (See the take-home notes on
docs.decagon.ai/connecting-decagon-to-salesforce and
decagon.ai/product/integrations.)

Mocked for now: create_case() returns an in-memory record shaped like a real
Salesforce Case object (Id, CaseNumber, Subject, Status, Origin, Priority,
CreatedDate) instead of calling the real API. Swapping to a real Salesforce
org later is a change to THIS module only -- a single POST to
/services/data/vXX.X/sobjects/Case/ using a Connected App's OAuth token
(client credentials or JWT bearer flow) -- app/handoff.py already treats
"create a case, get back an id/number" as the whole contract, so nothing
above this module needs to change.
"""
import secrets
from datetime import datetime, timezone

_CASES = {}
_next_case_number = 1


def create_case(subject: str, description: str, origin: str = "Chat", priority: str = "Medium") -> dict:
    """Returns a dict shaped like Salesforce's Case object."""
    global _next_case_number
    case_id = "500" + secrets.token_hex(8).upper()[:15]  # Case object prefix + mock 18-char id
    case_number = f"{_next_case_number:08d}"  # matches Salesforce's zero-padded CaseNumber format
    _next_case_number += 1
    record = {
        "Id": case_id,
        "CaseNumber": case_number,
        "Subject": subject,
        "Description": description,
        "Status": "New",
        "Origin": origin,
        "Priority": priority,
        "CreatedDate": datetime.now(timezone.utc).isoformat(),
    }
    _CASES[case_id] = record
    return record


def reset():
    """Test hook: clears all mock cases."""
    global _CASES, _next_case_number
    _CASES = {}
    _next_case_number = 1
