import unittest

from bot.services.app_status_service import AppStatusService, AutomationStatus
from bot.services.automation_lock_service import AutomationLockService
from bot.services.command_runner import DockerContainerState, DockerDiagnostics


class FakeCommandRunner:
    def __init__(self, diagnostics: DockerDiagnostics) -> None:
        self.diagnostics = diagnostics

    def get_diagnostics(self, telegram_user_id: int) -> DockerDiagnostics:
        return self.diagnostics


class AutomationLockServiceTest(unittest.TestCase):
    def test_lock_blocks_second_acquire_until_release(self) -> None:
        service = AutomationLockService()

        self.assertTrue(service.acquire_automation_lock(123))
        self.assertFalse(service.acquire_automation_lock(123))

        service.release_automation_lock(123)

        self.assertTrue(service.acquire_automation_lock(123))


class AppStatusServiceTest(unittest.TestCase):
    def test_maps_running_container_to_running_status(self) -> None:
        service = AppStatusService(
            FakeCommandRunner(
                DockerDiagnostics(
                    container_name="container",
                    state=DockerContainerState.RUNNING,
                )
            )
        )

        status = service.get_status(123)

        self.assertEqual(status.status, AutomationStatus.RUNNING)
        self.assertTrue(status.blocks_start)
        self.assertTrue(status.shows_stop_button)

    def test_maps_nonzero_exited_container_to_failed_status(self) -> None:
        service = AppStatusService(
            FakeCommandRunner(
                DockerDiagnostics(
                    container_name="container",
                    state=DockerContainerState.EXITED,
                    exit_code=1,
                )
            )
        )

        status = service.get_status(123)

        self.assertEqual(status.status, AutomationStatus.FAILED)
        self.assertFalse(status.blocks_start)

    def test_transient_status_overrides_docker_status(self) -> None:
        service = AppStatusService(
            FakeCommandRunner(
                DockerDiagnostics(
                    container_name="container",
                    state=DockerContainerState.NOT_FOUND,
                )
            )
        )

        service.mark_starting(123)

        self.assertEqual(service.get_status(123).status, AutomationStatus.STARTING)

        service.clear_transient_status(123)

        self.assertEqual(service.get_status(123).status, AutomationStatus.STOPPED)


if __name__ == "__main__":
    unittest.main()
