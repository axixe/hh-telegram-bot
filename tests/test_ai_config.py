import os
import unittest
from unittest.mock import patch

from bot.config import load_settings


class AiConfigTest(unittest.TestCase):
    def test_ai_settings_are_disabled_by_default(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "123456:token",
            "TELEGRAM_ALLOWED_USER_IDS": "123456789",
            "HH_TOOL_WORKDIR": ".",
        }

        with patch.dict(os.environ, env, clear=True), patch("bot.config.load_dotenv"):
            settings = load_settings()

        self.assertFalse(settings.ai.enabled)
        self.assertEqual(settings.ai.provider, "ollama")
        self.assertEqual(settings.ai.base_url, "")
        self.assertEqual(settings.ai.model, "")
        self.assertEqual(settings.ai.api_key, "")

    def test_loads_enabled_ai_settings(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "123456:token",
            "TELEGRAM_ALLOWED_USER_IDS": "123456789",
            "HH_TOOL_WORKDIR": ".",
            "AI_ENABLED": "true",
            "AI_PROVIDER": "ollama",
            "AI_BASE_URL": "http://localhost:11434/v1",
            "AI_MODEL": "qwen2.5:3b",
            "AI_API_KEY": "ollama",
        }

        with patch.dict(os.environ, env, clear=True), patch("bot.config.load_dotenv"):
            settings = load_settings()

        self.assertTrue(settings.ai.enabled)
        self.assertEqual(settings.ai.provider, "ollama")
        self.assertEqual(settings.ai.base_url, "http://localhost:11434/v1")
        self.assertEqual(settings.ai.model, "qwen2.5:3b")
        self.assertEqual(settings.ai.api_key, "ollama")

    def test_enabled_ai_requires_endpoint_model_and_key(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "123456:token",
            "TELEGRAM_ALLOWED_USER_IDS": "123456789",
            "HH_TOOL_WORKDIR": ".",
            "AI_ENABLED": "true",
        }

        with patch.dict(os.environ, env, clear=True), patch("bot.config.load_dotenv"):
            with self.assertRaisesRegex(RuntimeError, "AI_BASE_URL, AI_MODEL, AI_API_KEY"):
                load_settings()


if __name__ == "__main__":
    unittest.main()
