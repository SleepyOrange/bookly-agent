"""Actions layer: tools that reach into backend systems (order management,
notifications) and reveal or change customer-specific state. Every action
here is gated by the guardrails layer's identity check first -- an action
tool never trusts order_id alone.
"""
from datetime import date

from app import guardrails, store

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


def _eligibility(order, item_title: str | None):
    if order["status"] == "Cancelled":
        return {"eligible": False, "reason": "This order was already cancelled -- there's nothing to return."}
    if order["status"] != "Delivered" or not order["delivery_date"]:
        return {
            "eligible": False,
            "reason": f"Order is currently '{order['status']}' and hasn't been delivered yet, so it isn't eligible for return (it can still be cancelled if not yet shipped -- escalate if needed).",
        }
    if item_title:
        item = next((i for i in order["items"] if i["title"] == item_title), None)
        if not item:
            titles = [i["title"] for i in order["items"]]
            return {
                "eligible": False,
                "reason": f"'{item_title}' isn't in this order. Items on this order: {titles}.",
            }
        if item.get("returned"):
            return {"eligible": False, "reason": f"'{item_title}' on this order has already been returned."}
        if item.get("format") == "ebook":
            return {"eligible": False, "reason": "E-books and other digital purchases are final sale and non-returnable."}
    delivered = date.fromisoformat(order["delivery_date"])
    days_since = (date.today() - delivered).days
    window = order["return_window_days"]
    if days_since > window:
        return {
            "eligible": False,
            "reason": f"Delivered {days_since} days ago, which is past the {window}-day return window.",
        }
    return {
        "eligible": True,
        "reason": f"Delivered {days_since} days ago, within the {window}-day return window.",
        "days_remaining": window - days_since,
    }


def check_return_eligibility(order_id: str, email: str, item_title: str | None = None):
    order, err = guardrails.verify_identity(order_id, email)
    if err:
        return err
    return _eligibility(order, item_title)


def initiate_return(order_id: str, email: str, item_title: str, reason: str):
    order, err = guardrails.verify_identity(order_id, email)
    if err:
        return err
    elig = _eligibility(order, item_title)
    if not elig["eligible"]:
        return {"error": "not_eligible", "message": elig["reason"]}
    item = next(i for i in order["items"] if i["title"] == item_title)
    refund_amount = round(item["price"] * item.get("qty", 1), 2)
    record = store.create_return(order_id, item_title, reason, refund_amount)
    return {
        "return_id": record["return_id"],
        "status": "Return initiated",
        "refund_amount": refund_amount,
        "next_steps": f"A prepaid return label has been emailed to {order['customer_email']}. Refund will be issued to the original payment method 5-7 business days after we receive the item.",
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
    "send_password_reset": send_password_reset,
}
