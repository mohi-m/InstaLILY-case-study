from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from app.agent.llm import get_llm
from app.agent.tools import ALL_TOOLS


async def _call_model(state: MessagesState) -> dict:
    response = await get_llm().ainvoke(state["messages"])
    return {"messages": [response]}


def _should_continue(state: MessagesState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


@lru_cache
def build_graph():
    graph = StateGraph(MessagesState)
    graph.add_node("model", _call_model)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile()
