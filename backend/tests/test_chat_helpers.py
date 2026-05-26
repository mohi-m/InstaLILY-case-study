import json

from langchain_core.messages import SystemMessage, ToolMessage

from app.main import _coerce_tool_output, _to_lc_messages
from app.schemas import ChatRequest


def test_coerce_handles_dict():
    assert _coerce_tool_output({"found": True}) == {"found": True}


def test_coerce_parses_json_string():
    assert _coerce_tool_output(json.dumps({"a": 1})) == {"a": 1}


def test_coerce_parses_tool_message():
    msg = ToolMessage(content=json.dumps({"compatible": True}), tool_call_id="x")
    assert _coerce_tool_output(msg) == {"compatible": True}


def test_system_prompt_prepended_with_scope_rule():
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}])
    msgs = _to_lc_messages(req)
    assert isinstance(msgs[0], SystemMessage)
    assert "Refrigerator" in msgs[0].content and "Dishwasher" in msgs[0].content
    # Out-of-scope guardrail must be stated.
    assert "decline" in msgs[0].content.lower()
