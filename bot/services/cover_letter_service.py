from pathlib import Path

from bot.services.profile_service import ProfileService


class CoverLetterServiceError(RuntimeError):
    pass


class CoverLetterService:
    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    def get_letter(self, telegram_user_id: int) -> str | None:
        path = self.get_letter_path(telegram_user_id)
        if not path.exists():
            return None

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CoverLetterServiceError("Failed to read cover letter") from exc

        return text or None

    def save_letter(self, telegram_user_id: int, text: str) -> None:
        letter_text = text.strip()
        if not letter_text:
            raise CoverLetterServiceError("Cover letter is empty")

        path = self.get_letter_path(telegram_user_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{letter_text}\n", encoding="utf-8")
        except OSError as exc:
            raise CoverLetterServiceError("Failed to save cover letter") from exc

    def get_letter_path(self, telegram_user_id: int) -> Path:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        return self._workdir / "config" / profile_id / "letter.txt"
