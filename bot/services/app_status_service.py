from dataclasses import dataclass

from bot.services.command_runner import CommandRunner, CommandRunnerError


@dataclass(frozen=True)
class AppStatus:
    is_running: bool


class AppStatusService:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner

    def get_status(self, telegram_user_id: int) -> AppStatus:
        try:
            return AppStatus(is_running=self._command_runner.is_running(telegram_user_id))
        except CommandRunnerError:
            return AppStatus(is_running=False)
