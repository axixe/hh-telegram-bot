import io
import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from bot.config import AiSettings
from bot.services.ai_client import (
    AiClient,
    AiClientConnectionError,
    AiClientDisabledError,
    AiClientEmptyResponseError,
    AiClientEndpointError,
    AiClientTimeoutError,
)


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def enabled_settings() -> AiSettings:
    return AiSettings(
        enabled=True,
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model="qwen2.5:3b",
        api_key="ollama",
    )


class AiClientTest(unittest.TestCase):
    def test_chat_returns_first_message_content(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Локальная модель подключена и работает."
                            }
                        }
                    ]
                }
            )

        client = AiClient(enabled_settings(), timeout_seconds=12)

        with patch("bot.services.ai_client.urlopen", fake_urlopen):
            answer = client.chat("Проверка")

        request = captured["request"]
        self.assertEqual(answer, "Локальная модель подключена и работает.")
        self.assertEqual(request.full_url, "http://localhost:11434/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer ollama")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen2.5:3b")
        self.assertEqual(payload["messages"][0]["content"], "Проверка")
        self.assertFalse(payload["stream"])
        self.assertEqual(captured["timeout"], 12)

    def test_disabled_ai_raises_disabled_error(self) -> None:
        settings = AiSettings(
            enabled=False,
            provider="ollama",
            base_url="",
            model="",
            api_key="",
        )

        with self.assertRaises(AiClientDisabledError):
            AiClient(settings).chat("Проверка")

    def test_empty_choices_raise_empty_response_error(self) -> None:
        client = AiClient(enabled_settings())

        with patch("bot.services.ai_client.urlopen", return_value=FakeResponse({"choices": []})):
            with self.assertRaises(AiClientEmptyResponseError):
                client.chat("Проверка")

    def test_empty_content_raises_empty_response_error(self) -> None:
        client = AiClient(enabled_settings())

        with patch(
            "bot.services.ai_client.urlopen",
            return_value=FakeResponse({"choices": [{"message": {"content": "   "}}]}),
        ):
            with self.assertRaises(AiClientEmptyResponseError):
                client.chat("Проверка")

    def test_http_error_raises_endpoint_error(self) -> None:
        client = AiClient(enabled_settings())
        error = HTTPError(
            url="http://localhost:11434/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b'{"error":"model not found"}'),
        )

        with patch("bot.services.ai_client.urlopen", side_effect=error):
            with self.assertRaises(AiClientEndpointError):
                client.chat("Проверка")

    def test_connection_error_raises_connection_error(self) -> None:
        client = AiClient(enabled_settings())

        with patch("bot.services.ai_client.urlopen", side_effect=URLError("refused")):
            with self.assertRaises(AiClientConnectionError):
                client.chat("Проверка")

    def test_timeout_raises_connection_error(self) -> None:
        client = AiClient(enabled_settings())

        with patch("bot.services.ai_client.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(AiClientTimeoutError):
                client.chat("Проверка")


if __name__ == "__main__":
    unittest.main()
