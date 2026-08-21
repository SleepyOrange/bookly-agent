"""Channel layer: web chat. The same orchestrator/memory/actions stack would
back a voice or SMS channel too -- only this transport file would change.
"""
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import store
from app.memory import Session
from app.orchestrator import run_turn

app = FastAPI(title="Bookly Support Agent")

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SESSIONS: dict[str, Session] = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


@app.get("/")
def storefront():
    """The Bookly storefront, with the support agent embedded as a floating
    widget (static/widget.js + widget.css) -- this is the actual "embed a
    chatbot on a real site" deliverable."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/chat")
def standalone_chat():
    """The agent as a full-page chat, no storefront around it -- useful for
    testing the agent in isolation."""
    return FileResponse(STATIC_DIR / "chat.html")


@app.get("/contact")
def contact():
    """A second page with the same embedded widget, to prove the widget is
    genuinely page-agnostic and not wired specifically to the storefront."""
    return FileResponse(STATIC_DIR / "contact.html")


@app.get("/api/catalog")
def catalog():
    return store.CATALOG


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    session = SESSIONS.setdefault(session_id, Session())
    reply = run_turn(session, req.message)
    return ChatResponse(session_id=session_id, reply=reply)


@app.post("/api/reset")
def reset(session_id: str):
    SESSIONS.pop(session_id, None)
    return {"ok": True}
