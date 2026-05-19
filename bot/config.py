from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class AiSettings:
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_ids: frozenset[int]
    hh_tool_workdir: Path
    ai: AiSettings


def load_settings() -> Settings:
    load_dotenv()

    token = _get_required_env("TELEGRAM_BOT_TOKEN")
    allowed_user_ids = _parse_user_ids(_get_required_env("TELEGRAM_ALLOWED_USER_IDS"))
    hh_tool_workdir = Path(_get_required_env("HH_TOOL_WORKDIR")).expanduser().resolve()
    ai = _load_ai_settings()

    return Settings(
        telegram_bot_token=token,
        telegram_allowed_user_ids=allowed_user_ids,
        hh_tool_workdir=hh_tool_workdir,
        ai=ai,
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


def _load_ai_settings() -> AiSettings:
    enabled = _parse_bool(os.getenv("AI_ENABLED", "false"), "AI_ENABLED")
    provider = os.getenv("AI_PROVIDER", "ollama").strip() or "ollama"
    base_url = os.getenv("AI_BASE_URL", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    api_key = os.getenv("AI_API_KEY", "").strip()

    if enabled:
        missing = [
            name
            for name, value in (
                ("AI_BASE_URL", base_url),
                ("AI_MODEL", model),
                ("AI_API_KEY", api_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Environment variables are required when AI_ENABLED=true: "
                + ", ".join(missing)
            )

    return AiSettings(
        enabled=enabled,
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", ""}:
        return False

    raise RuntimeError(f"{name} must be a boolean value")
