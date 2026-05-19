import json
import tempfile
import unittest
from pathlib import Path

from bot.config import AiSettings
from bot.services.hh_ai_config_service import HhAiConfigService


def enabled_ai_settings(base_url: str = "http://localhost:11434/v1") -> AiSettings:
    return AiSettings(
        enabled=True,
        provider="ollama",
        base_url=base_url,
        model="qwen2.5:3b",
        api_key="ollama",
    )


class HhAiConfigServiceTest(unittest.TestCase):
    def test_configures_vacancy_filter_for_docker_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            config_path = workdir / "config" / "tg_123" / "config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"client_id": "keep-me"}, ensure_ascii=False),
                encoding="utf-8",
            )

            HhAiConfigService(workdir, enabled_ai_settings()).configure_vacancy_filter(123)

            config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(config["client_id"], "keep-me")
        self.assertEqual(config["openai_vacancy_filter"]["api_key"], "ollama")
        self.assertEqual(
            config["openai_vacancy_filter"]["base_url"],
            "http://host.docker.internal:11434/v1/chat/completions",
        )
        self.assertEqual(config["openai_vacancy_filter"]["model"], "qwen2.5:3b")
        self.assertEqual(config["openai_vacancy_filter"]["rate_limit"], 20)

    def test_keeps_non_localhost_base_url(self) -> None:
        service = HhAiConfigService(
            Path("."),
            enabled_ai_settings("https://example.com/v1/chat/completions"),
        )

        self.assertEqual(
            service._get_container_chat_completions_url(),
            "https://example.com/v1/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
