import re


class ProfileService:
    @staticmethod
    def get_profile_id(telegram_user_id: int) -> str:
        return f"tg_{telegram_user_id}"

    @staticmethod
    def get_container_name(telegram_user_id: int) -> str:
        profile_id = ProfileService.get_profile_id(telegram_user_id)
        safe_profile_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", profile_id)
        return f"hh_applicant_tool_{safe_profile_id}"

    @staticmethod
    def get_resume_bump_container_name(telegram_user_id: int) -> str:
        return f"{ProfileService.get_container_name(telegram_user_id)}_resume_bump"
