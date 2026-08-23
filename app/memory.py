"""Memory / session layer: per-conversation state, three kinds:

- messages: the raw transcript, required by the Messages API on every call.
- case_state: extracted slots (verified order_id/email) so the orchestrator
  doesn't re-collect identity every turn once it's been verified once.
- authenticated_email: set by the channel layer (app/channels/web.py) when
  the request carries a valid login session -- NOT derived from a tool
  result like case_state is, since it comes from a real login rather than an
  order lookup. See app/orchestrator.py's IDENTITY_GATED_TOOLS handling:
  this is the value actually used for identity verification once set, not
  just a prompt hint the model might ignore.

In-memory and keyed by a random session id here; production would back this
with a real session store (Redis/DB) keyed by an authenticated customer
identity, not a client-generated UUID.
"""
import json


class Session:
    def __init__(self):
        self.messages: list[dict] = []
        self.case_state: dict = {}
        self.authenticated_email: str | None = None


def system_context(session: Session, base_prompt: str) -> str:
    parts = [base_prompt]
    if session.authenticated_email:
        parts.append(
            "\n\nAUTHENTICATED CUSTOMER: this session is logged in and already "
            f"identity-verified as {session.authenticated_email}. Do not ask for "
            "their email for any order action -- it's enforced automatically. "
            "Still ask which order if the customer hasn't said, since they may "
            "have more than one."
        )
    if session.case_state:
        parts.append(
            "\n\nSESSION CONTEXT (already verified earlier this conversation -- "
            "reuse it for follow-up requests unless the customer references a "
            f"different order): {json.dumps(session.case_state)}"
        )
    return "".join(parts)


def update_case_state(session: Session, tool_name: str, tool_input: dict, result: dict):
    if tool_name in ("lookup_order", "check_return_eligibility", "initiate_return") and "error" not in result:
        session.case_state["order_id"] = tool_input.get("order_id")
        session.case_state["email"] = tool_input.get("email")
