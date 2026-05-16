from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import threading
import time
from collections import deque

from bot.services.account_service import AccountService
from bot.services.profile_service import ProfileService


@dataclass(frozen=True)
class AuthResult:
    is_success: bool
    user_message: str
    keep_waiting: bool = True
    requires_captcha: bool = False
    captcha_path: Path | None = None


class AuthService:
    AUTH_TIMEOUT_SECONDS = 120

    def __init__(self, account_service: AccountService, workdir: Path) -> None:
        self._account_service = account_service
        self._workdir = workdir
        self._pending_phones_by_user_id: dict[int, str] = {}
        self._processes_by_user_id: dict[int, subprocess.Popen[str]] = {}
        self._output_threads_by_user_id: dict[int, threading.Thread] = {}
        self._outputs_by_user_id: dict[int, deque[str]] = {}
        self._locks_by_user_id: dict[int, threading.Lock] = {}
        self._submitted_codes_by_user_id: set[int] = set()
        self._submitted_captchas_by_user_id: set[int] = set()
        self._authorized_user_ids: set[int] = set()

    def start_phone_authorization(self, telegram_user_id: int, phone: str) -> AuthResult:
        normalized_phone = self._normalize_phone(phone)
        if not self._is_valid_phone(normalized_phone):
            return AuthResult(
                is_success=False,
                user_message="Похоже, номер введён неверно. Отправьте номер в формате +79991234567.",
            )

        self._terminate_auth_process(telegram_user_id)
        self._pending_phones_by_user_id[telegram_user_id] = normalized_phone
        captcha_path = self._get_captcha_path(telegram_user_id)
        if captcha_path.exists():
            captcha_path.unlink()

        try:
            process = self._start_auth_process(telegram_user_id, normalized_phone)
        except OSError:
            self._pending_phones_by_user_id.pop(telegram_user_id, None)
            return AuthResult(
                is_success=False,
                user_message=(
                    "Не получилось запустить авторизацию hh-applicant-tool. "
                    "Проверьте Docker и попробуйте ещё раз."
                ),
            )

        self._processes_by_user_id[telegram_user_id] = process
        self._start_output_reader(telegram_user_id, process)
        prompt = self._wait_for_auth_prompt(telegram_user_id, process)
        if prompt == "captcha":
            return AuthResult(
                is_success=True,
                user_message="HH попросил капчу. Введите текст с картинки.",
                requires_captcha=True,
                captcha_path=self._get_captcha_path(telegram_user_id),
            )

        if prompt != "sms":
            output = self._get_auth_output(telegram_user_id)
            self._cleanup_auth_process(telegram_user_id)
            return AuthResult(
                is_success=False,
                user_message=self._format_start_failure(output),
            )

        return AuthResult(
            is_success=True,
            user_message="HH отправил код. Введите SMS-код сюда.",
        )

    def submit_captcha(self, telegram_user_id: int, captcha_text: str) -> AuthResult:
        normalized_captcha = captcha_text.strip()
        if not normalized_captcha:
            return AuthResult(
                is_success=False,
                user_message="Введите текст с картинки.",
            )

        if telegram_user_id in self._submitted_captchas_by_user_id:
            return AuthResult(
                is_success=False,
                user_message="Капча уже отправлена. Подождите результат.",
            )

        process = self._processes_by_user_id.get(telegram_user_id)
        if (
            not process
            or process.poll() is not None
            or not process.stdin
            or process.stdin.closed
        ):
            self._cleanup_auth_process(telegram_user_id)
            return AuthResult(
                is_success=False,
                user_message="Процесс входа уже завершился. Отправьте номер телефона ещё раз.",
                keep_waiting=False,
            )

        try:
            self._submitted_captchas_by_user_id.add(telegram_user_id)
            process.stdin.write(f"{normalized_captcha}\n")
            process.stdin.flush()
        except OSError:
            self._terminate_auth_process(telegram_user_id)
            return AuthResult(
                is_success=False,
                user_message="Не получилось отправить капчу. Отправьте номер телефона ещё раз.",
                keep_waiting=False,
            )

        prompt = self._wait_for_auth_prompt(telegram_user_id, process)
        if prompt == "sms":
            return AuthResult(
                is_success=True,
                user_message="Капча принята. HH отправил код. Введите SMS-код сюда.",
            )

        self._cleanup_auth_process(telegram_user_id)
        return AuthResult(
            is_success=False,
            user_message="HH не принял капчу или не отправил SMS. Отправьте номер телефона ещё раз.",
            keep_waiting=False,
        )

    def submit_sms_code(self, telegram_user_id: int, sms_code: str) -> AuthResult:
        lock = self._get_user_lock(telegram_user_id)
        if not lock.acquire(blocking=False):
            return AuthResult(
                is_success=False,
                user_message="Код уже проверяется. Подождите немного.",
            )
        try:
            return self._submit_sms_code_locked(telegram_user_id, sms_code)
        finally:
            lock.release()

    def _submit_sms_code_locked(self, telegram_user_id: int, sms_code: str) -> AuthResult:
        if telegram_user_id not in self._pending_phones_by_user_id:
            return AuthResult(
                is_success=False,
                user_message="Сначала отправьте номер телефона.",
                keep_waiting=False,
            )

        normalized_code = sms_code.strip()
        if not self._is_valid_sms_code(normalized_code):
            return AuthResult(
                is_success=False,
                user_message="Похоже, SMS-код введён неверно. Отправьте только цифры из сообщения HH.",
            )

        if telegram_user_id in self._submitted_codes_by_user_id:
            return AuthResult(
                is_success=False,
                user_message="Код уже отправлен в HH. Подождите результат проверки.",
            )

        process = self._processes_by_user_id.get(telegram_user_id)
        if (
            not process
            or process.poll() is not None
            or not process.stdin
            or process.stdin.closed
        ):
            self._cleanup_auth_process(telegram_user_id)
            return AuthResult(
                is_success=False,
                user_message=(
                    "Процесс входа уже завершился или не был запущен. "
                    "Отправьте номер телефона ещё раз."
                ),
                keep_waiting=False,
            )

        try:
            self._submitted_codes_by_user_id.add(telegram_user_id)
            process.stdin.write(f"{normalized_code}\n")
            process.stdin.flush()
            process.stdin.close()
            return_code = process.wait(timeout=self.AUTH_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            self._terminate_auth_process(telegram_user_id)
            return AuthResult(
                is_success=False,
                user_message=(
                    "Не удалось завершить авторизацию: hh-applicant-tool не ответил вовремя. "
                    "Отправьте номер телефона ещё раз."
                ),
                keep_waiting=False,
            )

        if return_code != 0 or not self._account_service.is_authorized(telegram_user_id):
            output = self._get_auth_output(telegram_user_id)
            self._cleanup_auth_process(telegram_user_id)
            return AuthResult(
                is_success=False,
                user_message=self._format_submit_failure(output),
                keep_waiting=False,
            )

        self._cleanup_auth_process(telegram_user_id)
        self.mark_authorized(telegram_user_id)
        return AuthResult(is_success=True, user_message="Авторизация подтверждена.")

    def is_authorized(self, telegram_user_id: int) -> bool:
        return telegram_user_id in self._authorized_user_ids

    def is_checking_code(self, telegram_user_id: int) -> bool:
        lock = self._locks_by_user_id.get(telegram_user_id)
        return bool(lock and lock.locked())

    def mark_authorized(self, telegram_user_id: int) -> None:
        self._cleanup_auth_process(telegram_user_id)
        self._authorized_user_ids.add(telegram_user_id)

    def forget_authorized(self, telegram_user_id: int) -> None:
        self._terminate_auth_process(telegram_user_id)
        self._authorized_user_ids.discard(telegram_user_id)

    def _start_auth_process(
        self,
        telegram_user_id: int,
        phone: str,
    ) -> subprocess.Popen[str]:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        scripts_dir = (Path(__file__).resolve().parents[1] / "scripts").resolve()
        command = [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--user",
            "docker",
            "-v",
            f"{scripts_dir.as_posix()}:/bot_scripts:ro",
            "hh_applicant_tool",
            "python",
            "/bot_scripts/telegram_authorize.py",
            "--config-dir",
            "/app/config",
            "--profile-id",
            profile_id,
            "--phone",
            phone,
            "--captcha-file",
            f"/app/config/{profile_id}/telegram_captcha.png",
        ]

        return subprocess.Popen(
            command,
            cwd=self._workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )

    def _cleanup_auth_process(self, telegram_user_id: int) -> None:
        self._pending_phones_by_user_id.pop(telegram_user_id, None)
        self._processes_by_user_id.pop(telegram_user_id, None)
        self._output_threads_by_user_id.pop(telegram_user_id, None)
        self._outputs_by_user_id.pop(telegram_user_id, None)
        self._submitted_codes_by_user_id.discard(telegram_user_id)
        self._submitted_captchas_by_user_id.discard(telegram_user_id)

    def _terminate_auth_process(self, telegram_user_id: int) -> None:
        process = self._processes_by_user_id.pop(telegram_user_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        self._pending_phones_by_user_id.pop(telegram_user_id, None)
        self._output_threads_by_user_id.pop(telegram_user_id, None)
        self._outputs_by_user_id.pop(telegram_user_id, None)
        self._submitted_codes_by_user_id.discard(telegram_user_id)
        self._submitted_captchas_by_user_id.discard(telegram_user_id)

    def _get_user_lock(self, telegram_user_id: int) -> threading.Lock:
        lock = self._locks_by_user_id.get(telegram_user_id)
        if lock is None:
            lock = threading.Lock()
            self._locks_by_user_id[telegram_user_id] = lock
        return lock

    def _start_output_reader(
        self,
        telegram_user_id: int,
        process: subprocess.Popen[str],
    ) -> None:
        output: deque[str] = deque(maxlen=80)
        self._outputs_by_user_id[telegram_user_id] = output

        def _reader() -> None:
            if not process.stdout:
                return
            for line in process.stdout:
                output.append(line)

        thread = threading.Thread(target=_reader, daemon=True)
        self._output_threads_by_user_id[telegram_user_id] = thread
        thread.start()

    def _get_auth_output(self, telegram_user_id: int) -> str:
        return "".join(self._outputs_by_user_id.get(telegram_user_id, ())).lower()

    def _wait_for_auth_prompt(
        self,
        telegram_user_id: int,
        process: subprocess.Popen[str],
        *,
        ignore_captcha: bool = False,
    ) -> str:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return "failed"

            output = self._get_auth_output(telegram_user_id)
            if not ignore_captcha and self._get_captcha_path(telegram_user_id).exists():
                return "captcha"
            if not ignore_captcha and "captcha_required" in output:
                return "captcha"
            if "sms_sent" in output:
                return "sms"
            if "auth_error" in output:
                return "failed"

            time.sleep(0.5)

        return "pending" if process.poll() is None else "failed"

    def _get_captcha_path(self, telegram_user_id: int) -> Path:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        return self._workdir / "config" / profile_id / "telegram_captcha.png"

    @staticmethod
    def _format_start_failure(output: str) -> str:
        if "капч" in output or "captcha" in output:
            return (
                "HH попросил капчу до отправки SMS. Сейчас бот не умеет показать "
                "и принять капчу в Telegram, поэтому код не приходит. Попробуйте "
                "позже или пройдите вход вручную в hh-applicant-tool."
            )
        if "playwright" in output or "browser" in output:
            return (
                "hh-applicant-tool не смог запустить браузер для входа. "
                "Проверьте Playwright/контейнер и попробуйте ещё раз."
            )
        return (
            "hh-applicant-tool не смог начать вход. Попробуйте ещё раз позже."
        )

    @staticmethod
    def _format_submit_failure(output: str) -> str:
        if "капч" in output or "captcha" in output:
            return (
                "HH запросил капчу во время входа. Сейчас бот не умеет пройти "
                "капчу в Telegram. Отправьте номер ещё раз позже или войдите "
                "вручную в hh-applicant-tool."
            )
        return (
            "HH не подтвердил вход. Возможно, код неверный или истёк. "
            "Отправьте номер телефона ещё раз."
        )

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        stripped = phone.strip()
        if stripped.startswith("+"):
            return "+" + re.sub(r"\D", "", stripped)
        return re.sub(r"\D", "", stripped)

    @staticmethod
    def _is_valid_phone(phone: str) -> bool:
        return bool(re.fullmatch(r"\+?\d{10,15}", phone))

    @staticmethod
    def _is_valid_sms_code(sms_code: str) -> bool:
        return bool(re.fullmatch(r"\d{4,8}", sms_code))
