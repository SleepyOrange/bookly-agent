"""Owns the "external system's" data: order records and FAQ/policy text.

This stands in for a real order-management system and FAQ/help-center CMS.
Eligibility and return logic live here deliberately -- in a real integration,
the upstream order system is the one that knows its own return-window rules,
not the support agent calling into it.

Identity/access control is NOT enforced here on purpose. This service just
answers "what does order BK-10234 look like" -- it's the caller's job (the
Bookly agent's guardrails layer) to decide whether the requester is allowed
to see it. A real external system wouldn't necessarily share our auth model,
so we never depend on it for that.
"""
import json
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def _load():
    with open(DATA_DIR / "orders.json") as f:
        orders = {o["order_id"]: o for o in json.load(f)}
    with open(DATA_DIR / "policies.json") as f:
        policies = json.load(f)
    return orders, policies


ORDERS, POLICIES = _load()
RETURNS = {}
_next_return_id = 1


def reset():
    """Test hook: restore fresh state from the JSON fixtures."""
    global ORDERS, POLICIES, RETURNS, _next_return_id
    ORDERS, POLICIES = _load()
    RETURNS = {}
    _next_return_id = 1


def find_order(order_id: str):
    return ORDERS.get(order_id.strip().upper())


def eligibility(order_id: str, item_title: str | None = None):
    order = find_order(order_id)
    if not order:
        return None
    if order["status"] == "Cancelled":
        return {"eligible": False, "reason": "This order was already cancelled -- there's nothing to return."}
    if order["status"] != "Delivered" or not order["delivery_date"]:
        return {
            "eligible": False,
            "reason": f"Order is currently '{order['status']}' and hasn't been delivered yet, so it isn't eligible for return (it can still be cancelled if not yet shipped -- escalate if needed).",
        }
    if not item_title and len(order["items"]) == 1:
        item_title = order["items"][0]["title"]
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


def create_return(order_id: str, item_title: str, reason: str):
    global _next_return_id
    order = find_order(order_id)
    if not order:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}
    elig = eligibility(order_id, item_title)
    if not elig["eligible"]:
        return {"error": "not_eligible", "message": elig["reason"]}

    item = next(i for i in order["items"] if i["title"] == item_title)
    item["returned"] = True
    refund_amount = round(item["price"] * item.get("qty", 1), 2)

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
    RETURNS[return_id] = record
    return record


def cancel_return(order_id: str, return_id: str):
    """Void a return before it's been processed. RETURNS is keyed by
    return_id alone, so the order_id cross-check below isn't redundant --
    without it, anyone who learns/guesses a return_id could cancel a
    different customer's return. Only "label_sent" is cancellable: once a
    return moves past that (refunded, received, etc. -- not modeled yet,
    see README), reversing it would mean also reversing a real refund, which
    this stand-in doesn't attempt.
    """
    order = find_order(order_id)
    if not order:
        return {"error": "not_found", "message": f"No order found with ID {order_id}."}

    record = RETURNS.get(return_id)
    if not record or record["order_id"].strip().upper() != order_id.strip().upper():
        return {"error": "not_found", "message": f"No return found with ID {return_id} on order {order_id}."}
    if record["status"] == "cancelled":
        return {"error": "already_cancelled", "message": f"Return {return_id} was already cancelled."}
    if record["status"] != "label_sent":
        return {
            "error": "not_cancellable",
            "message": f"Return {return_id} can no longer be cancelled (status: {record['status']}).",
        }

    item = next((i for i in order["items"] if i["title"] == record["item_title"]), None)
    if item:
        item["returned"] = False  # reopens eligibility, mirroring a voided label
    record["status"] = "cancelled"
    return record


def search_policy(query: str, limit: int = 3):
    """Lexical stand-in for real semantic search -- scores each policy by how
    many query words appear as a substring of its text (handles simple
    suffix variants like return/returns/returned without needing embeddings).
    Fast and dependency-free for local dev/testing; the AWS-hosted version
    (aws/faq_function) does real vector retrieval against a Bedrock
    Knowledge Base instead. Same request/response contract either way.
    """
    query_words = [w for w in query.lower().split() if len(w) > 2]
    scored = []
    for topic, text in POLICIES.items():
        haystack = f"{topic} {text}".lower()
        score = sum(1 for w in query_words if w in haystack)
        if score:
            scored.append((score, text))
    scored.sort(key=lambda pair: -pair[0])
    denom = max(len(query_words), 1)
    return [{"text": text, "score": round(score / denom, 3)} for score, text in scored[:limit]]
