"""Escalation / handoff layer: the safety valve for out-of-scope, sensitive,
or unresolved requests. Opens a Salesforce Case (app/salesforce.py) with the
reason and any related order -- mocked for now, real Salesforce org later,
same shape Decagon's own escalation flow uses.
"""
import os

from app import salesforce

# Set on public-facing deployments only (e.g. the Heroku demo) so real Cases
# created by anonymous visitors are visibly distinguishable from genuine
# customer cases in the same queue, without changing local/interview behavior.
DEMO_LABEL = os.environ.get("BOOKLY_DEMO_LABEL", "").strip()

TOOLS = [
    {
        "name": "escalate_to_human",
        "description": (
            "Open a case for a human specialist. Use this when the request is out "
            "of scope for support (e.g. legal threats, fraud claims, account "
            "deletion), when the customer explicitly asks for a human, or when you "
            "cannot resolve the issue after a genuine attempt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "order_id": {"type": "string", "description": "Optional related order ID"},
            },
            "required": ["reason"],
        },
    },
]


def escalate_to_human(reason: str, order_id: str | None = None):
    prefix = f"[{DEMO_LABEL}] " if DEMO_LABEL else ""
    subject = f"{prefix}Bookly escalation: {reason[:80]}"
    description = f"{reason}\n\nRelated order: {order_id}" if order_id else reason
    case = salesforce.create_case(subject=subject, description=description, origin="Chat")
    return {
        "case_number": case["CaseNumber"],
        "status": "escalated",
        "message": "A human specialist has been looped in and will follow up within 1 business day.",
    }


DISPATCH = {"escalate_to_human": escalate_to_human}
