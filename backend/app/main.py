import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.graph import build_graph
from app.agent.prompts import SYSTEM_PROMPT
from app.config import get_settings
from app.db import close_pool, init_pool
from app.schemas import (
    ChatRequest,
    ComponentEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    ToolStartEvent,
)

# Which UI component each tool's result renders as.
TOOL_COMPONENT_KIND: dict[str, str] = {
    "search_part_by_sku": "product_card",
    "search_by_symptom": "product_card",
    "get_part_detail": "install_steps",
    "get_model_info": "model_info",
    "list_parts_for_model": "product_card",
    "check_compatibility": "compatibility",
    "find_symptoms_for_model": "symptom_parts",
    "search_model_qa": "qa_results",
    "escalate_to_human": "escalation",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="PartSelect Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _sse(payload: Any) -> str:
    return f"data: {payload.model_dump_json()}\n\n"


def _coerce_tool_output(output: Any) -> dict[str, Any] | None:
    if isinstance(output, ToolMessage):
        output = output.content
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"text": output}
    return None


def _to_lc_messages(req: ChatRequest) -> list:
    messages: list = [SystemMessage(content=SYSTEM_PROMPT)]
    for m in req.messages:
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            messages.append(AIMessage(content=m.content))
    return messages


async def _event_stream(req: ChatRequest) -> AsyncIterator[str]:
    graph = build_graph()
    inputs = {"messages": _to_lc_messages(req)}
    try:
        async for event in graph.astream_events(inputs, version="v2"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield _sse(TokenEvent(delta=chunk.content))
            elif kind == "on_tool_start":
                yield _sse(
                    ToolStartEvent(
                        name=event["name"],
                        args=event["data"].get("input", {}),
                    )
                )
            elif kind == "on_tool_end":
                comp_kind = TOOL_COMPONENT_KIND.get(event["name"])
                data = _coerce_tool_output(event["data"].get("output"))
                if comp_kind and data is not None:
                    yield _sse(ComponentEvent(kind=comp_kind, data=data))
        yield _sse(DoneEvent())
    except Exception as exc:  # surface failures to the client stream
        yield _sse(ErrorEvent(message=str(exc)))


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
