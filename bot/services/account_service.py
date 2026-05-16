from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from bot.services.profile_service import ProfileService


class AccountServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResumeSummary:
    title: str
    status: str
    total_views: int
    new_views: int


@dataclass(frozen=True)
class AccountSummary:
    is_authorized: bool
    full_name: str | None = None
    resumes_count: int = 0
    unread_negotiations: int = 0
    total_negotiations: int = 0
    resumes: tuple[ResumeSummary, ...] = ()


class AccountService:
    SUMMARY_SCRIPT = (
        "import sys;"
        "from hh_applicant_tool.main import HHApplicantTool;"
        "tool=HHApplicantTool();"
        "sys.exit(tool.run(['--config-dir','/app/config','api','/me']) or 0)"
    )

    RESUMES_SCRIPT = (
        "import sys;"
        "from hh_applicant_tool.main import HHApplicantTool;"
        "tool=HHApplicantTool();"
        "sys.exit(tool.run(['--config-dir','/app/config','api','/resumes/mine']) or 0)"
    )

    LOGOUT_SCRIPT = (
        "from hh_applicant_tool.main import HHApplicantTool;"
        "tool=HHApplicantTool();"
        "tool.run(['--config-dir','/app/config','logout']);"
        "tool.config.save(token={})"
    )

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    def get_summary(self, telegram_user_id: int) -> AccountSummary:
        me = self._get_json_from_tool(telegram_user_id, self.SUMMARY_SCRIPT)
        resumes_response = self._get_json_from_tool(telegram_user_id, self.RESUMES_SCRIPT)
        resumes = self._parse_resumes(resumes_response)
        counters = me.get("counters", {})

        return AccountSummary(
            is_authorized=True,
            full_name=self._format_full_name(me),
            resumes_count=int(counters.get("resumes_count") or len(resumes)),
            unread_negotiations=int(counters.get("unread_negotiations") or 0),
            total_negotiations=self._count_negotiations(telegram_user_id),
            resumes=tuple(resumes),
        )

    def is_authorized(self, telegram_user_id: int) -> bool:
        try:
            return self.get_summary(telegram_user_id).is_authorized
        except AccountServiceError:
            return False

    def logout(self, telegram_user_id: int) -> None:
        result = self._run_tool_script(telegram_user_id, self.LOGOUT_SCRIPT)
        if result.returncode != 0:
            raise AccountServiceError("hh-applicant-tool logout failed")

    def _get_json_from_tool(self, telegram_user_id: int, script: str) -> dict[str, Any]:
        result = self._run_tool_script(telegram_user_id, script)
        if result.returncode != 0:
            raise AccountServiceError("hh-applicant-tool account check failed")

        for line in reversed(result.stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

        raise AccountServiceError("hh-applicant-tool returned invalid JSON")

    def _run_tool_script(
        self,
        telegram_user_id: int,
        script: str,
    ) -> subprocess.CompletedProcess[str]:
        if not self._workdir.exists():
            raise AccountServiceError("hh-applicant-tool workdir does not exist")

        profile_id = ProfileService.get_profile_id(telegram_user_id)
        command = [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--user",
            "docker",
            "hh_applicant_tool",
            "python",
            "-c",
            self._with_profile(script, profile_id),
        ]

        try:
            return subprocess.run(
                command,
                cwd=self._workdir,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=90,
            )
        except OSError as exc:
            raise AccountServiceError("Failed to run hh-applicant-tool") from exc
        except subprocess.TimeoutExpired as exc:
            raise AccountServiceError("hh-applicant-tool account check timed out") from exc

    @staticmethod
    def _format_full_name(user: dict[str, Any]) -> str:
        parts = [
            user.get("last_name"),
            user.get("first_name"),
            user.get("middle_name"),
        ]
        return " ".join(str(part).strip() for part in parts if part) or "Аккаунт HH"

    @staticmethod
    def _parse_resumes(response: dict[str, Any]) -> list[ResumeSummary]:
        items = response.get("items", [])
        resumes: list[ResumeSummary] = []
        for item in items:
            resumes.append(
                ResumeSummary(
                    title=str(item.get("title") or "Без названия"),
                    status=str(item.get("status", {}).get("name") or "статус неизвестен"),
                    total_views=int(item.get("total_views") or 0),
                    new_views=int(item.get("new_views") or 0),
                )
            )
        return resumes

    def _count_negotiations(self, telegram_user_id: int) -> int:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        db_path = self._workdir / "config" / profile_id / "data"
        if not db_path.exists():
            return 0

        try:
            with sqlite3.connect(db_path) as connection:
                cursor = connection.execute("SELECT count(*) FROM negotiations")
                value = cursor.fetchone()
        except sqlite3.Error:
            return 0

        return int(value[0]) if value else 0

    @staticmethod
    def _with_profile(script: str, profile_id: str) -> str:
        return (
            "import os;"
            f"os.environ['HH_PROFILE_ID']={profile_id!r};"
            f"{script}"
        )


def format_account_summary(summary: AccountSummary) -> str:
    lines = [
        "Вы уже авторизованы в HH.",
        "",
        f"Аккаунт: {summary.full_name or 'HH'}",
        f"Резюме: {summary.resumes_count}",
        f"Непрочитанные отклики: {summary.unread_negotiations}",
        f"Отклики в локальной базе: {summary.total_negotiations}",
    ]

    if summary.resumes:
        lines.append("")
        lines.append("Резюме:")
        for resume in summary.resumes[:5]:
            lines.append(
                f"- {resume.title} ({resume.status}), просмотры: "
                f"{resume.total_views}, новые: {resume.new_views}"
            )

    return "\n".join(lines)
