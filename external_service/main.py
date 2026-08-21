"""Bookly External API -- a stand-in for a real order-management system and
FAQ/help-center CMS, run as its own process on its own port. The Bookly
support agent (app/) talks to this over HTTP via app/store.py; nothing in
app/actions.py, app/knowledge.py, or app/guardrails.py knows this service
exists -- they only know the store.py interface.

This is a deliberately swappable boundary: pointing app/store.py's
BOOKLY_EXTERNAL_API_URL at a real hosted system (or fronting this same
contract with a RAG-backed FAQ engine) is a config change, not a rewrite.
"""
from fastapi import FastAPI, HTTPException
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


@app.get("/faq/{topic}")
def get_faq(topic: str):
    text = data_store.get_policy(topic)
    if text is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_topic"})
    return {"topic": topic, "policy": text}


@app.get("/faq")
def list_faq():
    return {"topics": list(data_store.POLICIES.keys())}
