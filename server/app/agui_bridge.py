"""AG-UI bridge: graph.astream_events -> the exact SSE event sequence the client parses.

Wire contract (see PYTHON-BACKEND-PLAN.md, "The wire contract"; reference: agui/server.js):

  text turn:  RUN_STARTED -> TEXT_MESSAGE_START -> TEXT_MESSAGE_CONTENT* -> TEXT_MESSAGE_END -> RUN_FINISHED
  UI turn:    RUN_STARTED -> CUSTOM status -> CUSTOM a2ui -> TEXT_MESSAGE_* (caption) -> RUN_FINISHED
  trace:      STEP_STARTED/FINISHED + TOOL_CALL_START/ARGS/END/RESULT around the above (P7)
  UI action:  forwardedProps.a2uiAction (A2UI client action) instead of a typed message; same events back
  error:      RUN_ERROR { message } (unless the client has gone), then close
  disconnect: stop consuming, no RUN_FINISHED

Only the responder node's tokens become chat text, so the router's classifier
output never leaks. The UI branch reports through custom events dispatched
inside its node ("status", "a2ui", "assistant_text").
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder
from langchain_core.messages import HumanMessage

from .log import RequestLogger, current_log

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_encoder = EventEncoder()
CONTENT_TYPE = _encoder.get_content_type()


@dataclass(frozen=True)
class RunRequest:
    thread_id: str
    run_id: str
    user_text: str
    persona: str | None = None  # RunAgentInput.state.persona (P5); the graph defaults it
    action: dict[str, Any] | None = None  # A2UI client action from forwardedProps.a2uiAction (P6)


def parse_action(forwarded: Any) -> dict[str, Any] | None:
    """The A2UI v0.9 client-to-server message, carried in AG-UI forwardedProps:

        forwardedProps: { a2uiAction: { version: "v0.9", action: {name, surfaceId, sourceComponentId, timestamp, context} } }
    """
    raw = forwarded.get("a2uiAction") if isinstance(forwarded, dict) else None
    action = raw.get("action") if isinstance(raw, dict) and isinstance(raw.get("action"), dict) else raw
    if not isinstance(action, dict) or not isinstance(action.get("name"), str) or not action["name"]:
        return None
    context = action.get("context")
    return {
        "name": action["name"],
        "context": context if isinstance(context, dict) else {},
        "sourceComponentId": str(action.get("sourceComponentId") or ""),
        "surfaceId": str(action.get("surfaceId") or ""),
    }


def describe_action(action: dict[str, Any]) -> str:
    """How a UI action is recorded in chat history, so later turns (and DECIDE) see it."""
    source = f' on "{action["sourceComponentId"]}"' if action.get("sourceComponentId") else ""
    context = json.dumps(action["context"], ensure_ascii=False)
    return f"[UI action] {action['name']}{source} {context[:2000]}"


def parse_run_input(body: Any) -> RunRequest:
    """Lenient RunAgentInput parse.

    The client sends only threadId, runId and messages, so binding to
    ag_ui.core.RunAgentInput would 422. Only the newest user message is used;
    earlier turns come back from the checkpointer by threadId.
    """
    body = body if isinstance(body, dict) else {}
    thread_id = body.get("threadId") or f"thread_{uuid.uuid4()}"
    run_id = body.get("runId") or f"run_{uuid.uuid4()}"
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    last_user = next(
        (m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "user"),
        None,
    )
    content = last_user.get("content") if last_user else None
    state = body.get("state") if isinstance(body.get("state"), dict) else {}
    persona = state.get("persona")
    action = parse_action(body.get("forwardedProps"))
    text = "" if content is None else str(content)
    return RunRequest(
        thread_id=str(thread_id),
        run_id=str(run_id),
        user_text=describe_action(action) if action else text,
        persona=persona if isinstance(persona, str) else None,
        action=action,
    )


def frame(event: BaseEvent) -> str:
    """One SSE frame (`data: <json>\\n\\n`), stamped with epoch ms like the Node server."""
    event.timestamp = int(time.time() * 1000)
    return _encoder.encode(event)


def chunk_text(content: Any) -> str:
    """Plain text out of a message chunk's content (string or list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p if isinstance(p, str) else p.get("text", "") if isinstance(p, dict) and p.get("type") == "text" else ""
            for p in content
        )
    return ""


