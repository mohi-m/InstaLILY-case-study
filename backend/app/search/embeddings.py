from openai import AsyncOpenAI

from app.config import get_settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _client


# Tiny in-process cache — identical query strings recur within a session.
_embed_cache: dict[str, list[float]] = {}


async def embed_query(text: str) -> list[float]:
    text = text.strip()
    if text in _embed_cache:
        return _embed_cache[text]
    embedding = (await embed_texts([text]))[0]
    _embed_cache[text] = embedding
    return embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    resp = await _get_client().embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in resp.data]
