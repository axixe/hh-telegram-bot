import subprocess
import textwrap
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from bot.services.ai_dry_run_service import AiDryRunLaunchOptions
from bot.services.profile_service import ProfileService


class CommandRunnerError(RuntimeError):
    pass


class DockerContainerState(str, Enum):
    NOT_FOUND = "not_found"
    CREATED = "created"
    RESTARTING = "restarting"
    RUNNING = "running"
    PAUSED = "paused"
    EXITED = "exited"
    DEAD = "dead"
    REMOVING = "removing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DockerDiagnostics:
    container_name: str
    state: DockerContainerState
    status_text: str = ""
    exit_code: int | None = None
    error: str = ""

    @property
    def exists(self) -> bool:
        return self.state != DockerContainerState.NOT_FOUND


@dataclass(frozen=True)
class AiDryRunResult:
    output: str
    rejected_count: int
    already_rejected_count: int


@dataclass(frozen=True)
class AutomationLaunchOptions:
    target_count: int
    total_pages: int
    per_page: int
    ai_filter: str | None = None
    search_query: str | None = None


class CommandRunner:
    AUTOMATION_SCRIPT = textwrap.dedent(
        """
        import os
        import subprocess
        import time

        base_command = ["/usr/local/bin/python", "-m", "hh_applicant_tool"]
        excluded_filter = os.environ["HH_EXCLUDED_FILTER"]
        interval_seconds = int(os.getenv("HH_AUTOMATION_INTERVAL_SECONDS", "18000"))
        letter_file = os.getenv("HH_LETTER_FILE")
        total_pages = os.getenv("HH_AUTOMATION_TOTAL_PAGES")
        per_page = os.getenv("HH_AUTOMATION_PER_PAGE")
        ai_filter = os.getenv("HH_AUTOMATION_AI_FILTER")
        search_query = os.getenv("HH_AUTOMATION_SEARCH")
        run_once = os.getenv("HH_AUTOMATION_RUN_ONCE") == "1"

        while True:
            subprocess.run(base_command + ["refresh-token"], check=False)
            subprocess.run(base_command + ["update-resumes"], check=False)

            apply_command = base_command + ["apply-vacancies", "-f"]
            if letter_file:
                apply_command.extend(["-L", letter_file])
            if total_pages:
                apply_command.extend(["--total-pages", total_pages])
            if per_page:
                apply_command.extend(["--per-page", per_page])
            if ai_filter:
                apply_command.extend(["--ai-filter", ai_filter])
            if search_query:
                apply_command.extend(["--search", search_query])
            apply_command.extend(["--excluded-filter", excluded_filter])
            subprocess.run(apply_command, check=False)

            if run_once:
                break

            time.sleep(interval_seconds)
        """
    ).strip()

    RESUME_BUMP_SCRIPT = textwrap.dedent(
        """
        import os
        import subprocess
        import time

        base_command = ["/usr/local/bin/python", "-m", "hh_applicant_tool"]
        interval_seconds = int(os.environ["HH_RESUME_BUMP_INTERVAL_SECONDS"])

        while True:
            subprocess.run(base_command + ["refresh-token"], check=False)
            subprocess.run(base_command + ["update-resumes"], check=False)
            time.sleep(interval_seconds)
        """
    ).strip()

    EXCLUDED_FILTER = (
        r"junior|стажировк|bitrix|ddd|web3|crypto|blockchain|"
        r"дружн\\w+коллектив|полиграф|open\\s*space|опенспейс|"
        r"хакатон|конкурс|тестов\\w+ задан|soft skill"
    )

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    def start_main_automation(
        self,
        telegram_user_id: int,
        letter_file: Path | None = None,
        options: AutomationLaunchOptions | None = None,
    ) -> None:
        diagnostics = self.get_diagnostics(telegram_user_id)
        if diagnostics.state in {
            DockerContainerState.CREATED,
            DockerContainerState.RESTARTING,
            DockerContainerState.RUNNING,
        }:
            raise CommandRunnerError("Application is already running")

        profile_id = ProfileService.get_profile_id(telegram_user_id)
        container_name = ProfileService.get_container_name(telegram_user_id)
        command = [
            "docker",
            "compose",
            "run",
            "-d",
            "--name",
            container_name,
            "--no-deps",
            "--user",
            "docker",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            f"HH_PROFILE_ID={profile_id}",
            "-e",
            f"HH_EXCLUDED_FILTER={self.EXCLUDED_FILTER}",
        ]
        container_letter_file = self._get_container_letter_file(letter_file)
        if container_letter_file:
            command.extend(("-e", f"HH_LETTER_FILE={container_letter_file}"))
        if options:
            command.extend(("-e", f"HH_AUTOMATION_TOTAL_PAGES={options.total_pages}"))
            command.extend(("-e", f"HH_AUTOMATION_PER_PAGE={options.per_page}"))
            command.extend(("-e", "HH_AUTOMATION_RUN_ONCE=1"))
            if options.ai_filter:
                command.extend(("-e", f"HH_AUTOMATION_AI_FILTER={options.ai_filter}"))
            if options.search_query:
                command.extend(("-e", f"HH_AUTOMATION_SEARCH={options.search_query}"))
        command.extend(
            (
                "hh_applicant_tool",
                "python",
                "-u",
                "-c",
                self.AUTOMATION_SCRIPT,
            )
        )

        self._run(("docker", "rm", container_name), check=False, timeout=30)
        self._run(tuple(command))

    def run_ai_dry_run(
        self,
        telegram_user_id: int,
        letter_file: Path | None = None,
        *,
        ai_filter: str = "light",
        total_pages: int = 1,
        per_page: int = 3,
    ) -> AiDryRunResult:
        if ai_filter not in {"light", "heavy"}:
            raise CommandRunnerError("Unknown AI filter mode")

        diagnostics = self.get_diagnostics(telegram_user_id)
        if diagnostics.state in {
            DockerContainerState.CREATED,
            DockerContainerState.RESTARTING,
            DockerContainerState.RUNNING,
        }:
            raise CommandRunnerError("Application is already running")

        profile_id = ProfileService.get_profile_id(telegram_user_id)
        container_name = ProfileService.get_container_name(telegram_user_id)
        command = [
            "docker",
            "compose",
            "run",
            "--rm",
            "--name",
            container_name,
            "--no-deps",
            "--user",
            "docker",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            f"HH_PROFILE_ID={profile_id}",
            "hh_applicant_tool",
            "python",
            "-u",
            "-m",
            "hh_applicant_tool",
            "apply-vacancies",
            "-f",
            "--dry-run",
            "--ai-filter",
            ai_filter,
            "--ai-rate-limit",
            "20",
            "--total-pages",
            str(total_pages),
            "--per-page",
            str(per_page),
            "--excluded-filter",
            self.EXCLUDED_FILTER,
        ]
        container_letter_file = self._get_container_letter_file(letter_file)
        if container_letter_file:
            command.extend(("-L", container_letter_file))

        self._run(("docker", "rm", container_name), check=False, timeout=30)
        result = self._run(tuple(command), timeout=300)
        output = (result.stdout + "\n" + result.stderr).strip()
        return AiDryRunResult(
            output=output,
            rejected_count=output.count(f"AI ({ai_filter}) посчитал неподходящей"),
            already_rejected_count=output.count("Вакансия уже отклонена ранее"),
        )

    def start_ai_dry_run(
        self,
        telegram_user_id: int,
        options: AiDryRunLaunchOptions,
        letter_file: Path | None = None,
        *,
        ai_filter: str = "light",
    ) -> None:
        if ai_filter not in {"light", "heavy"}:
            raise CommandRunnerError("Unknown AI filter mode")

        diagnostics = self.get_diagnostics(telegram_user_id)
        if diagnostics.state in {
            DockerContainerState.CREATED,
            DockerContainerState.RESTARTING,
            DockerContainerState.RUNNING,
        }:
            raise CommandRunnerError("Application is already running")

        profile_id = ProfileService.get_profile_id(telegram_user_id)
        container_name = ProfileService.get_container_name(telegram_user_id)
        command = [
            "docker",
            "compose",
            "run",
            "-d",
            "--name",
            container_name,
            "--no-deps",
            "--user",
            "docker",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            f"HH_PROFILE_ID={profile_id}",
            "hh_applicant_tool",
            "python",
            "-u",
            "-m",
            "hh_applicant_tool",
            "-vv",
            "apply-vacancies",
            "-f",
            "--dry-run",
            "--ai-filter",
            ai_filter,
            "--ai-rate-limit",
            "20",
            "--total-pages",
            str(options.total_pages),
            "--per-page",
            str(options.per_page),
            "--excluded-filter",
            self.EXCLUDED_FILTER,
        ]
        if options.search_query:
            command.extend(("--search", options.search_query))
        container_letter_file = self._get_container_letter_file(letter_file)
        if container_letter_file:
            command.extend(("-L", container_letter_file))

        self._run(("docker", "rm", container_name), check=False, timeout=30)
        self._run(tuple(command))

    def get_container_logs(
        self,
        telegram_user_id: int,
        *,
        tail: int | str = 500,
    ) -> str:
        container_name = ProfileService.get_container_name(telegram_user_id)
        result = self._run(
            (
                "docker",
                "logs",
                "--tail",
                str(tail),
                container_name,
            ),
            check=False,
            timeout=20,
        )
        return (result.stdout + "\n" + result.stderr).strip()

    def clear_ai_rejected_vacancies(self, telegram_user_id: int) -> str:
        diagnostics = self.get_diagnostics(telegram_user_id)
        if diagnostics.state in {
            DockerContainerState.CREATED,
            DockerContainerState.RESTARTING,
            DockerContainerState.RUNNING,
            DockerContainerState.PAUSED,
        }:
            raise CommandRunnerError("Application is already running")

        profile_id = ProfileService.get_profile_id(telegram_user_id)
        result = self._run(
            (
                "docker",
                "compose",
                "run",
                "--rm",
                "--no-deps",
                "--user",
                "docker",
                "-e",
                f"HH_PROFILE_ID={profile_id}",
                "hh_applicant_tool",
                "python",
                "-u",
                "-m",
                "hh_applicant_tool",
                "clear-skipped",
                "--reason",
                "ai_rejected",
            ),
            check=False,
            timeout=120,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode != 0:
            raise CommandRunnerError(output or "hh-applicant-tool command failed")
        return output

    def stop_main_automation(self, telegram_user_id: int) -> None:
        container_name = ProfileService.get_container_name(telegram_user_id)
        diagnostics = self.get_diagnostics(telegram_user_id)
        if diagnostics.state not in {
            DockerContainerState.CREATED,
            DockerContainerState.RESTARTING,
            DockerContainerState.RUNNING,
            DockerContainerState.PAUSED,
        }:
            return

        self._run(("docker", "stop", container_name), timeout=30)
        self._run(("docker", "rm", container_name), timeout=30)

    def start_resume_bump(self, telegram_user_id: int, interval_hours: int) -> None:
        if interval_hours not in {4, 5}:
            raise CommandRunnerError("Unsupported resume bump interval")

        diagnostics = self.get_resume_bump_diagnostics(telegram_user_id)
        if diagnostics.state in {
            DockerContainerState.CREATED,
            DockerContainerState.RESTARTING,
            DockerContainerState.RUNNING,
        }:
            return

        profile_id = ProfileService.get_profile_id(telegram_user_id)
        container_name = ProfileService.get_resume_bump_container_name(telegram_user_id)
        command = [
            "docker",
            "compose",
            "run",
            "-d",
            "--name",
            container_name,
            "--no-deps",
            "--user",
            "docker",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            f"HH_PROFILE_ID={profile_id}",
            "-e",
            f"HH_RESUME_BUMP_INTERVAL_SECONDS={interval_hours * 60 * 60}",
            "hh_applicant_tool",
            "python",
            "-u",
            "-c",
            self.RESUME_BUMP_SCRIPT,
        ]

        self._run(("docker", "rm", container_name), check=False, timeout=30)
        self._run(tuple(command))

    def stop_resume_bump(self, telegram_user_id: int) -> None:
        container_name = ProfileService.get_resume_bump_container_name(telegram_user_id)
        diagnostics = self.get_resume_bump_diagnostics(telegram_user_id)
        if diagnostics.state not in {
            DockerContainerState.CREATED,
            DockerContainerState.RESTARTING,
            DockerContainerState.RUNNING,
            DockerContainerState.PAUSED,
        }:
            return

        self._run(("docker", "stop", container_name), timeout=30)
        self._run(("docker", "rm", container_name), timeout=30)

    def is_running(self, telegram_user_id: int) -> bool:
        return self.get_diagnostics(telegram_user_id).state == DockerContainerState.RUNNING

    def get_diagnostics(self, telegram_user_id: int) -> DockerDiagnostics:
        container_name = ProfileService.get_container_name(telegram_user_id)
        return self._get_diagnostics_by_container_name(container_name)

    def get_resume_bump_diagnostics(self, telegram_user_id: int) -> DockerDiagnostics:
        container_name = ProfileService.get_resume_bump_container_name(telegram_user_id)
        return self._get_diagnostics_by_container_name(container_name)

    def _get_diagnostics_by_container_name(self, container_name: str) -> DockerDiagnostics:
        result = self._run(
            (
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name=^/{container_name}$",
                "--format",
                "{{.Names}}\t{{.State}}\t{{.Status}}",
            ),
            check=False,
        )
        if result.returncode != 0:
            raise CommandRunnerError("Failed to inspect hh-applicant-tool container")

        line = result.stdout.strip().splitlines()
        if not line:
            return DockerDiagnostics(
                container_name=container_name,
                state=DockerContainerState.NOT_FOUND,
            )

        parts = line[0].split("\t", 2)
        if len(parts) < 2 or parts[0] != container_name:
            return DockerDiagnostics(
                container_name=container_name,
                state=DockerContainerState.UNKNOWN,
                status_text=line[0],
            )

        state = self._parse_docker_state(parts[1])
        status_text = parts[2] if len(parts) > 2 else ""
        exit_code, error = self._get_container_inspection(container_name)
        return DockerDiagnostics(
            container_name=container_name,
            state=state,
            status_text=status_text,
            exit_code=exit_code,
            error=error,
        )

    def _run(
        self,
        command: tuple[str, ...],
        *,
        check: bool = True,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if not self._workdir.exists():
            raise CommandRunnerError("hh-applicant-tool workdir does not exist")

        try:
            result = subprocess.run(
                list(command),
                cwd=self._workdir,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=timeout,
            )
        except OSError as exc:
            raise CommandRunnerError("Failed to run hh-applicant-tool command") from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandRunnerError("hh-applicant-tool command timed out") from exc

        if check and result.returncode != 0:
            raise CommandRunnerError("hh-applicant-tool command failed")

        return result

    def _get_container_inspection(self, container_name: str) -> tuple[int | None, str]:
        result = self._run(
            (
                "docker",
                "inspect",
                "--format",
                "{{.State.ExitCode}}\t{{.State.Error}}",
                container_name,
            ),
            check=False,
            timeout=20,
        )
        if result.returncode != 0:
            return None, ""

        parts = result.stdout.rstrip("\n").split("\t", 1)
        try:
            exit_code = int(parts[0])
        except ValueError:
            exit_code = None

        error = parts[1].strip() if len(parts) > 1 else ""
        return exit_code, error

    def _parse_docker_state(self, raw_state: str) -> DockerContainerState:
        normalized = raw_state.strip().lower()
        for state in DockerContainerState:
            if state.value == normalized:
                return state
        return DockerContainerState.UNKNOWN

    def _get_container_letter_file(self, letter_file: Path | None) -> str | None:
        if not letter_file or not letter_file.exists():
            return None

        try:
            relative_path = letter_file.resolve().relative_to(self._workdir)
        except ValueError as exc:
            raise CommandRunnerError("Letter file is outside hh-applicant-tool") from exc

        return "/app/" + "/".join(relative_path.parts)