def whole_text(text: str) -> list[str]:
    """A complete one-shot assistant message (the UI branch's caption or apology)."""
    if not text:
        return []
    mid = f"msg_{uuid.uuid4()}"
    return [
        frame(TextMessageStartEvent(message_id=mid, role="assistant")),
        frame(TextMessageContentEvent(message_id=mid, delta=text)),
        frame(TextMessageEndEvent(message_id=mid)),
    ]


async def stream_run(
    graph: Any,
    req: RunRequest,
    is_disconnected: Callable[[], Awaitable[bool]],
    log: RequestLogger,
) -> AsyncIterator[str]:
    """Run the graph for one turn and yield SSE frames following the wire contract."""
    message_id = f"msg_{uuid.uuid4()}"
    started = False  # emitted TEXT_MESSAGE_START for the streaming path yet?
    deltas = 0
    surfaces = 0
    tools = 0
    current_log.set(log)  # graph nodes log into this request's trace
    try:
        yield frame(RunStartedEvent(thread_id=req.thread_id, run_id=req.run_id))
        log.step("emit RUN_STARTED — invoking graph")

        events = graph.astream_events(
            {"messages": [HumanMessage(req.user_text)], "persona": req.persona or "assistant", "action": req.action},
            {"configurable": {"thread_id": req.thread_id}},
            version="v2",
        )
        async for ev in events:
            if await is_disconnected():
                log.warn(f"client disconnected mid-stream — stopped after {deltas} deltas")
                return

            kind = ev["event"]
            # TEXT branch: only the responder node's tokens become chat text.
            if ev.get("metadata", {}).get("langgraph_node") == "responder":
                if kind == "on_chat_model_start" and not started:
                    yield frame(TextMessageStartEvent(message_id=message_id, role="assistant"))
                    started = True
                    log.step("responder start → TEXT_MESSAGE_START")
                elif kind == "on_chat_model_stream":
                    text = chunk_text(getattr(ev["data"].get("chunk"), "content", None))
                    if text:
                        yield frame(TextMessageContentEvent(message_id=message_id, delta=text))
                        deltas += 1
                continue

            # UI branch: custom events dispatched inside the ui_generator node.
            if kind == "on_custom_event":
                name, data = ev["name"], ev["data"]
                if name == "a2ui":
                    yield frame(CustomEvent(name="a2ui", value=data))
                    surfaces += 1
                    log.step(f"ui_generator → CUSTOM a2ui ({len(data.get('a2ui') or [])} message(s))")
                elif name == "assistant_text":
                    for f in whole_text(data.get("text", "")):
                        yield f
                    log.step("ui_generator → TEXT_MESSAGE (caption/fallback)")
                elif name == "status":
                    # Transient progress note (e.g. "Generating UI…"); not chat history.
                    yield frame(CustomEvent(name="status", value=data))
                # Trace (P7): steps and tool activity -> standard AG-UI events for the trace panel.
                elif name == "trace_step":
                    cls = StepStartedEvent if data["phase"] == "start" else StepFinishedEvent
                    yield frame(cls(step_name=data["name"]))
                elif name == "trace_tool_start":
                    yield frame(ToolCallStartEvent(tool_call_id=data["id"], tool_call_name=data["name"]))
                    yield frame(ToolCallArgsEvent(tool_call_id=data["id"], delta=json.dumps(data["args"], ensure_ascii=False, default=str)))
                    yield frame(ToolCallEndEvent(tool_call_id=data["id"]))
                elif name == "trace_tool_end":
                    yield frame(ToolCallResultEvent(
                        message_id=f"result_{data['id']}",
                        tool_call_id=data["id"],
                        content=json.dumps(data["result"], ensure_ascii=False, default=str),
                        role="tool",
                    ))
                    tools += 1

        if started:
            yield frame(TextMessageEndEvent(message_id=message_id))
        yield frame(RunFinishedEvent(thread_id=req.thread_id, run_id=req.run_id))
        log.done(f"streamed {deltas} text delta(s), {surfaces} surface(s), {tools} traced call(s) → RUN_FINISHED")
    except asyncio.CancelledError:
        # Starlette cancels the response task when the client goes away.
        log.warn(f"client disconnected mid-stream — stopped after {deltas} deltas")
        raise
    except Exception as err:  # noqa: BLE001 — any failure becomes RUN_ERROR
        log.fail(f"graph/stream error — {err}")
        if not await is_disconnected():
            yield frame(RunErrorEvent(message=str(err) or "stream error"))
