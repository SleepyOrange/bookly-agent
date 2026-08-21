"""Knowledge layer: grounds policy answers in approved content instead of the
model's parametric memory. In production this would be a chunked/embedded
document store over the real help center; here it's a small curated lookup
table -- enough to prove out the pattern the orchestrator enforces: never
answer a policy question without a get_policy call first.
"""
from app import store

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
                "topic": {
                    "type": "string",
                    "enum": ["shipping", "returns", "refunds", "password_reset", "payment", "account", "contact_human"],
                }
            },
            "required": ["topic"],
        },
    },
]


def get_policy(topic: str):
    text = store.POLICIES.get(topic)
    if not text:
        return {"error": "unknown_topic", "available_topics": list(store.POLICIES.keys())}
    return {"topic": topic, "policy": text}


DISPATCH = {"get_policy": get_policy}
