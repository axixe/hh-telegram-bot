from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from bot.services.account_service import AccountSummary
from bot.services.profile_service import ProfileService


class AccountCacheServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CachedResume:
    title: str
    status: str
    total_views: int
    new_views: int


@dataclass(frozen=True)
class CachedAccount:
    full_name: str
    resumes_count: int
    resumes: tuple[CachedResume, ...]


class AccountCacheService:
    CACHE_FILENAME = "telegram_account_cache.json"

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    def get(self, telegram_user_id: int) -> CachedAccount | None:
        path = self._get_cache_path(telegram_user_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._parse(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def save_summary(self, telegram_user_id: int, summary: AccountSummary) -> CachedAccount:
        account = CachedAccount(
            full_name=summary.full_name or "HH",
            resumes_count=summary.resumes_count,
            resumes=tuple(
                CachedResume(
                    title=resume.title,
                    status=resume.status,
                    total_views=resume.total_views,
                    new_views=resume.new_views,
                )
                for resume in summary.resumes
            ),
        )
        self.save(telegram_user_id, account)
        return account

    def save(self, telegram_user_id: int, account: CachedAccount) -> None:
        path = self._get_cache_path(telegram_user_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(account), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise AccountCacheServiceError("Failed to save account cache") from exc

    def _get_cache_path(self, telegram_user_id: int) -> Path:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        return self._workdir / "config" / profile_id / self.CACHE_FILENAME

    def _parse(self, data: dict[str, Any]) -> CachedAccount:
        resumes = tuple(
            CachedResume(
                title=str(item["title"]),
                status=str(item["status"]),
                total_views=int(item["total_views"]),
                new_views=int(item["new_views"]),
            )
            for item in data.get("resumes", [])
        )
        return CachedAccount(
            full_name=str(data["full_name"]),
            resumes_count=int(data["resumes_count"]),
            resumes=resumes,
        )
