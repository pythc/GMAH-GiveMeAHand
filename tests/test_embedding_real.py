"""Tests for OpenAICompatibleEmbeddingModel and CrossEncoderReranker."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from agent_workflow.rag.embeddings import (
    CrossEncoderReranker,
    EmbeddingModelError,
    OpenAICompatibleEmbeddingModel,
    RerankerError,
)

# ---------------------------------------------------------------------------
# OpenAICompatibleEmbeddingModel tests
# ---------------------------------------------------------------------------


class TestOpenAICompatibleEmbeddingModel:
    """Tests for the OpenAI-compatible embedding model."""

    def _make_model(self, client: httpx.Client) -> OpenAICompatibleEmbeddingModel:
        return OpenAICompatibleEmbeddingModel(
            base_url="https://api.example.com/v1",
            model="text-embedding-3-small",
            api_key="test-key-123",
            dimension=128,
            client=client,
        )

    def _mock_response(self, embeddings: list[list[float]], status: int = 200) -> httpx.Response:
        """Create a mock embedding API response."""
        data = [
            {"object": "embedding", "index": i, "embedding": emb}
            for i, emb in enumerate(embeddings)
        ]
        body = {"object": "list", "data": data, "model": "text-embedding-3-small"}
        request = httpx.Request("POST", "https://api.example.com/v1/embeddings")
        return httpx.Response(status_code=status, json=body, request=request)

    def test_embed_single_text(self) -> None:
        """embed() should return a single vector for one text."""
        expected = [0.1] * 128
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_response([expected])

        model = self._make_model(mock_client)
        result = model.embed("hello world")

        assert result == expected
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "/embeddings" in call_kwargs[0][0]
        payload = call_kwargs[1]["json"]
        assert payload["input"] == ["hello world"]
        assert payload["model"] == "text-embedding-3-small"
        assert payload["dimensions"] == 128

    def test_embed_batch_multiple_texts(self) -> None:
        """embed_batch() should return vectors for multiple texts."""
        embeddings = [[0.1] * 128, [0.2] * 128, [0.3] * 128]
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_response(embeddings)

        model = self._make_model(mock_client)
        results = model.embed_batch(["hello", "world", "test"])

        assert len(results) == 3
        assert results[0] == [0.1] * 128
        assert results[1] == [0.2] * 128
        assert results[2] == [0.3] * 128

    def test_embed_batch_empty_list(self) -> None:
        """embed_batch() with empty list should return empty without API call."""
        mock_client = MagicMock(spec=httpx.Client)
        model = self._make_model(mock_client)

        results = model.embed_batch([])

        assert results == []
        mock_client.post.assert_not_called()

    def test_embed_batch_preserves_order_from_shuffled_response(self) -> None:
        """embed_batch() should sort by index even if API returns out of order."""
        # Simulate API returning results in reverse order
        data = [
            {"object": "embedding", "index": 2, "embedding": [0.3] * 128},
            {"object": "embedding", "index": 0, "embedding": [0.1] * 128},
            {"object": "embedding", "index": 1, "embedding": [0.2] * 128},
        ]
        body = {"object": "list", "data": data, "model": "text-embedding-3-small"}
        request = httpx.Request("POST", "https://api.example.com/v1/embeddings")
        response = httpx.Response(status_code=200, json=body, request=request)

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = response

        model = self._make_model(mock_client)
        results = model.embed_batch(["a", "b", "c"])

        assert results[0] == [0.1] * 128
        assert results[1] == [0.2] * 128
        assert results[2] == [0.3] * 128

    def test_embed_raises_on_http_error(self) -> None:
        """embed() should raise EmbeddingModelError on HTTP error status."""
        mock_client = MagicMock(spec=httpx.Client)
        error_response = httpx.Response(
            status_code=429,
            text="Rate limited",
            request=httpx.Request("POST", "https://api.example.com/v1/embeddings"),
        )
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "rate limited", request=error_response.request, response=error_response
        )

        model = self._make_model(mock_client)

        with pytest.raises(EmbeddingModelError, match="status 429"):
            model.embed("hello")

    def test_embed_raises_on_connection_error(self) -> None:
        """embed() should raise EmbeddingModelError on network errors."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        model = self._make_model(mock_client)

        with pytest.raises(EmbeddingModelError, match="request failed"):
            model.embed("hello")

    def test_embed_raises_on_timeout(self) -> None:
        """embed() should raise EmbeddingModelError on timeout."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.side_effect = httpx.ReadTimeout("Read timed out")

        model = self._make_model(mock_client)

        with pytest.raises(EmbeddingModelError, match="request failed"):
            model.embed("hello")

    def test_embed_raises_on_malformed_response(self) -> None:
        """embed() should raise EmbeddingModelError when response has no data."""
        body = {"object": "list", "model": "text-embedding-3-small"}
        request = httpx.Request("POST", "https://api.example.com/v1/embeddings")
        response = httpx.Response(status_code=200, json=body, request=request)

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = response

        model = self._make_model(mock_client)

        with pytest.raises(EmbeddingModelError, match="missing 'data'"):
            model.embed("hello")

    def test_sends_authorization_header(self) -> None:
        """Should send Bearer token in Authorization header."""
        expected = [0.1] * 128
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_response([expected])

        model = self._make_model(mock_client)
        model.embed("test")

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["authorization"] == "Bearer test-key-123"

    def test_dimension_attribute(self) -> None:
        """Model should expose dimension attribute matching configured value."""
        mock_client = MagicMock(spec=httpx.Client)
        model = self._make_model(mock_client)
        assert model.dimension == 128


# ---------------------------------------------------------------------------
# CrossEncoderReranker tests
# ---------------------------------------------------------------------------


class TestCrossEncoderReranker:
    """Tests for the cross-encoder reranker."""

    def _make_reranker(self, client: httpx.Client) -> CrossEncoderReranker:
        return CrossEncoderReranker(
            base_url="https://api.example.com/v1",
            model="gpt-4o-mini",
            api_key="test-key-456",
            client=client,
        )

    def _mock_chat_response(self, score: str) -> httpx.Response:
        """Create a mock chat completion response with a score."""
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": score},
                    "finish_reason": "stop",
                }
            ],
        }
        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        return httpx.Response(status_code=200, json=body, request=request)

    def test_rerank_returns_sorted_results(self) -> None:
        """rerank() should return documents sorted by descending score."""
        mock_client = MagicMock(spec=httpx.Client)
        # Return different scores for each document
        mock_client.post.side_effect = [
            self._mock_chat_response("0.3"),
            self._mock_chat_response("0.9"),
            self._mock_chat_response("0.6"),
        ]

        reranker = self._make_reranker(mock_client)
        results = reranker.rerank(
            "python programming",
            ["doc about java", "doc about python", "doc about rust"],
        )

        assert len(results) == 3
        # Highest score first
        assert results[0].score == pytest.approx(0.9)
        assert results[0].index == 1
        assert results[0].content == "doc about python"
        # Second
        assert results[1].score == pytest.approx(0.6)
        assert results[1].index == 2
        # Lowest
        assert results[2].score == pytest.approx(0.3)
        assert results[2].index == 0

    def test_rerank_with_top_k(self) -> None:
        """rerank() with top_k should return only top_k results."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.side_effect = [
            self._mock_chat_response("0.2"),
            self._mock_chat_response("0.8"),
            self._mock_chat_response("0.5"),
        ]

        reranker = self._make_reranker(mock_client)
        results = reranker.rerank("query", ["a", "b", "c"], top_k=2)

        assert len(results) == 2
        assert results[0].score == pytest.approx(0.8)
        assert results[1].score == pytest.approx(0.5)

    def test_rerank_empty_documents(self) -> None:
        """rerank() with empty list should return empty without API calls."""
        mock_client = MagicMock(spec=httpx.Client)
        reranker = self._make_reranker(mock_client)

        results = reranker.rerank("query", [])

        assert results == []
        mock_client.post.assert_not_called()

    def test_rerank_clamps_score_above_one(self) -> None:
        """Scores above 1.0 should be clamped to 1.0."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_chat_response("1.5")

        reranker = self._make_reranker(mock_client)
        results = reranker.rerank("query", ["doc"])

        assert results[0].score == 1.0

    def test_rerank_handles_score_with_text(self) -> None:
        """Should extract score even if model returns extra text."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_chat_response("Score: 0.75")

        reranker = self._make_reranker(mock_client)
        results = reranker.rerank("query", ["doc"])

        assert results[0].score == pytest.approx(0.75)

    def test_rerank_handles_no_score_in_response(self) -> None:
        """Should return 0.0 if no number found in response."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_chat_response("I cannot score this.")

        reranker = self._make_reranker(mock_client)
        results = reranker.rerank("query", ["doc"])

        assert results[0].score == 0.0

    def test_rerank_raises_on_http_error(self) -> None:
        """Should raise RerankerError on HTTP errors."""
        mock_client = MagicMock(spec=httpx.Client)
        error_response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        )
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "server error", request=error_response.request, response=error_response
        )

        reranker = self._make_reranker(mock_client)

        with pytest.raises(RerankerError, match="status 500"):
            reranker.rerank("query", ["doc"])

    def test_rerank_raises_on_network_error(self) -> None:
        """Should raise RerankerError on network errors."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        reranker = self._make_reranker(mock_client)

        with pytest.raises(RerankerError, match="request failed"):
            reranker.rerank("query", ["doc"])

    def test_rerank_sends_correct_payload(self) -> None:
        """Should send properly formatted chat completion request."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_chat_response("0.8")

        reranker = self._make_reranker(mock_client)
        reranker.rerank("what is python?", ["Python is a language"])

        call_kwargs = mock_client.post.call_args
        assert "/chat/completions" in call_kwargs[0][0]
        payload = call_kwargs[1]["json"]
        assert payload["model"] == "gpt-4o-mini"
        assert payload["temperature"] == 0.0
        assert payload["max_tokens"] == 10
        messages = payload["messages"]
        assert len(messages) == 1
        assert "what is python?" in messages[0]["content"]
        assert "Python is a language" in messages[0]["content"]

    def test_rerank_sends_authorization_header(self) -> None:
        """Should send Bearer token in Authorization header."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = self._mock_chat_response("0.5")

        reranker = self._make_reranker(mock_client)
        reranker.rerank("query", ["doc"])

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["authorization"] == "Bearer test-key-456"
