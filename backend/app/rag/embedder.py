"""Text embedders: OpenAI for real use, a deterministic hashing embedder for tests and offline runs."""

import hashlib
import math
import re
from typing import Protocol

from openai import AsyncOpenAI

from app.config import Settings

_WORD = re.compile(r"[a-z0-9$]+")


class Embedder(Protocol):
    model_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(self, settings: Settings, batch_size: int = 64) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model_name = settings.embedding_model
        self._batch_size = batch_size
        self.last_usage_tokens = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        self.last_usage_tokens = 0
        for i in range(0, len(texts), self._batch_size):
            resp = await self._client.embeddings.create(model=self.model_name, input=texts[i : i + self._batch_size])
            out.extend(d.embedding for d in resp.data)
            self.last_usage_tokens += resp.usage.prompt_tokens
        return out


class HashEmbedder:
    """Deterministic bag-of-words (plus bigrams) hashing vectors, L2-normalised. No network, no randomness."""

    model_name = "hash-embedder"

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim
        self.last_usage_tokens = 0

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            words = _WORD.findall(text.lower())
            vec = [0.0] * self.dim
            for term in words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]:
                vec[int(hashlib.md5(term.encode()).hexdigest(), 16) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vectors.append([x / norm for x in vec])
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_sync(texts)
