"""Memory / session layer: per-conversation state, two kinds:

- messages: the raw transcript, required by the Messages API on every call.
- case_state: extracted slots (verified order_id/email) so the orchestrator
  doesn't re-collect identity every turn once it's been verified once.

In-memory and keyed by a random session id here; production would back this
with a real session store (Redis/DB) keyed by an authenticated customer
identity, not a client-generated UUID.
"""
import json


class Session:
    def __init__(self):
        self.messages: list[dict] = []
        self.case_state: dict = {}


def system_context(session: Session, base_prompt: str) -> str:
    if not session.case_state:
        return base_prompt
    return (
        base_prompt
        + "\n\nSESSION CONTEXT (already verified earlier this conversation -- "
        + "reuse it for follow-up requests unless the customer references a "
        + f"different order): {json.dumps(session.case_state)}"
    )


def update_case_state(session: Session, tool_name: str, tool_input: dict, result: dict):
    if tool_name in ("lookup_order", "check_return_eligibility", "initiate_return") and "error" not in result:
        session.case_state["order_id"] = tool_input.get("order_id")
        session.case_state["email"] = tool_input.get("email")
