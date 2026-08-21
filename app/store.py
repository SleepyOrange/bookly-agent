"""Mock data access layer for Bookly.

Orders/policies are loaded from JSON fixtures (data/). Returns and escalation
tickets are created at runtime and kept in-memory only -- this stands in for
a real order-management / ticketing system in production.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

with open(DATA_DIR / "orders.json") as f:
    _ORDERS = {o["order_id"]: o for o in json.load(f)}

with open(DATA_DIR / "policies.json") as f:
    POLICIES = json.load(f)

with open(DATA_DIR / "catalog.json") as f:
    CATALOG = json.load(f)

# Runtime mock tables
_RETURNS = {}
_TICKETS = {}
_next_return_id = 1
_next_ticket_id = 1


def find_order(order_id: str):
    return _ORDERS.get(order_id.strip().upper())


def orders_for_email(email: str):
    email = email.strip().lower()
    return [o for o in _ORDERS.values() if o["customer_email"].lower() == email]


def create_return(order_id: str, item_title: str, reason: str, refund_amount: float):
    global _next_return_id
    return_id = f"RT-{1000 + _next_return_id}"
    _next_return_id += 1
    record = {
        "return_id": return_id,
        "order_id": order_id,
        "item_title": item_title,
        "reason": reason,
        "refund_amount": refund_amount,
        "status": "label_sent",
    }
    _RETURNS[return_id] = record
    mark_item_returned(order_id, item_title)
    return record


def mark_item_returned(order_id: str, item_title: str):
    order = find_order(order_id)
    if not order:
        return
    for item in order["items"]:
        if item["title"] == item_title:
            item["returned"] = True


def create_ticket(reason: str, order_id: str | None = None):
    global _next_ticket_id
    ticket_id = f"CASE-{5000 + _next_ticket_id}"
    _next_ticket_id += 1
    record = {"ticket_id": ticket_id, "reason": reason, "order_id": order_id}
    _TICKETS[ticket_id] = record
    return record
