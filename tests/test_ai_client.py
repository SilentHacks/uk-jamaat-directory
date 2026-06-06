from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.extract.ai.client import (
    GroqError,
    GroqMessage,
    GroqRateLimiter,
    GroqRateLimitError,
    groq_chat_completion,
)


class TestGroqRateLimiter:
    @pytest.mark.asyncio
    async def test_burst_allows_immediate_calls(self):
        limiter = GroqRateLimiter(rpm=30, burst=3)
        # First 3 should pass immediately
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()
        # 4th should have to wait
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 1.8  # ~2s refill for 1 token at 30 RPM

    @pytest.mark.asyncio
    async def test_steady_state_rate(self):
        limiter = GroqRateLimiter(rpm=60, burst=1)
        times = []
        for _ in range(3):
            t0 = asyncio.get_event_loop().time()
            await limiter.acquire()
            times.append(asyncio.get_event_loop().time() - t0)
        # First call immediate, subsequent calls wait ~1s each
        assert times[0] < 0.1
        assert times[1] >= 0.9
        assert times[2] >= 0.9

    @pytest.mark.asyncio
    async def test_global_singleton_shared(self):
        from uk_jamaat_directory.ingest.extract.ai.client import _default_limiter

        limiter1 = _default_limiter
        limiter2 = _default_limiter
        assert limiter1 is limiter2


class TestGroqChatCompletion:
    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self):
        settings = Settings(groq_api_key=None)
        with pytest.raises(GroqError, match="groq_api_key is not configured"):
            await groq_chat_completion(
                [GroqMessage(role="user", content="hello")],
                model="llama-3.1-8b-instant",
                settings=settings,
            )

    @pytest.mark.asyncio
    async def test_successful_response_parsed(self):
        settings = Settings(groq_api_key="test-key")
        fake_response = {"choices": [{"message": {"content": '{"asset_type": "html_table"}'}}]}

        mock_post = AsyncMock()
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = lambda: fake_response

        with patch("httpx.AsyncClient.post", new=mock_post):
            result = await groq_chat_completion(
                [GroqMessage(role="user", content="hello")],
                model="llama-3.1-8b-instant",
                settings=settings,
            )

        assert result == fake_response
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(self):
        settings = Settings(groq_api_key="test-key")
        mock_post = AsyncMock(return_value=AsyncMock(status_code=429, text="rate limited"))

        with patch("httpx.AsyncClient.post", new=mock_post):
            with pytest.raises(GroqRateLimitError):
                await groq_chat_completion(
                    [GroqMessage(role="user", content="hello")],
                    model="llama-3.1-8b-instant",
                    settings=settings,
                )

        assert mock_post.call_count == 1

    @pytest.mark.asyncio
    async def test_4xx_raises_groq_error(self):
        settings = Settings(groq_api_key="test-key")

        mock_post = AsyncMock(return_value=AsyncMock(status_code=400, text="bad request"))

        with patch("httpx.AsyncClient.post", new=mock_post):
            with pytest.raises(GroqError, match="Groq API error 400"):
                await groq_chat_completion(
                    [GroqMessage(role="user", content="hello")],
                    model="llama-3.1-8b-instant",
                    settings=settings,
                )

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self):
        settings = Settings(groq_api_key="test-key")

        def _bad_json():
            raise json.JSONDecodeError("bad json", "", 0)

        mock_post = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=_bad_json,
            )
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            with pytest.raises(GroqError, match="Failed to decode Groq response"):
                await groq_chat_completion(
                    [GroqMessage(role="user", content="hello")],
                    model="llama-3.1-8b-instant",
                    settings=settings,
                )

    @pytest.mark.asyncio
    async def test_empty_content_returns_data(self):
        settings = Settings(groq_api_key="test-key")

        class _FakeResponse:
            status_code = 200
            text = "ok"

            def json(self):
                return {"choices": [{"message": {"content": ""}}]}

        mock_post = AsyncMock(return_value=_FakeResponse())

        with patch("httpx.AsyncClient.post", new=mock_post):
            result = await groq_chat_completion(
                [GroqMessage(role="user", content="hello")],
                model="llama-3.1-8b-instant",
                settings=settings,
            )

        assert result == {"choices": [{"message": {"content": ""}}]}

    @pytest.mark.asyncio
    async def test_rate_limiter_is_invoked(self):
        settings = Settings(groq_api_key="test-key")
        limiter = GroqRateLimiter(rpm=30, burst=5)
        limiter.acquire = AsyncMock()

        mock_post = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": "{}"}}]},
            )
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            await groq_chat_completion(
                [GroqMessage(role="user", content="hello")],
                model="llama-3.1-8b-instant",
                settings=settings,
                limiter=limiter,
            )

        limiter.acquire.assert_awaited_once()
