from __future__ import annotations

import json
import socket
import unittest
import urllib.error
from unittest.mock import patch

from subbake.entities import Usage
from subbake.models.base_model import (
    BackendRequestError,
    GeminiBackend,
    OpenAIBackend,
    build_backend,
    parse_glossary_entries,
    parse_translation_lines,
)


class FakeResponse:
    def __init__(self, payload: dict, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class ModelParsingTestCase(unittest.TestCase):
    def test_parse_translation_lines_accepts_text_key(self) -> None:
        lines = parse_translation_lines([{"id": "1", "text": "你好"}])
        self.assertEqual(lines[0].translation, "你好")

    def test_parse_glossary_entries_accepts_mapping(self) -> None:
        entries = parse_glossary_entries({"Hartman": "哈特曼"})
        self.assertEqual([(entry.source, entry.target) for entry in entries], [("Hartman", "哈特曼")])

    def test_parse_glossary_entries_accepts_parenthetical_string_entries(self) -> None:
        entries = parse_glossary_entries(
            ["战斗脸 (war face): 军事训练中要求士兵展现的凶狠表情"]
        )
        self.assertEqual(
            [(entry.source, entry.target) for entry in entries],
            [("war face", "战斗脸")],
        )

    def test_parse_glossary_entries_accepts_hyphenated_string_entries(self) -> None:
        entries = parse_glossary_entries(["列兵 - private", "formation - 队形"])
        self.assertEqual(
            [(entry.source, entry.target) for entry in entries],
            [("private", "列兵"), ("formation", "队形")],
        )


class ProviderRetryTestCase(unittest.TestCase):
    def test_openai_backend_retries_retryable_http_errors(self) -> None:
        backend = OpenAIBackend(model="demo", api_key="test-key", timeout_seconds=1.0)
        responses: list[object] = [
            urllib.error.HTTPError(
                url="https://example.test/v1/chat/completions",
                code=429,
                msg="Too Many Requests",
                hdrs={"retry-after": "0", "x-request-id": "req-1"},
                fp=None,
            ),
            FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"lines": [{"id": "1", "translation": "你好"}]})
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ),
        ]

        with patch("urllib.request.urlopen", side_effect=responses), patch("time.sleep"):
            payload, usage = backend.generate_json([{"role": "user", "content": "hello"}])

        self.assertEqual(payload["lines"][0]["translation"], "你好")
        self.assertEqual(usage.total_tokens, 2)

    def test_openai_backend_surfaces_request_metadata_on_failure(self) -> None:
        backend = OpenAIBackend(model="demo", api_key="test-key", timeout_seconds=1.0)
        error = urllib.error.HTTPError(
            url="https://example.test/v1/chat/completions",
            code=503,
            msg="Service Unavailable",
            hdrs={"retry-after": "0", "x-request-id": "req-503"},
            fp=None,
        )

        with patch("urllib.request.urlopen", side_effect=[error, error, error]), patch("time.sleep"):
            with self.assertRaises(BackendRequestError) as context:
                backend.generate_json([{"role": "user", "content": "hello"}])

        self.assertEqual(context.exception.metadata.status_code, 503)
        self.assertEqual(context.exception.metadata.request_id, "req-503")
        self.assertTrue(context.exception.metadata.retryable)

    def test_openai_backend_surfaces_transport_error_metadata(self) -> None:
        backend = OpenAIBackend(model="demo", api_key="test-key", timeout_seconds=1.0)
        error = urllib.error.URLError(socket.timeout("timed out"))

        with patch("urllib.request.urlopen", side_effect=[error, error, error]), patch("time.sleep"):
            with self.assertRaises(BackendRequestError) as context:
                backend.generate_json([{"role": "user", "content": "hello"}])

        self.assertIsNone(context.exception.metadata.status_code)
        self.assertTrue(context.exception.metadata.retryable)
        self.assertIn("timed out", str(context.exception.metadata.reason))

    def test_openai_backend_raises_value_error_for_malformed_json_content(self) -> None:
        backend = OpenAIBackend(model="demo", api_key="test-key", timeout_seconds=1.0)
        response = FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "this is not valid json",
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(ValueError):
                backend.generate_json([{"role": "user", "content": "hello"}])

    def test_build_backend_supports_gemini_provider(self) -> None:
        backend = build_backend("gemini", "gemini-2.5-flash", api_key="test-key")

        self.assertIsInstance(backend, GeminiBackend)
        self.assertEqual(backend.base_url, "https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(backend.api_key, "test-key")

    def test_gemini_backend_uses_gemini_api_key_env_var(self) -> None:
        with patch.dict("os.environ", {"GEMINI_API_KEY": "gem-test-key"}, clear=False):
            backend = GeminiBackend(model="gemini-2.5-flash")

        self.assertEqual(backend.api_key, "gem-test-key")

    def test_gemini_backend_credential_check_uses_gemini_label(self) -> None:
        backend = GeminiBackend(model="gemini-2.5-flash", api_key="test-key", timeout_seconds=1.0)
        response = FakeResponse({"data": [{"id": "gemini-2.5-flash"}]})

        with patch("urllib.request.urlopen", return_value=response):
            valid, message = backend.check_credentials()

        self.assertTrue(valid)
        self.assertIn("Gemini", message)
