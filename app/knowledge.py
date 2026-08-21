"""Knowledge layer: grounds policy answers in approved content instead of the
model's parametric memory. search_policy calls out to the external FAQ
system (external_service/ locally, aws/faq_function in production) on every
call rather than caching -- a policy edit there is live the next time a
customer asks, with no redeploy of the agent.

This is real retrieval, not a fixed lookup table: the tool takes the
customer's actual question as free text and gets back ranked, relevant
excerpts, the same shape whether the backend is a lexical stand-in (local
dev) or a Bedrock Knowledge Base doing real semantic search (AWS). Enough to
prove out the pattern the orchestrator enforces: never answer a policy
question without a search_policy call first.
"""
from app import store

TOOLS = [
    {
        "name": "search_policy",
        "description": (
            "Search Bookly's policy/FAQ knowledge base for the customer's question. "
            "ALWAYS call this before answering any question about shipping, returns, "
            "refunds, password resets, payment methods, or account settings -- pass "
            "the customer's actual question (or a short paraphrase), not a fixed "
            "category. Never answer policy questions from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The customer's question, in their own words"},
            },
            "required": ["query"],
        },
    },
]


def search_policy(query: str):
    matches, err = store.search_policy(query)
    if err:
        return err
    if not matches:
        return {"error": "no_match", "message": "No relevant policy content found for that question."}
    return {"query": query, "matches": matches}


DISPATCH = {"search_policy": search_policy}
