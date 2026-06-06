from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from uk_jamaat_directory.config import Settings

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_RPM = 30
_DEFAULT_BURST = 5


class GroqRateLimitError(Exception):
    """Raised when Groq returns a 429 even after retries."""


class GroqError(Exception):
    """Raised for non-2xx Groq responses or JSON decode failures."""


class GroqRateLimiter:
    """Async token-bucket limiter enforcing a global RPM ceiling.

    Defaults to 30 RPM with a burst of 5.
    """

    def __init__(self, rpm: int = _DEFAULT_RPM, burst: int = _DEFAULT_BURST) -> None:
        self._tokens = float(burst)
        self._capacity = float(burst)
        self._refill_rate = rpm / 60.0  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._refill_rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last_refill = time.monotonic()
            else:
                self._tokens -= 1.0


# Module singleton: shared across CLI, API, and tasks.
_default_limiter = GroqRateLimiter()


@dataclass(frozen=True)
class GroqMessage:
    role: str
    content: str


async def groq_chat_completion(
    messages: list[GroqMessage],
    *,
    model: str,
    response_format: dict[str, str] | None = None,
    settings: Settings | None = None,
    limiter: GroqRateLimiter | None = None,
) -> dict[str, Any]:
    """Send a chat-completion request to Groq with rate-limiting and one retry on 429.

    Args:
        messages: List of GroqMessage objects.
        model: Model name, e.g. "llama-3.1-8b-instant".
        response_format: Optional Groq response_format dict (e.g. {"type": "json_object"}).
        settings: Project settings; uses groq_api_key and ai_max_tokens.
        limiter: Token-bucket limiter; defaults to the module singleton.

    Returns:
        Parsed JSON response body as a dict.

    Raises:
        GroqRateLimitError: After a 429 retry still fails.
        GroqError: For other non-2xx responses or JSON decode failures.
    """
    cfg = settings or Settings()  # pragma: no cover
    api_key = cfg.groq_api_key
    if not api_key:
        raise GroqError("groq_api_key is not configured")

    lim = limiter or _default_limiter
    await lim.acquire()

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "max_tokens": cfg.ai_max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=cfg.ai_profiling_timeout_seconds) as client:
        response = await client.post(_GROQ_API_URL, headers=headers, json=payload)

        if response.status_code == 429:
            raise GroqRateLimitError(
                f"Groq rate limited after retry (429). Body: {response.text[:200]}"
            )

        if response.status_code >= 400:
            raise GroqError(f"Groq API error {response.status_code}: {response.text[:500]}")

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise GroqError(f"Failed to decode Groq response as JSON: {exc}") from exc

        return data
