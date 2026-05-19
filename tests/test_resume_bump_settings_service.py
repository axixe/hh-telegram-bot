import tempfile
import unittest
from pathlib import Path

from bot.services.resume_bump_settings_service import (
    ResumeBumpSettings,
    ResumeBumpSettingsService,
    ResumeBumpSettingsServiceError,
)


class ResumeBumpSettingsServiceTest(unittest.TestCase):
    def test_defaults_to_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ResumeBumpSettingsService(Path(tmp))

            settings = service.get(123)

        self.assertFalse(settings.is_enabled)
        self.assertIsNone(settings.interval_hours)
        self.assertEqual(settings.label, "выкл")

    def test_saves_and_loads_supported_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ResumeBumpSettingsService(Path(tmp))

            service.save(123, ResumeBumpSettings(interval_hours=4))
            settings = service.get(123)

        self.assertTrue(settings.is_enabled)
        self.assertEqual(settings.interval_hours, 4)
        self.assertEqual(settings.label, "4 часа")

    def test_invalid_json_is_treated_as_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config" / "tg_123"
            path.mkdir(parents=True)
            (path / "telegram_resume_bump_settings.json").write_text("{", encoding="utf-8")
            service = ResumeBumpSettingsService(Path(tmp))

            settings = service.get(123)

        self.assertFalse(settings.is_enabled)

    def test_rejects_unsupported_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ResumeBumpSettingsService(Path(tmp))

            with self.assertRaises(ResumeBumpSettingsServiceError):
                service.save(123, ResumeBumpSettings(interval_hours=3))


if __name__ == "__main__":
    unittest.main()
