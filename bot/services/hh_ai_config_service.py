import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from bot.config import AiSettings
from bot.services.profile_service import ProfileService


class HhAiConfigServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class HhAiConfigService:
    workdir: Path
    ai_settings: AiSettings

    def configure_vacancy_filter(self, telegram_user_id: int) -> None:
        if not self.ai_settings.enabled:
            raise HhAiConfigServiceError("AI is disabled")

        config_path = self._get_config_path(telegram_user_id)
        try:
            config = self._read_config(config_path)
            config["openai_vacancy_filter"] = {
                **self._get_existing_section(config),
                "api_key": self.ai_settings.api_key,
                "base_url": self._get_container_chat_completions_url(),
                "model": self.ai_settings.model,
                "temperature": 0.1,
                "max_completion_tokens": 100,
                "rate_limit": 20,
            }
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            raise HhAiConfigServiceError("Failed to save HH AI config") from exc
        except json.JSONDecodeError as exc:
            raise HhAiConfigServiceError("HH config contains invalid JSON") from exc

    def _get_config_path(self, telegram_user_id: int) -> Path:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        return self.workdir / "config" / profile_id / "config.json"

    def _read_config(self, config_path: Path) -> dict:
        if not config_path.exists():
            return {}

        content = config_path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return {}

        config = json.loads(content)
        if not isinstance(config, dict):
            raise HhAiConfigServiceError("HH config must be a JSON object")

        return config

    def _get_existing_section(self, config: dict) -> dict:
        section = config.get("openai_vacancy_filter", {})
        return section if isinstance(section, dict) else {}

    def _get_container_chat_completions_url(self) -> str:
        base_url = self.ai_settings.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            url = base_url
        else:
            url = f"{base_url}/chat/completions"

        parsed = urlparse(url)
        if parsed.hostname not in {"localhost", "127.0.0.1"}:
            return url

        netloc = "host.docker.internal"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"

        return urlunparse(parsed._replace(netloc=netloc))
