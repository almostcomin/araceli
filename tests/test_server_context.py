"""Automated tests for server context discovery and API error hints."""

import contextlib
import io
import json
import sys
import unittest

from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import main

from main import (
    _context_size_hint,
    _extract_api_error_detail,
    query_server_context,
)


class _FakeResponse:
    """Minimal stand-in for the object returned by urlopen."""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class QueryServerContextTestCase(unittest.TestCase):
    """Tests for context discovery through LM Studio's native API."""

    def _mock_urlopen(self, payload):
        return mock.patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(json.dumps(payload).encode("utf-8")),
        )

    def test_returns_loaded_context_for_matching_model(self):
        payload = {
            "data": [
                {
                    "id": "qwen/qwen3.5-9b",
                    "state": "loaded",
                    "loaded_context_length": 8192,
                    "max_context_length": 262144,
                },
                {
                    "id": "text-embedding-nomic-embed-text-v1.5",
                    "state": "loaded",
                    "loaded_context_length": 2048,
                },
            ]
        }

        with self._mock_urlopen(payload):
            result = query_server_context()

        self.assertEqual(result, 8192)

    def test_returns_none_when_model_is_not_loaded(self):
        payload = {
            "data": [
                {"id": "qwen/qwen3.5-9b", "state": "not-loaded"},
            ]
        }

        with self._mock_urlopen(payload):
            self.assertIsNone(query_server_context())

    def test_returns_none_when_model_is_missing(self):
        payload = {"data": [{"id": "other/model", "state": "loaded"}]}

        with self._mock_urlopen(payload):
            self.assertIsNone(query_server_context())

    def test_returns_none_on_request_failure(self):
        with mock.patch(
            "urllib.request.urlopen", side_effect=OSError("down")
        ):
            self.assertIsNone(query_server_context())

    def test_returns_none_on_invalid_payload(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(b"not json"),
        ):
            self.assertIsNone(query_server_context())

    def test_queries_native_api_endpoint(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(b'{"data": []}'),
        ) as urlopen_mock:
            query_server_context()

        request = urlopen_mock.call_args.args[0]

        self.assertEqual(
            request.full_url, "http://127.0.0.1:1234/api/v0/models"
        )


class ContextSizeHintTestCase(unittest.TestCase):
    """Tests for the exceed-context-size hint extraction."""

    def test_hint_from_string_body(self):
        body = (
            'Engine protocol predict request returned 400: '
            '{"error":{"code":400,"message":"request (40010 tokens) '
            'exceeds the available context size (24576 tokens), try '
            'increasing it","type":"exceed_context_size_error",'
            '"n_prompt_tokens":40010,"n_ctx":24576}}'
        )

        FakeError = type(
            "FakeError",
            (Exception,),
            {"body": body},
        )

        hint = _context_size_hint(FakeError("Error code: 400"))

        self.assertIsNotNone(hint)
        self.assertIn("24576 tokens", hint)
        self.assertIn("Raise the model's context length", hint)

    def test_none_for_unrelated_error_body(self):
        class FakeError(Exception):
            body = {"error": {"message": "something else"}}

        self.assertIsNone(_context_size_hint(FakeError("x")))

    def test_none_for_garbage_body(self):
        self.assertIsNone(_context_size_hint(Exception("plain")))

    def test_none_when_json_is_broken(self):
        body = _MARKUP_BODY_PARTIAL = "prefix {not json"

        self.assertIsNone(_context_size_hint(Exception(body)))


class ExtractApiErrorDetailTestCase(unittest.TestCase):
    """Tests for readable API error messages."""

    def test_includes_string_body(self):
        class FakeError(Exception):
            body = "the server explanation"

        detail = _extract_api_error_detail(FakeError("Error code: 400"))

        self.assertEqual(
            detail, "Error code: 400: the server explanation"
        )

    def test_includes_dict_body(self):
        class FakeError(Exception):
            body = {"error": {"message": "bad request"}}

        detail = _extract_api_error_detail(FakeError("Error code: 400"))

        self.assertIn("bad request", detail)

    def test_plain_exception_uses_str(self):
        detail = _extract_api_error_detail(OSError("connection lost"))

        self.assertEqual(detail, "connection lost")


class EstimateTokensTestCase(unittest.TestCase):
    """Tests for the approximate token estimator."""

    def test_estimate_is_chars_over_four(self):
        self.assertEqual(main.estimate_tokens("abcd" * 100), 100)

    def test_empty_text_estimates_one_token(self):
        self.assertEqual(main.estimate_tokens(""), 1)

    def test_estimation_rounds(self):
        self.assertEqual(main.estimate_tokens("abcdefg"), 2)


class PrintContextUsageTestCase(unittest.TestCase):
    """Tests for the shared context usage line."""

    def _capture(self, used_tokens, context_limit):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            main.print_context_usage(used_tokens, context_limit)

        return output.getvalue()

    def test_line_contains_values(self):
        text = self._capture(12058, 32768)

        self.assertIn("Context: 36.8%", text)
        self.assertIn("(12,058/32,768", text)
        self.assertIn("20,710 free", text)

    def test_line_warns_at_ninety_percent(self):
        text = self._capture(31000, 32768)

        self.assertIn("Context: 94.6%", text)
        self.assertIn("1,768 free", text)


class ToolBudgetExceededTestCase(unittest.TestCase):
    """Tests for the tool round budget exception."""

    class _StubFunction:
        name = "calculate"
        arguments = '{"expression": "2+2"}'

    class _StubToolCall:
        def __init__(self):
            self.id = "call_1"
            self.function = ToolBudgetExceededTestCase._StubFunction()

    class _StubMessage:
        def __init__(self):
            self.content = None
            self.tool_calls = [ToolBudgetExceededTestCase._StubToolCall()]

        def model_dump(self, exclude_none=False):
            return {
                "role": "assistant",
                "content": self.content,
            }

    class _StubChoice:
        def __init__(self):
            self.message = ToolBudgetExceededTestCase._StubMessage()
            self.finish_reason = "tool_calls"

    class _StubUsage:
        prompt_tokens = 100
        completion_tokens = 10

    class _StubResponse:
        def __init__(self):
            self.choices = [ToolBudgetExceededTestCase._StubChoice()]
            self.usage = ToolBudgetExceededTestCase._StubUsage()

    class _StubCompletions:
        def create(self, **kwargs):
            return ToolBudgetExceededTestCase._StubResponse()

    class _StubChat:
        def __init__(self):
            self.completions = ToolBudgetExceededTestCase._StubCompletions()

    class _StubClient:
        def __init__(self):
            self.chat = ToolBudgetExceededTestCase._StubChat()

    def test_budget_exhaustion_raises_dedicated_exception(self):
        import contextlib

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(main.ToolBudgetExceeded) as context:
                main.generate_response(
                    ToolBudgetExceededTestCase._StubClient(),
                    [],
                    main.BASE_TOOL_DEFINITIONS,
                )

        self.assertIn("16", str(context.exception))
        self.assertIn("rounds", str(context.exception))

    def test_budget_exception_is_an_exception(self):
        self.assertIsInstance(
            main.ToolBudgetExceeded("x"), Exception
        )


if __name__ == "__main__":
    unittest.main()
