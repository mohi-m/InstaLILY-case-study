from typing import Any, Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


# ---- SSE event envelopes (the contract the frontend consumes) ----

ComponentKind = Literal[
    "product_card",
    "install_steps",
    "compatibility",
    "model_info",
    "symptom_parts",
    "qa_results",
    "escalation",
]


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    delta: str


class ToolStartEvent(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    name: str
    args: dict[str, Any]


class ComponentEvent(BaseModel):
    type: Literal["component"] = "component"
    kind: ComponentKind
    data: dict[str, Any]


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
