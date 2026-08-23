"""Actions layer: tools that reach into backend systems (order management,
notifications) and reveal or change customer-specific state. Every action
here is gated by the guardrails layer's identity check first -- an action
tool never trusts order_id alone.

Return eligibility, return creation, and return cancellation are all
delegated to store.py, which calls the external order-management system
(external_service/) -- that system owns the business rules for what's
returnable (and what's still cancellable), the same way a real OMS would.
This module stays a thin, presentation-shaping layer on top.
"""
from app import guardrails, store

# Every tool here that takes an "email" argument for identity verification.
# app/orchestrator.py overrides that argument with the session's
# authenticated_email (when logged in) before dispatch -- a hard, code-level
# guarantee, not a prompt hint the model could be talked out of following.
IDENTITY_GATED_TOOLS = {"lookup_order", "check_return_eligibility", "initiate_return", "cancel_return"}

TOOLS = [
    {
        "name": "lookup_order",
        "description": (
            "Look up a Bookly order's status, items, and tracking info. "
            "Requires the order ID AND the email on the order to verify the "
            "requester's identity before any details are revealed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "e.g. BK-10234"},
                "email": {"type": "string", "description": "Email on file for the order"},
            },
            "required": ["order_id", "email"],
        },
    },
    {
        "name": "check_return_eligibility",
        "description": (
            "Check whether an order (or a specific item in it) is still eligible "
            "for return, based on delivery date and the 30-day return window. "
            "Requires order_id and email for identity verification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "email": {"type": "string"},
                "item_title": {"type": "string", "description": "Optional: specific item to check"},
            },
            "required": ["order_id", "email"],
        },
    },
    {
        "name": "initiate_return",
        "description": (
            "Start a return/refund for a specific item on an order. Only call this "
            "after eligibility is confirmed and the customer has stated a reason. "
            "Requires order_id and email for identity verification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "email": {"type": "string"},
                "item_title": {"type": "string"},
                "reason": {"type": "string", "description": "Customer's stated reason for the return"},
            },
            "required": ["order_id", "email", "item_title", "reason"],
        },
    },
    {
        "name": "cancel_return",
        "description": (
            "Cancel a return that was already initiated, voiding its return "
            "label -- only possible before the return has been processed. "
            "Requires order_id and email for identity verification, plus the "
            "return_id given when initiate_return was called."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "email": {"type": "string"},
                "return_id": {"type": "string", "description": "e.g. RT-1001, from when the return was initiated"},
            },
            "required": ["order_id", "email", "return_id"],
        },
    },
    {
        "name": "send_password_reset",
        "description": "Trigger a password reset email to the customer's address on file.",
        "input_schema": {
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
    },
]


def lookup_order(order_id: str, email: str):
    order, err = guardrails.verify_identity(order_id, email)
    if err:
        return err
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "order_date": order["order_date"],
        "delivery_date": order["delivery_date"],
        "tracking_number": order["tracking_number"],
        "carrier": order["carrier"],
        "items": order["items"],
    }


def check_return_eligibility(order_id: str, email: str, item_title: str | None = None):
    order, err = guardrails.verify_identity(order_id, email)
    if err:
        return err
    return store.check_eligibility(order_id, item_title)


def initiate_return(order_id: str, email: str, item_title: str, reason: str):
    order, err = guardrails.verify_identity(order_id, email)
    if err:
        return err
    result = store.create_return(order_id, item_title, reason)
    if "error" in result:
        return result
    return {
        "return_id": result["return_id"],
        "status": "Return initiated",
        "refund_amount": result["refund_amount"],
        "next_steps": f"A prepaid return label has been emailed to {order['customer_email']}. Refund will be issued to the original payment method 5-7 business days after we receive the item.",
    }


def cancel_return(order_id: str, email: str, return_id: str):
    order, err = guardrails.verify_identity(order_id, email)
    if err:
        return err
    result = store.cancel_return(order_id, return_id)
    if "error" in result:
        return result
    return {
        "return_id": result["return_id"],
        "status": "Return cancelled",
        "message": f"Return {result['return_id']} for '{result['item_title']}' has been cancelled -- the label is void and no refund will be issued. The item is yours to keep.",
    }


def send_password_reset(email: str):
    return {
        "status": "sent",
        "message": f"If an account exists for {guardrails.mask_email(email)}, a password reset link has been sent to it.",
    }


DISPATCH = {
    "lookup_order": lookup_order,
    "check_return_eligibility": check_return_eligibility,
    "initiate_return": initiate_return,
    "cancel_return": cancel_return,
    "send_password_reset": send_password_reset,
}
