import json
import socket
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bot.config import AiSettings


AI_TEST_PROMPT = "Ответь коротко: локальная модель подключена и работает."


class AiClientError(RuntimeError):
    pass


class AiClientDisabledError(AiClientError):
    pass


class AiClientConnectionError(AiClientError):
    pass


class AiClientTimeoutError(AiClientConnectionError):
    pass


class AiClientEndpointError(AiClientError):
    pass


class AiClientEmptyResponseError(AiClientError):
    pass


@dataclass(frozen=True)
class AiClient:
    settings: AiSettings
    timeout_seconds: float = 30.0

    def chat(self, prompt: str) -> str:
        if not self.settings.enabled:
            raise AiClientDisabledError("AI is disabled")

        payload = {
            "model": self.settings.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        request = Request(
            self._chat_completions_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read()
        except HTTPError as exc:
            raise AiClientEndpointError(self._format_http_error(exc)) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AiClientTimeoutError("AI request timed out") from exc
        except URLError as exc:
            raise AiClientConnectionError("AI endpoint is unavailable") from exc

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AiClientEndpointError("AI endpoint returned invalid JSON") from exc

        return self._extract_message_content(body)

    def _chat_completions_url(self) -> str:
        return f"{self.settings.base_url.rstrip('/')}/chat/completions"

    def _extract_message_content(self, body: object) -> str:
        if not isinstance(body, dict):
            raise AiClientEndpointError("AI endpoint returned an unexpected response")

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AiClientEmptyResponseError("AI endpoint returned no choices")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise AiClientEmptyResponseError("AI endpoint returned an empty choice")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise AiClientEmptyResponseError("AI endpoint returned no message")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AiClientEmptyResponseError("AI endpoint returned an empty message")

        return content.strip()

    def _format_http_error(self, exc: HTTPError) -> str:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        if body:
            return f"AI endpoint returned HTTP {exc.code}: {body[:500]}"
        return f"AI endpoint returned HTTP {exc.code}"
