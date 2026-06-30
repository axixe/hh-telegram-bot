import tempfile
import unittest
from pathlib import Path

from bot.services.account_cache_service import (
    AccountCacheService,
    CachedAccount,
)


class AccountCacheServiceTest(unittest.TestCase):
    def test_clear_removes_cached_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AccountCacheService(Path(tmp))
            service.save(123, CachedAccount(full_name="Old", resumes_count=1, resumes=()))

            service.clear(123)

            self.assertIsNone(service.get(123))

    def test_clear_missing_cache_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AccountCacheService(Path(tmp))

            service.clear(123)

            self.assertIsNone(service.get(123))


if __name__ == "__main__":
    unittest.main()
