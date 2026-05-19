import subprocess
import tempfile
import unittest
from pathlib import Path

from bot.services.command_runner import (
    AiDryRunResult,
    AutomationLaunchOptions,
    CommandRunner,
    DockerContainerState,
    DockerDiagnostics,
)
from bot.services.ai_dry_run_service import get_ai_dry_run_launch_options


class FakeCommandRunner(CommandRunner):
    def __init__(self, workdir: Path) -> None:
        super().__init__(workdir)
        self.commands: list[tuple[str, ...]] = []
        self.resume_bump_state = DockerContainerState.NOT_FOUND

    def get_diagnostics(self, telegram_user_id: int) -> DockerDiagnostics:
        return DockerDiagnostics(
            container_name=f"hh_applicant_tool_tg_{telegram_user_id}",
            state=DockerContainerState.NOT_FOUND,
        )

    def get_resume_bump_diagnostics(self, telegram_user_id: int) -> DockerDiagnostics:
        return DockerDiagnostics(
            container_name=f"hh_applicant_tool_tg_{telegram_user_id}_resume_bump",
            state=self.resume_bump_state,
        )

    def _run(
        self,
        command: tuple[str, ...],
        *,
        check: bool = True,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=0,
            stdout=(
                "🧠 AI (light) посчитал неподходящей https://example.test\n"
                "⏩ Вакансия уже отклонена ранее https://example.test/old\n"
            ),
            stderr="",
        )


class CommandRunnerAiDryRunTest(unittest.TestCase):
    def test_run_ai_dry_run_uses_safe_dry_run_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner(Path(tmp))

            result = runner.run_ai_dry_run(123)

        command = runner.commands[-1]
        self.assertIsInstance(result, AiDryRunResult)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(result.already_rejected_count, 1)
        self.assertIn("--rm", command)
        self.assertIn("--name", command)
        self.assertIn("hh_applicant_tool_tg_123", command)
        self.assertIn("--dry-run", command)
        self.assertIn("--ai-filter", command)
        self.assertIn("light", command)
        self.assertIn("--total-pages", command)
        self.assertIn("1", command)
        self.assertIn("--per-page", command)
        self.assertIn("3", command)
        self.assertNotIn("shell=True", command)

    def test_start_main_automation_passes_limit_and_ai_filter_to_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner(Path(tmp))

            runner.start_main_automation(
                123,
                options=AutomationLaunchOptions(
                    target_count=30,
                    total_pages=1,
                    per_page=30,
                    ai_filter="heavy",
                    search_query="Frontend-разработчик",
                ),
            )

        command = runner.commands[-1]
        self.assertIn("HH_AUTOMATION_TOTAL_PAGES=1", command)
        self.assertIn("HH_AUTOMATION_PER_PAGE=30", command)
        self.assertIn("HH_AUTOMATION_RUN_ONCE=1", command)
        self.assertIn("HH_AUTOMATION_AI_FILTER=heavy", command)
        self.assertIn("HH_AUTOMATION_SEARCH=Frontend-разработчик", command)

    def test_start_ai_dry_run_uses_live_detached_arguments_for_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner(Path(tmp))

            runner.start_ai_dry_run(
                123,
                get_ai_dry_run_launch_options(
                    30,
                    "heavy",
                    search_query="Frontend-разработчик",
                ),
                ai_filter="heavy",
            )

        command = runner.commands[-1]
        self.assertIn("-d", command)
        self.assertIn("--name", command)
        self.assertIn("hh_applicant_tool_tg_123", command)
        self.assertIn("-vv", command)
        self.assertIn("--dry-run", command)
        self.assertIn("--ai-filter", command)
        self.assertIn("heavy", command)
        self.assertIn("--total-pages", command)
        self.assertIn("4", command)
        self.assertIn("--per-page", command)
        self.assertIn("100", command)
        self.assertIn("--search", command)
        self.assertIn("Frontend-разработчик", command)

    def test_launch_options_map_targets_to_candidate_buffer(self) -> None:
        self.assertEqual(get_ai_dry_run_launch_options(10).total_pages, 2)
        self.assertEqual(get_ai_dry_run_launch_options(10).per_page, 100)
        self.assertEqual(get_ai_dry_run_launch_options(30).total_pages, 4)
        self.assertEqual(get_ai_dry_run_launch_options(30).per_page, 100)
        self.assertEqual(get_ai_dry_run_launch_options(50).total_pages, 6)
        self.assertEqual(get_ai_dry_run_launch_options(50).per_page, 100)
        self.assertEqual(get_ai_dry_run_launch_options(50, "heavy").ai_filter, "heavy")
        self.assertEqual(get_ai_dry_run_launch_options(0).total_pages, 20)
        self.assertEqual(get_ai_dry_run_launch_options(0).per_page, 100)
        self.assertEqual(
            get_ai_dry_run_launch_options(
                0,
                search_query="Frontend-разработчик",
            ).search_query,
            "Frontend-разработчик",
        )

    def test_clear_ai_rejected_vacancies_uses_safe_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner(Path(tmp))

            runner.clear_ai_rejected_vacancies(123)

        command = runner.commands[-1]
        self.assertIn("clear-skipped", command)
        self.assertIn("--reason", command)
        self.assertIn("ai_rejected", command)
        self.assertIn("HH_PROFILE_ID=tg_123", command)

    def test_start_resume_bump_uses_separate_container_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner(Path(tmp))

            runner.start_resume_bump(123, 4)

        command = runner.commands[-1]
        command_text = " ".join(command)
        self.assertIn("-d", command)
        self.assertIn("--name", command)
        self.assertIn("hh_applicant_tool_tg_123_resume_bump", command)
        self.assertIn("HH_PROFILE_ID=tg_123", command)
        self.assertIn("HH_RESUME_BUMP_INTERVAL_SECONDS=14400", command)
        self.assertIn("refresh-token", command_text)
        self.assertIn("update-resumes", command_text)
        self.assertNotIn("apply-vacancies", command_text)

    def test_start_resume_bump_does_not_duplicate_running_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner(Path(tmp))
            runner.resume_bump_state = DockerContainerState.RUNNING

            runner.start_resume_bump(123, 5)

        self.assertEqual(runner.commands, [])

    def test_stop_resume_bump_stops_separate_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner(Path(tmp))
            runner.resume_bump_state = DockerContainerState.RUNNING

            runner.stop_resume_bump(123)

        self.assertEqual(
            runner.commands,
            [
                ("docker", "stop", "hh_applicant_tool_tg_123_resume_bump"),
                ("docker", "rm", "hh_applicant_tool_tg_123_resume_bump"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
