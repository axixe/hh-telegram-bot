import json
from pathlib import Path

from bot.services.profile_service import ProfileService


class SearchQueryHistoryServiceError(RuntimeError):
    pass


class SearchQueryHistoryService:
    HISTORY_FILENAME = "telegram_search_queries.json"
    MAX_ITEMS = 10

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    def get_queries(self, telegram_user_id: int, *, limit: int | None = None) -> list[str]:
        queries = self._read_queries(telegram_user_id)
        return queries[:limit] if limit is not None else queries

    def add_query(self, telegram_user_id: int, query: str) -> list[str]:
        normalized_query = " ".join(query.split())
        if not normalized_query:
            return self.get_queries(telegram_user_id)

        queries = [
            existing
            for existing in self._read_queries(telegram_user_id)
            if existing.casefold() != normalized_query.casefold()
        ]
        queries.insert(0, normalized_query)
        queries = queries[: self.MAX_ITEMS]

        path = self._get_history_path(telegram_user_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(queries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise SearchQueryHistoryServiceError("Failed to save search query history") from exc

        return queries

    def _read_queries(self, telegram_user_id: int) -> list[str]:
        path = self._get_history_path(telegram_user_id)
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(data, list):
            return []

        queries: list[str] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, str):
                continue
            query = " ".join(item.split())
            key = query.casefold()
            if not query or key in seen:
                continue
            seen.add(key)
            queries.append(query)
            if len(queries) >= self.MAX_ITEMS:
                break

        return queries

    def _get_history_path(self, telegram_user_id: int) -> Path:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        return self._workdir / "config" / profile_id / self.HISTORY_FILENAME
