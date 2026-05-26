from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.agent.tools import ALL_TOOLS
from app.config import get_settings


@lru_cache
def get_llm() -> ChatOpenAI:
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        streaming=True,
        temperature=0,
    )
    return llm.bind_tools(ALL_TOOLS)
