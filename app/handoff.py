"""Escalation / handoff layer: the safety valve for out-of-scope, sensitive,
or unresolved requests. In production this would open a real case in the
helpdesk (Zendesk/Intercom/Salesforce Service Cloud) with the full transcript
and case_state attached; here it's a mock ticket table.
"""
from app import store

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
    ticket = store.create_ticket(reason, order_id)
    return {
        "ticket_id": ticket["ticket_id"],
        "status": "escalated",
        "message": "A human specialist has been looped in and will follow up within 1 business day.",
    }


DISPATCH = {"escalate_to_human": escalate_to_human}
