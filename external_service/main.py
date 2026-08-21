"""Bookly External API -- a stand-in for a real order-management system and
FAQ/help-center CMS, run as its own process on its own port. The Bookly
support agent (app/) talks to this over HTTP via app/store.py; nothing in
app/actions.py, app/knowledge.py, or app/guardrails.py knows this service
exists -- they only know the store.py interface.

This is a deliberately swappable boundary: pointing app/store.py's
BOOKLY_EXTERNAL_API_URL at a real hosted system is a config change, not a
rewrite -- see aws/, which fronts this exact same /orders and /faq contract
with DynamoDB and a Bedrock Knowledge Base (real semantic retrieval) instead
of the lexical stand-in used here for fast local dev/testing.
"""
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from external_service import data_store

app = FastAPI(title="Bookly External API")


class ReturnRequest(BaseModel):
    item_title: str
    reason: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = data_store.find_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"No order found with ID {order_id}."})
    return order


@app.get("/orders/{order_id}/eligibility")
def get_eligibility(order_id: str, item_title: str | None = None):
    order = data_store.find_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"No order found with ID {order_id}."})
    return data_store.eligibility(order_id, item_title)


@app.post("/orders/{order_id}/returns")
def post_return(order_id: str, body: ReturnRequest):
    result = data_store.create_return(order_id, body.item_title, body.reason)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result)
    return result


@app.get("/faq")
def search_faq(q: str = Query(..., min_length=1)):
    matches = data_store.search_policy(q)
    if not matches:
        raise HTTPException(status_code=404, detail={"error": "no_match", "message": "No relevant policy content found."})
    return {"query": q, "matches": matches}
