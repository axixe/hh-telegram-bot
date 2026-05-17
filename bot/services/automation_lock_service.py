from threading import Lock


class AutomationLockService:
    def __init__(self) -> None:
        self._active_locks: set[str] = set()
        self._lock = Lock()

    def acquire_automation_lock(self, telegram_user_id: int) -> bool:
        key = self._get_automation_key(telegram_user_id)
        with self._lock:
            if key in self._active_locks:
                return False
            self._active_locks.add(key)
            return True

    def release_automation_lock(self, telegram_user_id: int) -> None:
        key = self._get_automation_key(telegram_user_id)
        with self._lock:
            self._active_locks.discard(key)

    def _get_automation_key(self, telegram_user_id: int) -> str:
        return f"automation_lock:{telegram_user_id}"
