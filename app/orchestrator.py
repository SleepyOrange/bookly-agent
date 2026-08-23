"""Orchestration layer: the reasoning loop, and the whole orchestrator --
no agent framework underneath it. A turn is a small loop: call the model,
and if it asks for tool(s), dispatch them locally against the knowledge /
actions / handoff layers and feed the results back, until the model produces
a final reply or we hit a safety cap on tool iterations.
"""
import json
import logging
import os

from anthropic import Anthropic

from app import actions, handoff, knowledge, memory
from app.memory import Session
from app.prompts import SYSTEM_PROMPT

logger = logging.getLogger("bookly.orchestrator")

MODEL = os.environ.get("BOOKLY_MODEL", "claude-sonnet-5")
MAX_TOOL_ITERATIONS = 6

# The orchestrator doesn't know or care which layer a tool lives in -- it
# just needs a flat schema list + dispatch table. The layering is for
# humans (and org boundaries in a real deployment), not the model.
TOOLS = knowledge.TOOLS + actions.TOOLS + handoff.TOOLS
DISPATCH = {**knowledge.DISPATCH, **actions.DISPATCH, **handoff.DISPATCH}

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _run_tool(name: str, tool_input: dict) -> dict:
    fn = DISPATCH.get(name)
    if not fn:
        # The model asked for a tool that isn't registered -- a schema drift
        # bug (TOOLS/DISPATCH out of sync), not a customer-facing failure.
        logger.warning("Model requested unknown tool %r with input %r", name, tool_input)
        return {"error": "unknown_tool", "message": f"No such tool: {name}"}
    try:
        return fn(**tool_input)
    except TypeError as e:
        # Usually a schema/signature mismatch (model passed args the function
        # doesn't accept) -- worth a log line to catch drift early, but not
        # a full traceback since it's an expected, recoverable shape.
        logger.warning("Tool %r called with bad arguments %r: %s", name, tool_input, e)
        return {"error": "bad_arguments", "message": str(e)}
    except Exception:
        # Defensive: never let a tool crash the conversation -- but log the
        # full traceback here, since this is the ONLY place an unexpected
        # bug inside a tool would otherwise surface. Without this, the model
        # just sees an opaque error dict and improvises a reply, and nothing
        # ever reaches the server logs to debug from.
        logger.exception("Tool %r raised an unexpected exception with input %r", name, tool_input)
        return {"error": "tool_error", "message": "Something went wrong completing that action."}


def run_turn(session: Session, user_message: str) -> str:
    session.messages.append({"role": "user", "content": user_message})
    client = _get_client()

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=memory.system_context(session, SYSTEM_PROMPT),
            tools=TOOLS,
            messages=session.messages,
        )
        session.messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text")

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _run_tool(block.name, block.input)
            memory.update_case_state(session, block.name, block.input, result)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )
        session.messages.append({"role": "user", "content": tool_results})

    return "I'm having trouble completing that right now -- let me loop in a human specialist for you."
