from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from bot.services.profile_service import ProfileService


class ResumeBumpSettingsServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResumeBumpSettings:
    interval_hours: int | None = None

    @property
    def is_enabled(self) -> bool:
        return self.interval_hours in ResumeBumpSettingsService.SUPPORTED_INTERVAL_HOURS

    @property
    def label(self) -> str:
        if not self.is_enabled:
            return "выкл"
        return f"{self.interval_hours} часа"


class ResumeBumpSettingsService:
    SETTINGS_FILENAME = "telegram_resume_bump_settings.json"
    SUPPORTED_INTERVAL_HOURS = frozenset({4, 5})

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    def get(self, telegram_user_id: int) -> ResumeBumpSettings:
        path = self._get_settings_path(telegram_user_id)
        if not path.exists():
            return ResumeBumpSettings()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._parse(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return ResumeBumpSettings()

    def save(self, telegram_user_id: int, settings: ResumeBumpSettings) -> None:
        if (
            settings.interval_hours is not None
            and settings.interval_hours not in self.SUPPORTED_INTERVAL_HOURS
        ):
            raise ResumeBumpSettingsServiceError("Unsupported resume bump interval")

        path = self._get_settings_path(telegram_user_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"interval_hours": settings.interval_hours},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ResumeBumpSettingsServiceError("Failed to save resume bump settings") from exc

    def disable(self, telegram_user_id: int) -> None:
        self.save(telegram_user_id, ResumeBumpSettings())

    def _get_settings_path(self, telegram_user_id: int) -> Path:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        return self._workdir / "config" / profile_id / self.SETTINGS_FILENAME

    def _parse(self, data: dict[str, Any]) -> ResumeBumpSettings:
        interval_hours = data.get("interval_hours")
        if interval_hours is None:
            return ResumeBumpSettings()
        interval_hours = int(interval_hours)
        if interval_hours not in self.SUPPORTED_INTERVAL_HOURS:
            return ResumeBumpSettings()
        return ResumeBumpSettings(interval_hours=interval_hours)
