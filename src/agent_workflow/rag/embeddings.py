"""Embedding interfaces and deterministic local embedding implementation."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

import httpx


class EmbeddingModel(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]:
        """Return a dense vector for text."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return dense vectors for a batch of texts."""


class EmbeddingModelError(RuntimeError):
    """Raised when an embedding API call fails."""


class RerankerError(RuntimeError):
    """Raised when a reranker call fails."""


@dataclass
class ScoredDocument:
    """A document with its relevance score after reranking."""

    index: int
    content: str
    score: float


class Reranker(Protocol):
    """Protocol for reranking retrieved documents by relevance to a query."""

    def rerank(
        self, query: str, documents: list[str], top_k: int | None = None
    ) -> list[ScoredDocument]:
        """Rerank documents by relevance to query, return scored list."""


class HashEmbeddingModel:
    """Deterministic local embedding model for tests and offline development.

    Production deployments can replace this interface with BGE-M3, ColPali, or
    hosted multimodal embeddings without changing the gateway API.
    """

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0 for _ in range(self.dimension)]
        tokens = [token for token in text.lower().split() if token]
        if not tokens:
            tokens = [text]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return normalize(vector)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class OpenAICompatibleEmbeddingModel:
    """Embedding model using an OpenAI-compatible /embeddings API endpoint.

    Supports providers like OpenAI, Azure OpenAI, Volcengine Ark, and any
    other service exposing the standard /v1/embeddings interface.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        dimension: int = 1536,
        timeout_seconds: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        results = self.embed_batch([text])
        return results[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings in a single API call."""
        if not texts:
            return []

        headers: dict[str, str] = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, object] = {
            "model": self.model,
            "input": texts,
            "dimensions": self.dimension,
        }

        try:
            response = self._client.post(
                f"{self.base_url}/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise EmbeddingModelError(
                f"Embedding API returned status {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise EmbeddingModelError(
                f"Embedding API request failed: {exc}"
            ) from exc

        body = response.json()
        data = body.get("data")
        if not isinstance(data, list):
            raise EmbeddingModelError(
                "Embedding API response missing 'data' array"
            )

        # Sort by index to preserve input order
        sorted_data = sorted(data, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in sorted_data]


class CrossEncoderReranker:
    """Reranker using an OpenAI-compatible chat API for relevance scoring.

    Sends query-document pairs to a chat model with a scoring prompt and
    parses the 0-1 relevance score from the model's response.
    """

    SCORING_PROMPT_TEMPLATE = (
        "You are a relevance scoring system. Given a query and a document, "
        "output ONLY a single floating-point number between 0.0 and 1.0 "
        "representing how relevant the document is to the query. "
        "0.0 means completely irrelevant, 1.0 means perfectly relevant.\n\n"
        "Query: {query}\n\n"
        "Document: {document}\n\n"
        "Relevance score:"
    )

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def rerank(
        self, query: str, documents: list[str], top_k: int | None = None
    ) -> list[ScoredDocument]:
        """Rerank documents by relevance to query using chat-based scoring."""
        if not documents:
            return []

        scored: list[ScoredDocument] = []
        for idx, doc in enumerate(documents):
            score = self._score_pair(query, doc)
            scored.append(ScoredDocument(index=idx, content=doc, score=score))

        scored.sort(key=lambda item: item.score, reverse=True)
        if top_k is not None:
            scored = scored[:top_k]
        return scored

    def _score_pair(self, query: str, document: str) -> float:
        """Score a single query-document pair via chat completion."""
        prompt = self.SCORING_PROMPT_TEMPLATE.format(
            query=query, document=document
        )

        headers: dict[str, str] = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 10,
        }

        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RerankerError(
                f"Reranker API returned status {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise RerankerError(
                f"Reranker API request failed: {exc}"
            ) from exc

        body = response.json()
        return self._parse_score(body)

    def _parse_score(self, body: dict[str, object]) -> float:
        """Extract a float score from a chat completion response."""
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return 0.0
        first = choices[0]
        if not isinstance(first, dict):
            return 0.0
        message = first.get("message")
        if not isinstance(message, dict):
            return 0.0
        content = message.get("content", "")
        if not isinstance(content, str):
            return 0.0

        # Extract first float from response
        match = re.search(r"(\d+\.?\d*)", content.strip())
        if match:
            value = float(match.group(1))
            return max(0.0, min(1.0, value))
        return 0.0


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return max(0.0, sum(a * b for a, b in zip(left, right, strict=False)))
