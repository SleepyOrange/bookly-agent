"""Escalation / handoff layer: the safety valve for out-of-scope, sensitive,
or unresolved requests. Opens a Salesforce Case (app/salesforce.py) with the
reason and any related order -- mocked for now, real Salesforce org later,
same shape Decagon's own escalation flow uses.
"""
from app import salesforce

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
    subject = f"Bookly escalation: {reason[:80]}"
    description = f"{reason}\n\nRelated order: {order_id}" if order_id else reason
    case = salesforce.create_case(subject=subject, description=description, origin="Chat")
    return {
        "case_number": case["CaseNumber"],
        "status": "escalated",
        "message": "A human specialist has been looped in and will follow up within 1 business day.",
    }


DISPATCH = {"escalate_to_human": escalate_to_human}
