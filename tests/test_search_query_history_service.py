import tempfile
import unittest
from pathlib import Path

from bot.services.search_query_history_service import SearchQueryHistoryService


class SearchQueryHistoryServiceTest(unittest.TestCase):
    def test_add_query_deduplicates_and_keeps_latest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SearchQueryHistoryService(Path(temp_dir))

            service.add_query(123, "Frontend")
            service.add_query(123, "Python backend")
            service.add_query(123, " frontend ")

            self.assertEqual(
                service.get_queries(123),
                ["frontend", "Python backend"],
            )

    def test_history_is_limited_to_ten_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SearchQueryHistoryService(Path(temp_dir))

            for index in range(12):
                service.add_query(123, f"Query {index}")

            queries = service.get_queries(123)
            self.assertEqual(len(queries), 10)
            self.assertEqual(queries[0], "Query 11")
            self.assertEqual(queries[-1], "Query 2")

    def test_invalid_json_is_treated_as_empty_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            history_path = workdir / "config" / "tg_123" / "telegram_search_queries.json"
            history_path.parent.mkdir(parents=True)
            history_path.write_text("{", encoding="utf-8")

            service = SearchQueryHistoryService(workdir)

            self.assertEqual(service.get_queries(123), [])


if __name__ == "__main__":
    unittest.main()
