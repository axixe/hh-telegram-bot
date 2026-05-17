import subprocess
import textwrap
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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

        while True:
            subprocess.run(base_command + ["refresh-token"], check=False)
            subprocess.run(base_command + ["update-resumes"], check=False)

            apply_command = base_command + ["apply-vacancies", "-f"]
            if letter_file:
                apply_command.extend(["-L", letter_file])
            apply_command.extend(["--excluded-filter", excluded_filter])
            subprocess.run(apply_command, check=False)

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

    def is_running(self, telegram_user_id: int) -> bool:
        return self.get_diagnostics(telegram_user_id).state == DockerContainerState.RUNNING

    def get_diagnostics(self, telegram_user_id: int) -> DockerDiagnostics:
        container_name = ProfileService.get_container_name(telegram_user_id)
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
