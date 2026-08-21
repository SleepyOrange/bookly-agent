"""Guardrails layer: hard constraints enforced in code, not left to the
model's judgment. Two concerns live here because both must hold on every
single call, regardless of what the LLM decides to do:

- verify_identity: no order data is ever returned unless the caller proves
  they know the account holder's email, cross-checked against the order.
- mask_email: anything echoed back to a customer that contains an email
  address is masked, even values a tool result might otherwise repeat verbatim.
"""
from app import store


def verify_identity(order_id: str, email: str):
    """Returns (order, None) on success, or (None, error_dict) on failure."""
    order = store.find_order(order_id)
    if order is None:
        return None, {"error": "not_found", "message": f"No order found with ID {order_id}."}
    if "error" in order:
        # e.g. external_service_unavailable -- pass the store's error through as-is
        return None, order
    if order["customer_email"].lower() != email.strip().lower():
        return None, {
            "error": "identity_mismatch",
            "message": "The email provided doesn't match our records for this order. Please double-check and try again.",
        }
    return order, None


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    if len(name) <= 2:
        masked = name[0] + "*"
    else:
        masked = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"
