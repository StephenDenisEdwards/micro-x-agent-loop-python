"""Tests for broker channel adapters."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.broker.channels import (
    HttpAdapter,
    LogAdapter,
    TelegramAdapter,
    TriggerFilter,
    WhatsAppAdapter,
    build_adapters,
    build_trigger_filter,
)
from micro_x_agent_loop.broker.runner import RunResult

# ---------------------------------------------------------------------------
# TriggerFilter
# ---------------------------------------------------------------------------


class TriggerFilterMatchesTests(unittest.TestCase):
    def test_empty_filter_accepts_all(self) -> None:
        f = TriggerFilter()
        result = f.matches("chat1", "user1", "hello")
        self.assertEqual("hello", result)

    def test_chat_ids_filter_passes(self) -> None:
        f = TriggerFilter(chat_ids=["chat1"])
        result = f.matches("chat1", "user1", "hi")
        self.assertEqual("hi", result)

    def test_chat_ids_filter_rejects(self) -> None:
        f = TriggerFilter(chat_ids=["chat1"])
        result = f.matches("other", "user1", "hi")
        self.assertIsNone(result)

    def test_chat_ids_filter_rejects_none_chat(self) -> None:
        f = TriggerFilter(chat_ids=["chat1"])
        result = f.matches(None, "user1", "hi")
        self.assertIsNone(result)

    def test_sender_ids_filter_passes(self) -> None:
        f = TriggerFilter(sender_ids=["alice"])
        result = f.matches(None, "alice", "hello")
        self.assertEqual("hello", result)

    def test_sender_ids_filter_rejects(self) -> None:
        f = TriggerFilter(sender_ids=["alice"])
        result = f.matches(None, "bob", "hello")
        self.assertIsNone(result)

    def test_prefix_filter_passes_and_strips(self) -> None:
        f = TriggerFilter(prefix="/agent ")
        result = f.matches(None, "user", "/agent do something")
        self.assertEqual("do something", result)

    def test_prefix_filter_rejects_non_matching(self) -> None:
        f = TriggerFilter(prefix="/agent ")
        result = f.matches(None, "user", "just a message")
        self.assertIsNone(result)

    def test_prefix_stripped_to_empty_returns_none(self) -> None:
        f = TriggerFilter(prefix="/agent")
        result = f.matches(None, "user", "/agent")
        self.assertIsNone(result)

    def test_combined_all_must_match(self) -> None:
        f = TriggerFilter(chat_ids=["c1"], sender_ids=["u1"], prefix="/bot ")
        self.assertEqual("go", f.matches("c1", "u1", "/bot go"))
        self.assertIsNone(f.matches("c2", "u1", "/bot go"))  # wrong chat
        self.assertIsNone(f.matches("c1", "u2", "/bot go"))  # wrong sender
        self.assertIsNone(f.matches("c1", "u1", "no prefix"))  # no prefix

    def test_empty_text_after_strip_returns_none(self) -> None:
        f = TriggerFilter()
        f.matches(None, "u", "   ")
        # Empty text after strip
        result2 = f.matches(None, "u", "hello")
        self.assertIsNotNone(result2)


class TriggerFilterIsEmptyTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertTrue(TriggerFilter().is_empty)

    def test_not_empty_with_chat_ids(self) -> None:
        self.assertFalse(TriggerFilter(chat_ids=["c"]).is_empty)

    def test_not_empty_with_sender_ids(self) -> None:
        self.assertFalse(TriggerFilter(sender_ids=["u"]).is_empty)

    def test_not_empty_with_prefix(self) -> None:
        self.assertFalse(TriggerFilter(prefix="/bot").is_empty)


# ---------------------------------------------------------------------------
# HttpAdapter
# ---------------------------------------------------------------------------


class HttpAdapterTests(unittest.TestCase):
    def test_channel_name(self) -> None:
        a = HttpAdapter()
        self.assertEqual("http", a.channel_name)

    def test_supports_webhook(self) -> None:
        self.assertTrue(HttpAdapter().supports_webhook)

    def test_supports_polling(self) -> None:
        self.assertFalse(HttpAdapter().supports_polling)

    def test_verify_request_no_secret(self) -> None:
        a = HttpAdapter()
        self.assertTrue(a.verify_request({}, b""))

    def test_verify_request_with_secret_passes(self) -> None:
        a = HttpAdapter(auth_secret="mysecret")
        headers = {"authorization": "Bearer mysecret"}
        self.assertTrue(a.verify_request(headers, b""))

    def test_verify_request_with_secret_fails(self) -> None:
        a = HttpAdapter(auth_secret="mysecret")
        headers = {"authorization": "Bearer wrong"}
        self.assertFalse(a.verify_request(headers, b""))

    def test_parse_webhook_valid(self) -> None:
        a = HttpAdapter()
        payload = {
            "prompt": "  do something  ",
            "sender_id": "user1",
            "callback_url": "http://cb",
            "session_id": "s1",
            "config": "profile1",
            "metadata": {"k": "v"},
        }
        req = a.parse_webhook(payload)
        self.assertIsNotNone(req)
        self.assertEqual("do something", req.prompt)
        self.assertEqual("user1", req.sender_id)
        self.assertEqual("http://cb", req.response_target)
        self.assertEqual("s1", req.session_id)
        self.assertEqual("profile1", req.config_profile)

    def test_parse_webhook_no_prompt_returns_none(self) -> None:
        a = HttpAdapter()
        req = a.parse_webhook({"prompt": "   "})
        self.assertIsNone(req)

    def test_parse_webhook_missing_prompt_returns_none(self) -> None:
        a = HttpAdapter()
        req = a.parse_webhook({})
        self.assertIsNone(req)

    def test_parse_webhook_defaults_sender_id(self) -> None:
        a = HttpAdapter()
        req = a.parse_webhook({"prompt": "hello"})
        self.assertIsNotNone(req)
        self.assertEqual("http", req.sender_id)

    def test_poll_messages_returns_empty(self) -> None:
        import asyncio

        a = HttpAdapter()
        result = asyncio.run(a.poll_messages())
        self.assertEqual([], result)

    def test_send_response_no_target(self) -> None:
        import asyncio

        a = HttpAdapter()
        result_obj = RunResult(exit_code=0, stdout="done", stderr="")
        result = asyncio.run(a.send_response("", result_obj))
        self.assertFalse(result)

    def test_send_question_no_target(self) -> None:
        import asyncio

        a = HttpAdapter()
        result = asyncio.run(a.send_question("", "a question?"))
        self.assertFalse(result)

    def test_send_response_http_success(self) -> None:
        import asyncio

        a = HttpAdapter()
        result_obj = RunResult(exit_code=0, stdout="done", stderr="")
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_response("http://callback", result_obj))
        self.assertTrue(result)

    def test_send_response_http_failure(self) -> None:
        import asyncio

        a = HttpAdapter()
        result_obj = RunResult(exit_code=1, stdout="", stderr="error")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_response("http://callback", result_obj))
        self.assertFalse(result)

    def test_send_question_http_success(self) -> None:
        import asyncio

        a = HttpAdapter()
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_question("http://target", "what?", [{"label": "yes", "description": "yes"}]))
        self.assertTrue(result)

    def test_send_question_http_exception(self) -> None:
        import asyncio

        a = HttpAdapter()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("fail"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_question("http://target", "what?"))
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# LogAdapter
# ---------------------------------------------------------------------------


class LogAdapterTests(unittest.TestCase):
    def test_channel_name(self) -> None:
        self.assertEqual("log", LogAdapter().channel_name)

    def test_supports_webhook(self) -> None:
        self.assertFalse(LogAdapter().supports_webhook)

    def test_supports_polling(self) -> None:
        self.assertFalse(LogAdapter().supports_polling)

    def test_verify_request_always_false(self) -> None:
        self.assertFalse(LogAdapter().verify_request({}, b""))

    def test_parse_webhook_always_none(self) -> None:
        self.assertIsNone(LogAdapter().parse_webhook({}))

    def test_poll_messages_returns_empty(self) -> None:
        import asyncio

        result = asyncio.run(LogAdapter().poll_messages())
        self.assertEqual([], result)

    def test_send_response_logs_and_returns_true(self) -> None:
        import asyncio

        a = LogAdapter()
        result_obj = RunResult(exit_code=0, stdout="done", stderr="")
        result = asyncio.run(a.send_response("", result_obj))
        self.assertTrue(result)

    def test_send_response_failed_run(self) -> None:
        import asyncio

        a = LogAdapter()
        result_obj = RunResult(exit_code=1, stdout="", stderr="err")
        result = asyncio.run(a.send_response("", result_obj))
        self.assertTrue(result)

    def test_send_question_returns_false(self) -> None:
        import asyncio

        a = LogAdapter()
        result = asyncio.run(a.send_question("", "q?"))
        self.assertFalse(result)

    def test_send_question_with_options(self) -> None:
        import asyncio

        a = LogAdapter()
        result = asyncio.run(a.send_question("", "q?", [{"label": "yes"}]))
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# TelegramAdapter
# ---------------------------------------------------------------------------


class TelegramAdapterParseTests(unittest.TestCase):
    def _make_update(self, text: str = "hello", chat_id: int = 42, from_id: int = 99) -> dict:
        return {
            "update_id": 1,
            "message": {
                "chat": {"id": chat_id},
                "from": {"id": from_id},
                "text": text,
            },
        }

    def test_parse_webhook_valid_message(self) -> None:
        a = TelegramAdapter(bot_token="TOKEN")
        req = a.parse_webhook(self._make_update("hello"))
        self.assertIsNotNone(req)
        self.assertEqual("hello", req.prompt)
        self.assertEqual("42", req.response_target)
        self.assertEqual("99", req.sender_id)
        self.assertEqual("telegram", req.channel)

    def test_parse_webhook_no_message(self) -> None:
        a = TelegramAdapter(bot_token="TOKEN")
        req = a.parse_webhook({"update_id": 1})
        self.assertIsNone(req)

    def test_parse_webhook_no_text(self) -> None:
        a = TelegramAdapter(bot_token="TOKEN")
        update = {"update_id": 1, "message": {"chat": {"id": 1}, "from": {"id": 2}}}
        req = a.parse_webhook(update)
        self.assertIsNone(req)

    def test_parse_webhook_filtered_out(self) -> None:
        a = TelegramAdapter(bot_token="TOKEN", trigger_filter=TriggerFilter(prefix="/bot "))
        req = a.parse_webhook(self._make_update("no prefix"))
        self.assertIsNone(req)

    def test_verify_request_with_secret(self) -> None:
        a = TelegramAdapter(bot_token="TOKEN", webhook_secret="SECRET")
        self.assertTrue(a.verify_request({"x-telegram-bot-api-secret-token": "SECRET"}, b""))
        self.assertFalse(a.verify_request({"x-telegram-bot-api-secret-token": "WRONG"}, b""))

    def test_verify_request_no_secret_uses_token(self) -> None:
        a = TelegramAdapter(bot_token="TOKEN")
        self.assertTrue(a.verify_request({}, b""))

    def test_supports_webhook_and_polling(self) -> None:
        a = TelegramAdapter(bot_token="TOKEN")
        self.assertTrue(a.supports_webhook)
        self.assertTrue(a.supports_polling)

    def test_send_response(self) -> None:
        import asyncio

        a = TelegramAdapter(bot_token="TOKEN")
        result_obj = RunResult(exit_code=0, stdout="done", stderr="")
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_response("42", result_obj))
        self.assertTrue(result)

    def test_send_question_with_options(self) -> None:
        import asyncio

        a = TelegramAdapter(bot_token="TOKEN")
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_question("42", "Do it?", [{"label": "yes", "description": "proceed"}]))
        self.assertTrue(result)

    def test_send_text_exception(self) -> None:
        import asyncio

        a = TelegramAdapter(bot_token="TOKEN")
        result_obj = RunResult(exit_code=0, stdout="", stderr="")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("fail"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_response("42", result_obj))
        self.assertFalse(result)

    def test_poll_messages_success(self) -> None:
        import asyncio

        a = TelegramAdapter(bot_token="TOKEN")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 10,
                    "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "hello"},
                }
            ],
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(a.poll_messages())
        self.assertEqual(1, len(results))
        self.assertEqual("hello", results[0].prompt)
        self.assertEqual(11, a._update_offset)

    def test_poll_messages_not_ok(self) -> None:
        import asyncio

        a = TelegramAdapter(bot_token="TOKEN")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(a.poll_messages())
        self.assertEqual([], results)

    def test_poll_messages_exception(self) -> None:
        import asyncio

        a = TelegramAdapter(bot_token="TOKEN")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(a.poll_messages())
        self.assertEqual([], results)


# ---------------------------------------------------------------------------
# WhatsAppAdapter
# ---------------------------------------------------------------------------


class WhatsAppAdapterTests(unittest.TestCase):
    def _make_payload(self, text: str = "hello", from_id: str = "1234567890") -> dict:
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "type": "text",
                                        "from": from_id,
                                        "text": {"body": text},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

    def test_parse_webhook_valid(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        req = a.parse_webhook(self._make_payload("do stuff"))
        self.assertIsNotNone(req)
        self.assertEqual("do stuff", req.prompt)
        self.assertEqual("1234567890", req.sender_id)
        self.assertEqual("whatsapp", req.channel)

    def test_parse_webhook_no_entry(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        self.assertIsNone(a.parse_webhook({}))
        self.assertIsNone(a.parse_webhook({"entry": []}))

    def test_parse_webhook_no_changes(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        payload = {"entry": [{"changes": []}]}
        self.assertIsNone(a.parse_webhook(payload))

    def test_parse_webhook_no_messages(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
        self.assertIsNone(a.parse_webhook(payload))

    def test_parse_webhook_non_text_type(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        payload = {"entry": [{"changes": [{"value": {"messages": [{"type": "image", "from": "u"}]}}]}]}
        self.assertIsNone(a.parse_webhook(payload))

    def test_parse_webhook_filtered_out(self) -> None:
        a = WhatsAppAdapter(
            phone_number_id="PH",
            access_token="TOK",
            trigger_filter=TriggerFilter(prefix="/bot "),
        )
        req = a.parse_webhook(self._make_payload("no prefix"))
        self.assertIsNone(req)

    def test_verify_request_no_secret(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        self.assertTrue(a.verify_request({}, b""))

    def test_verify_request_with_secret_valid(self) -> None:
        import hashlib
        import hmac

        secret = "mysecret"
        body = b'{"test": true}'
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK", app_secret=secret)
        self.assertTrue(a.verify_request({"x-hub-signature-256": sig}, body))

    def test_verify_request_with_secret_invalid(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK", app_secret="secret")
        self.assertFalse(a.verify_request({"x-hub-signature-256": "sha256=wrong"}, b"body"))

    def test_verify_request_bad_sig_format(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK", app_secret="secret")
        self.assertFalse(a.verify_request({"x-hub-signature-256": "nope"}, b"body"))

    def test_channel_properties(self) -> None:
        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        self.assertEqual("whatsapp", a.channel_name)
        self.assertTrue(a.supports_webhook)
        self.assertFalse(a.supports_polling)

    def test_poll_messages_returns_empty(self) -> None:
        import asyncio

        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        result = asyncio.run(a.poll_messages())
        self.assertEqual([], result)

    def test_send_response(self) -> None:
        import asyncio

        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        result_obj = RunResult(exit_code=0, stdout="done", stderr="")
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_response("1234", result_obj))
        self.assertTrue(result)

    def test_send_question_with_options(self) -> None:
        import asyncio

        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_question("1234", "Choose:", [{"label": "A", "description": "Option A"}]))
        self.assertTrue(result)

    def test_send_text_exception(self) -> None:
        import asyncio

        a = WhatsAppAdapter(phone_number_id="PH", access_token="TOK")
        result_obj = RunResult(exit_code=0, stdout="", stderr="")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("fail"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(a.send_response("1234", result_obj))
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# build_trigger_filter / build_adapters
# ---------------------------------------------------------------------------


class BuildTriggerFilterTests(unittest.TestCase):
    def test_none_config_returns_empty(self) -> None:
        f = build_trigger_filter(None)
        self.assertTrue(f.is_empty)

    def test_empty_config_returns_empty(self) -> None:
        f = build_trigger_filter({})
        self.assertTrue(f.is_empty)

    def test_full_config(self) -> None:
        f = build_trigger_filter(
            {
                "chat_ids": ["c1"],
                "sender_ids": ["u1"],
                "prefix": "/bot ",
            }
        )
        self.assertEqual(["c1"], f.chat_ids)
        self.assertEqual(["u1"], f.sender_ids)
        self.assertEqual("/bot ", f.prefix)


class BuildAdaptersTests(unittest.TestCase):
    def test_always_includes_log(self) -> None:
        adapters = build_adapters({})
        self.assertIn("log", adapters)
        self.assertIsInstance(adapters["log"], LogAdapter)

    def test_http_adapter_enabled(self) -> None:
        adapters = build_adapters({"http": {"enabled": True, "auth_secret": "s"}})
        self.assertIn("http", adapters)
        self.assertIsInstance(adapters["http"], HttpAdapter)
        self.assertEqual("s", adapters["http"].auth_secret)

    def test_http_adapter_enabled_by_default(self) -> None:
        # Non-empty config with no explicit enabled=False defaults to enabled
        adapters = build_adapters({"http": {"auth_secret": ""}})
        self.assertIn("http", adapters)

    def test_http_adapter_disabled(self) -> None:
        adapters = build_adapters({"http": {"enabled": False}})
        self.assertNotIn("http", adapters)

    def test_telegram_no_token_skipped(self) -> None:
        adapters = build_adapters({"telegram": {"enabled": True, "bot_token": ""}})
        self.assertNotIn("telegram", adapters)

    def test_telegram_with_token(self) -> None:
        adapters = build_adapters(
            {
                "telegram": {"enabled": True, "bot_token": "TOK", "trigger_filter": {"prefix": "/a "}},
            }
        )
        self.assertIn("telegram", adapters)
        self.assertIsInstance(adapters["telegram"], TelegramAdapter)

    def test_telegram_disabled(self) -> None:
        adapters = build_adapters({"telegram": {"enabled": False, "bot_token": "TOK"}})
        self.assertNotIn("telegram", adapters)

    def test_whatsapp_missing_credentials_skipped(self) -> None:
        adapters = build_adapters({"whatsapp": {"enabled": True, "phone_number_id": "", "access_token": "TOK"}})
        self.assertNotIn("whatsapp", adapters)

    def test_whatsapp_with_credentials(self) -> None:
        adapters = build_adapters(
            {
                "whatsapp": {
                    "enabled": True,
                    "phone_number_id": "PH",
                    "access_token": "TOK",
                    "trigger_filter": {"prefix": "/w "},
                }
            }
        )
        self.assertIn("whatsapp", adapters)
        self.assertIsInstance(adapters["whatsapp"], WhatsAppAdapter)

    def test_whatsapp_disabled(self) -> None:
        adapters = build_adapters({"whatsapp": {"enabled": False}})
        self.assertNotIn("whatsapp", adapters)


if __name__ == "__main__":
    unittest.main()
