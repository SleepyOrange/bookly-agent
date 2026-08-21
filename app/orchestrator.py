"""Orchestration layer: the reasoning loop, and the whole orchestrator --
no agent framework underneath it. A turn is a small loop: call the model,
and if it asks for tool(s), dispatch them locally against the knowledge /
actions / handoff layers and feed the results back, until the model produces
a final reply or we hit a safety cap on tool iterations.
"""
import json
import os

from anthropic import Anthropic

from app import actions, handoff, knowledge, memory
from app.memory import Session
from app.prompts import SYSTEM_PROMPT

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
        return {"error": "unknown_tool", "message": f"No such tool: {name}"}
    try:
        return fn(**tool_input)
    except TypeError as e:
        return {"error": "bad_arguments", "message": str(e)}
    except Exception as e:  # defensive: never let a tool crash the conversation
        return {"error": "tool_error", "message": str(e)}


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
