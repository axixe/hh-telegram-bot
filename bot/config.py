from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_ids: frozenset[int]
    hh_tool_workdir: Path


def load_settings() -> Settings:
    load_dotenv()

    token = _get_required_env("TELEGRAM_BOT_TOKEN")
    allowed_user_ids = _parse_user_ids(_get_required_env("TELEGRAM_ALLOWED_USER_IDS"))
    hh_tool_workdir = Path(_get_required_env("HH_TOOL_WORKDIR")).expanduser().resolve()

    return Settings(
        telegram_bot_token=token,
        telegram_allowed_user_ids=allowed_user_ids,
        hh_tool_workdir=hh_tool_workdir,
    )


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _parse_user_ids(value: str) -> frozenset[int]:
    user_ids: set[int] = set()

    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            user_ids.add(int(item))
        except ValueError as exc:
            raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS must contain only integer IDs") from exc

    if not user_ids:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS must contain at least one user ID")

    return frozenset(user_ids)
