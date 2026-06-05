"""Retry behaviour for GeminiProvider — 429 is retried, other 4xx fail fast."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from google.genai.errors import ClientError, ServerError

from micro_x_agent_loop.providers.gemini_provider import GeminiProvider, _is_retryable_gemini_error


def _err(cls: type[Exception], code: int) -> Exception:
    e = cls.__new__(cls)
    e.code = code  # type: ignore[attr-defined]
    e.message = ""  # type: ignore[attr-defined]
    e.status = ""  # type: ignore[attr-defined]
    return e


class PredicateTests(unittest.TestCase):
    def test_rate_limit_is_retryable(self) -> None:
        self.assertTrue(_is_retryable_gemini_error(_err(ClientError, 429)))

    def test_server_error_is_retryable(self) -> None:
        self.assertTrue(_is_retryable_gemini_error(_err(ServerError, 500)))
        self.assertTrue(_is_retryable_gemini_error(_err(ServerError, 503)))

    def test_other_client_errors_not_retryable(self) -> None:
        self.assertFalse(_is_retryable_gemini_error(_err(ClientError, 400)))
        self.assertFalse(_is_retryable_gemini_error(_err(ClientError, 403)))
        self.assertFalse(_is_retryable_gemini_error(_err(ClientError, 404)))

    def test_non_api_errors_not_retryable(self) -> None:
        self.assertFalse(_is_retryable_gemini_error(ValueError("boom")))


def _make_provider() -> GeminiProvider:
    """Build a provider without touching the real google-genai Client."""
    with patch("google.genai.Client", return_value=SimpleNamespace()):
        return GeminiProvider(api_key="test-key")


def _fake_response() -> SimpleNamespace:
    return SimpleNamespace(
        text="OK",
        usage_metadata=SimpleNamespace(
            prompt_token_count=5,
            candidates_token_count=2,
            cached_content_token_count=0,
        ),
    )


class CreateMessageRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Make tenacity's backoff instant so the 10s exponential wait doesn't
        # slow the suite; the retry still goes through its real decision path.
        self._sleep_patch = patch("asyncio.sleep", new=AsyncMock())
        self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

    async def _run(self, side_effect: Any) -> tuple[str, Any, int]:
        provider = _make_provider()
        gen = AsyncMock(side_effect=side_effect)
        provider._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=gen)))
        result = await provider.create_message(
            model="gemini-2.5-flash",
            max_tokens=64,
            temperature=0.0,
            messages=[{"role": "user", "content": "hi"}],
        )
        return result[0], result[1], gen.await_count

    async def test_retries_on_429_then_succeeds(self) -> None:
        text, _usage, calls = await self._run([_err(ClientError, 429), _fake_response()])
        self.assertEqual("OK", text)
        self.assertEqual(2, calls)  # failed once, retried, succeeded

    async def test_does_not_retry_on_400(self) -> None:
        with self.assertRaises(ClientError):
            await self._run([_err(ClientError, 400), _fake_response()])

    async def test_does_not_retry_on_404(self) -> None:
        provider = _make_provider()
        gen = AsyncMock(side_effect=_err(ClientError, 404))
        provider._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=gen)))
        with self.assertRaises(ClientError):
            await provider.create_message(
                model="gemini-2.5-flash",
                max_tokens=64,
                temperature=0.0,
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(1, gen.await_count)  # no retry on permanent error


if __name__ == "__main__":
    unittest.main()
