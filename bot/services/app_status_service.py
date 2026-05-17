from dataclasses import dataclass
from enum import Enum
from threading import Lock

from bot.services.command_runner import (
    CommandRunner,
    CommandRunnerError,
    DockerContainerState,
)


class AutomationStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class AppStatus:
    status: AutomationStatus

    @property
    def is_running(self) -> bool:
        return self.status == AutomationStatus.RUNNING

    @property
    def blocks_start(self) -> bool:
        return self.status in {
            AutomationStatus.STARTING,
            AutomationStatus.RUNNING,
            AutomationStatus.STOPPING,
        }

    @property
    def shows_stop_button(self) -> bool:
        return self.blocks_start


class AppStatusService:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner
        self._transient_statuses: dict[int, AutomationStatus] = {}
        self._lock = Lock()

    def get_status(self, telegram_user_id: int) -> AppStatus:
        with self._lock:
            transient_status = self._transient_statuses.get(telegram_user_id)
        if transient_status:
            return AppStatus(status=transient_status)

        try:
            diagnostics = self._command_runner.get_diagnostics(telegram_user_id)
        except CommandRunnerError:
            return AppStatus(status=AutomationStatus.FAILED)

        return AppStatus(status=self._map_docker_status(diagnostics.state, diagnostics.exit_code))

    def mark_starting(self, telegram_user_id: int) -> None:
        self._set_transient_status(telegram_user_id, AutomationStatus.STARTING)

    def mark_stopping(self, telegram_user_id: int) -> None:
        self._set_transient_status(telegram_user_id, AutomationStatus.STOPPING)

    def mark_failed(self, telegram_user_id: int) -> None:
        self._set_transient_status(telegram_user_id, AutomationStatus.FAILED)

    def clear_transient_status(self, telegram_user_id: int) -> None:
        with self._lock:
            self._transient_statuses.pop(telegram_user_id, None)

    def _set_transient_status(
        self,
        telegram_user_id: int,
        status: AutomationStatus,
    ) -> None:
        with self._lock:
            self._transient_statuses[telegram_user_id] = status

    def _map_docker_status(
        self,
        state: DockerContainerState,
        exit_code: int | None,
    ) -> AutomationStatus:
        if state == DockerContainerState.RUNNING:
            return AutomationStatus.RUNNING
        if state in {DockerContainerState.CREATED, DockerContainerState.RESTARTING}:
            return AutomationStatus.STARTING
        if state in {DockerContainerState.DEAD, DockerContainerState.UNKNOWN}:
            return AutomationStatus.FAILED
        if state == DockerContainerState.EXITED and exit_code not in (None, 0, 137, 143):
            return AutomationStatus.FAILED
        return AutomationStatus.STOPPED
