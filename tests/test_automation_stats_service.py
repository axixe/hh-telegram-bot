from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from bot.services.automation_stats_service import (
    AutomationStats,
    AutomationStatsService,
)


class FakeAutomationStatsService(AutomationStatsService):
    def __init__(self, workdir: Path, logs: str = "") -> None:
        super().__init__(workdir)
        self.logs = logs

    def _get_container_logs(
        self,
        telegram_user_id: int,
        *,
        with_timestamps: bool = False,
    ) -> str:
        return self.logs


class AutomationStatsServiceTest(unittest.TestCase):
    def test_period_stats_include_recorded_session_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = FakeAutomationStatsService(Path(temp_dir))

            service.record_session(
                123,
                AutomationStats(responses_count=3, tests_count=1),
            )

            stats = service.get_period_stats(123)

            self.assertEqual(stats["today"].responses_count, 3)
            self.assertEqual(stats["today"].tests_count, 1)
            self.assertEqual(stats["week"].responses_count, 3)
            self.assertEqual(stats["month"].tests_count, 1)

    def test_period_stats_can_include_current_session_logs(self) -> None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        logs = "\n".join(
            [
                f"{timestamp} 📨 Отправили отклик на вакансию https://hh.ru/vacancy/1",
                f"{timestamp} 📨 Отправили отклик на вакансию с тестом https://hh.ru/vacancy/2",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            service = FakeAutomationStatsService(Path(temp_dir), logs=logs)

            stats_without_logs = service.get_period_stats(123)
            stats_with_logs = service.get_period_stats(
                123,
                include_current_session=True,
            )

            self.assertEqual(stats_without_logs["today"].responses_count, 0)
            self.assertEqual(stats_with_logs["today"].responses_count, 2)
            self.assertEqual(stats_with_logs["today"].tests_count, 1)

    def test_period_stats_include_negotiations_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            profile_dir = workdir / "config" / "tg_123"
            profile_dir.mkdir(parents=True)
            db_path = profile_dir / "data"

            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE negotiations (
                        id INTEGER PRIMARY KEY,
                        state TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.executemany(
                    "INSERT INTO negotiations (state, created_at) VALUES (?, ?)",
                    [
                        ("response", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        ("discard", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        (
                            "invitation",
                            (datetime.now() - timedelta(days=40)).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            service = FakeAutomationStatsService(workdir)
            stats = service.get_period_stats(123)

            self.assertEqual(stats["today"].responses_count, 2)
            self.assertEqual(stats["today"].discards_count, 1)
            self.assertEqual(stats["today"].invitations_count, 0)
            self.assertEqual(stats["month"].responses_count, 2)

    def test_parse_automation_summary_reads_last_machine_line(self) -> None:
        service = FakeAutomationStatsService(Path("."))

        summary = service.parse_automation_summary(
            "\n".join(
                [
                    "ordinary log",
                    'TELEGRAM_AUTOMATION_SUMMARY {"duration_seconds": 12, "search": "Frontend", "found_count": 1600, "available_count": 1000, "processed_count": 42, "responses_count": 5, "tests_count": 1, "already_ai_rejected_count": 7, "ai_rejected_count": 9, "excluded_filter_count": 3, "limit_reached": true}',
                ]
            )
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.duration_seconds, 12)
        self.assertEqual(summary.search_query, "Frontend")
        self.assertEqual(summary.found_count, 1600)
        self.assertEqual(summary.available_count, 1000)
        self.assertEqual(summary.processed_count, 42)
        self.assertEqual(summary.responses_count, 5)
        self.assertEqual(summary.tests_count, 1)
        self.assertEqual(summary.already_ai_rejected_count, 7)
        self.assertEqual(summary.ai_rejected_count, 9)
        self.assertEqual(summary.excluded_filter_count, 3)
        self.assertTrue(summary.limit_reached)


if __name__ == "__main__":
    unittest.main()
