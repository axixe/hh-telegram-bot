from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess

from bot.services.profile_service import ProfileService


class AutomationStatsServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutomationStats:
    responses_count: int = 0
    tests_count: int = 0
    discards_count: int = 0
    invitations_count: int = 0


@dataclass(frozen=True)
class PeriodStats:
    responses_count: int = 0
    tests_count: int = 0
    discards_count: int = 0
    invitations_count: int = 0


class AutomationStatsService:
    SENT_RESPONSES_PATTERN = re.compile(r"Отправлено:\s*(\d+)")
    SENT_RESPONSE_TEXT = "Отправили отклик на вакансию"
    SENT_TEST_RESPONSE_TEXT = "Отправили отклик на вакансию с тестом"
    HISTORY_FILENAME = "telegram_automation_stats.json"

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    def get_stats(self, telegram_user_id: int) -> AutomationStats:
        logs = self._get_container_logs(telegram_user_id)
        by_state = self._get_negotiations_by_state(telegram_user_id)

        return AutomationStats(
            responses_count=self._count_responses_from_logs(logs),
            tests_count=logs.count(self.SENT_TEST_RESPONSE_TEXT),
            discards_count=by_state.get("discard", 0),
            invitations_count=by_state.get("invitation", 0),
        )

    def format_status(self, stats: AutomationStats) -> str:
        return self.format_status_with_state(stats, is_running=True)

    def format_status_with_state(
        self,
        stats: AutomationStats,
        *,
        is_running: bool,
    ) -> str:
        status = "запущен" if is_running else "остановлен"
        status_icon = "🟢" if is_running else "⚪"
        return (
            f"{status_icon} <b>Авто-отклик бот {status}</b>\n\n"
            "📨 <b>Сессия</b>\n"
            f"• Откликов отправлено: <b>{stats.responses_count}</b>\n"
            f"• Тестов выполнено: <b>{stats.tests_count}</b>\n\n"
            "📬 <b>HH</b>\n"
            f"• Отказов: <b>{stats.discards_count}</b>\n"
            f"• Приглашений: <b>{stats.invitations_count}</b>"
        )

    def get_period_stats(self, telegram_user_id: int) -> dict[str, PeriodStats]:
        now = datetime.now()
        starts = {
            "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
            "week": now - timedelta(days=7),
            "month": now - timedelta(days=30),
        }
        db_stats = {
            name: self._get_negotiations_period_stats(telegram_user_id, start)
            for name, start in starts.items()
        }
        tests_by_period = self._get_tests_by_period(telegram_user_id, starts)
        history_stats = {
            name: self._get_history_period_stats(telegram_user_id, start)
            for name, start in starts.items()
        }

        return {
            name: PeriodStats(
                responses_count=(
                    stats.get("total", 0)
                    + history_stats[name].responses_count
                ),
                tests_count=(
                    tests_by_period.get(name, 0)
                    + history_stats[name].tests_count
                ),
                discards_count=stats.get("discard", 0),
                invitations_count=stats.get("invitation", 0),
            )
            for name, stats in db_stats.items()
        }

    def record_session(self, telegram_user_id: int, stats: AutomationStats) -> None:
        if stats.responses_count <= 0 and stats.tests_count <= 0:
            return

        history = self._read_history(telegram_user_id)
        history.append(
            {
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "responses_count": stats.responses_count,
                "tests_count": stats.tests_count,
            }
        )
        path = self._get_history_path(telegram_user_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(history[-200:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise AutomationStatsServiceError("Failed to save automation stats") from exc

    def format_period_stats(self, stats: dict[str, PeriodStats]) -> str:
        return (
            "📊 <b>Статистика</b>\n\n"
            f"{self._format_period('Сегодня', stats['today'])}\n\n"
            f"{self._format_period('7 дней', stats['week'])}\n\n"
            f"{self._format_period('30 дней', stats['month'])}"
        )

    def _get_container_logs(
        self,
        telegram_user_id: int,
        *,
        with_timestamps: bool = False,
    ) -> str:
        container_name = ProfileService.get_container_name(telegram_user_id)
        command = ["docker", "logs", "--tail", "5000"]
        if with_timestamps:
            command.append("--timestamps")
        command.append(container_name)
        result = self._run(tuple(command), check=False, timeout=20)
        if result.returncode != 0:
            return ""

        return result.stdout + result.stderr

    def _get_negotiations_by_state(self, telegram_user_id: int) -> dict[str, int]:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        db_path = self._workdir / "config" / profile_id / "data"
        if not db_path.exists():
            return {}

        try:
            with sqlite3.connect(db_path) as connection:
                cursor = connection.execute(
                    "SELECT state, count(*) FROM negotiations GROUP BY state"
                )
                return {str(state): int(count) for state, count in cursor.fetchall()}
        except sqlite3.Error:
            return {}

    def _count_responses_from_logs(self, logs: str) -> int:
        sent_lines_count = logs.count(self.SENT_RESPONSE_TEXT)
        if sent_lines_count:
            return sent_lines_count

        total = 0
        for match in self.SENT_RESPONSES_PATTERN.finditer(logs):
            total += int(match.group(1))
        return total

    def _get_negotiations_period_stats(
        self,
        telegram_user_id: int,
        start: datetime,
    ) -> dict[str, int]:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        db_path = self._workdir / "config" / profile_id / "data"
        if not db_path.exists():
            return {}

        try:
            with sqlite3.connect(db_path) as connection:
                cursor = connection.execute(
                    """
                    SELECT state, count(*)
                    FROM negotiations
                    WHERE created_at >= ?
                    GROUP BY state
                    """,
                    (start.strftime("%Y-%m-%d %H:%M:%S"),),
                )
                by_state = {str(state): int(count) for state, count in cursor.fetchall()}
                by_state["total"] = sum(by_state.values())
                return by_state
        except sqlite3.Error:
            return {}

    def _get_tests_by_period(
        self,
        telegram_user_id: int,
        starts: dict[str, datetime],
    ) -> dict[str, int]:
        logs = self._get_container_logs(telegram_user_id, with_timestamps=True)
        counters = {name: 0 for name in starts}
        for line in logs.splitlines():
            if self.SENT_TEST_RESPONSE_TEXT not in line:
                continue
            timestamp = self._parse_docker_timestamp(line)
            if not timestamp:
                continue
            local_timestamp = timestamp.astimezone().replace(tzinfo=None)
            for name, start in starts.items():
                if local_timestamp >= start:
                    counters[name] += 1
        return counters

    def _parse_docker_timestamp(self, line: str) -> datetime | None:
        raw_timestamp = line.split(" ", 1)[0]
        try:
            if raw_timestamp.endswith("Z"):
                return datetime.fromisoformat(
                    raw_timestamp.removesuffix("Z")
                ).replace(tzinfo=timezone.utc)
            return datetime.fromisoformat(raw_timestamp)
        except ValueError:
            return None

    def _format_period(self, title: str, stats: PeriodStats) -> str:
        return (
            f"🗓 <b>{title}</b>\n"
            f"• Откликов: <b>{stats.responses_count}</b>\n"
            f"• Отказов: <b>{stats.discards_count}</b>\n"
            f"• Приглашений: <b>{stats.invitations_count}</b>\n"
            f"• Тестов выполнено: <b>{stats.tests_count}</b>"
        )

    def _get_history_period_stats(
        self,
        telegram_user_id: int,
        start: datetime,
    ) -> PeriodStats:
        responses_count = 0
        tests_count = 0
        for item in self._read_history(telegram_user_id):
            try:
                finished_at = datetime.fromisoformat(str(item["finished_at"]))
            except (KeyError, ValueError):
                continue
            if finished_at < start:
                continue
            responses_count += int(item.get("responses_count") or 0)
            tests_count += int(item.get("tests_count") or 0)

        return PeriodStats(
            responses_count=responses_count,
            tests_count=tests_count,
        )

    def _read_history(self, telegram_user_id: int) -> list[dict]:
        path = self._get_history_path(telegram_user_id)
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        return data if isinstance(data, list) else []

    def _get_history_path(self, telegram_user_id: int) -> Path:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        return self._workdir / "config" / profile_id / self.HISTORY_FILENAME

    def _run(
        self,
        command: tuple[str, ...],
        *,
        check: bool = True,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if not self._workdir.exists():
            raise AutomationStatsServiceError("hh-applicant-tool workdir does not exist")

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
            raise AutomationStatsServiceError("Failed to read automation stats") from exc
        except subprocess.TimeoutExpired as exc:
            raise AutomationStatsServiceError("Reading automation stats timed out") from exc

        if check and result.returncode != 0:
            raise AutomationStatsServiceError("Failed to read automation stats")

        return result
