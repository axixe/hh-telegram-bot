import unittest

from bot.main import (
    _apply_estimate_to_launch_options,
    _format_automation_preview,
    _get_automation_launch_options,
)
from bot.services.ai_dry_run_service import AI_DRY_RUN_ALL_TARGET
from bot.services.command_runner import VacancySearchEstimate


class AutomationPreviewTest(unittest.TestCase):
    def test_all_target_uses_available_pages_from_estimate(self) -> None:
        launch_options = _get_automation_launch_options(
            AI_DRY_RUN_ALL_TARGET,
            search_query="Frontend",
        )
        estimate = VacancySearchEstimate(
            search_query="Frontend",
            found=1600,
            pages=16,
            per_page=100,
            requested_pages=20,
        )

        launch_options = _apply_estimate_to_launch_options(launch_options, estimate)

        self.assertEqual(launch_options.total_pages, 16)
        self.assertEqual(estimate.available_count, 1600)

    def test_preview_separates_found_available_and_checked_count(self) -> None:
        launch_options = _get_automation_launch_options(
            AI_DRY_RUN_ALL_TARGET,
            search_query="Frontend",
        )
        estimate = VacancySearchEstimate(
            search_query="Frontend",
            found=1600,
            pages=10,
            per_page=100,
            requested_pages=20,
        )
        launch_options = _apply_estimate_to_launch_options(launch_options, estimate)

        text = _format_automation_preview(
            launch_options=launch_options,
            estimate=estimate,
        )

        self.assertIn("HH нашёл: <b>1600</b>", text)
        self.assertIn("доступно к проходу через API: <b>1000</b>", text)
        self.assertIn("бот проверит максимум: <b>1000</b>", text)


if __name__ == "__main__":
    unittest.main()
