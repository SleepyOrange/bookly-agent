"""Knowledge layer: grounds policy answers in approved content instead of the
model's parametric memory. get_policy calls out to the external FAQ/CMS
system (external_service/, via app/store.py) on every call rather than
caching -- a policy edit there is live the next time a customer asks,
with no redeploy of the agent. Enough to prove out the pattern the
orchestrator enforces: never answer a policy question without a get_policy
call first.
"""
from app import store

_TOPICS = ["shipping", "returns", "refunds", "password_reset", "payment", "account", "contact_human"]

TOOLS = [
    {
        "name": "get_policy",
        "description": (
            "Retrieve Bookly's official policy text on a topic. ALWAYS call this "
            "before answering any question about shipping, returns, refunds, "
            "password resets, payment methods, or account settings -- never answer "
            "policy questions from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "enum": _TOPICS},
            },
            "required": ["topic"],
        },
    },
]


def get_policy(topic: str):
    text, err = store.get_policy_text(topic)
    if err:
        return err
    if not text:
        return {"error": "unknown_topic", "available_topics": _TOPICS}
    return {"topic": topic, "policy": text}


DISPATCH = {"get_policy": get_policy}
