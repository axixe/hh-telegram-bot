import unittest

from bot.keyboards import (
    AI_DRY_RUN_BUTTON_TEXT,
    AI_DRY_RUN_10_BUTTON_TEXT,
    AI_DRY_RUN_30_BUTTON_TEXT,
    AI_DRY_RUN_50_BUTTON_TEXT,
    AI_DRY_RUN_ALL_TARGET_BUTTON_TEXT,
    AI_DRY_RUN_ALL_BUTTON_TEXT,
    AI_DRY_RUN_APPROVED_BUTTON_TEXT,
    AI_DRY_RUN_CLEAR_SKIPPED_BUTTON_TEXT,
    AI_DRY_RUN_HEAVY_BUTTON_TEXT,
    AI_DRY_RUN_LIGHT_BUTTON_TEXT,
    AI_DRY_RUN_REPEAT_BUTTON_TEXT,
    AI_DRY_RUN_BACK_BUTTON_TEXT,
    AI_DRY_RUN_REJECTED_BUTTON_TEXT,
    AI_TEST_BUTTON_TEXT,
    AUTOMATION_CHANGE_QUERY_BUTTON_TEXT,
    AUTOMATION_CONFIRM_BUTTON_TEXT,
    AUTOMATION_RESUME_TITLE_QUERY_BUTTON_TEXT,
    AUTOMATION_AI_BUTTON_TEXT,
    AUTOMATION_PLAIN_BUTTON_TEXT,
    COVER_LETTER_BUTTON_TEXT,
    RESUME_BUMP_4H_BUTTON_TEXT,
    RESUME_BUMP_5H_BUTTON_TEXT,
    RESUME_BUMP_BUTTON_PREFIX,
    RESUME_BUMP_OFF_BUTTON_TEXT,
    SETTINGS_BUTTON_TEXT,
    STOP_BUTTON_TEXT,
    ai_dry_run_limit_keyboard,
    ai_dry_run_mode_keyboard,
    ai_dry_run_result_keyboard,
    account_keyboard,
    automation_ai_mode_keyboard,
    automation_limit_keyboard,
    automation_preview_keyboard,
    automation_result_keyboard,
    automation_search_query_keyboard,
    automation_type_keyboard,
    resume_bump_settings_keyboard,
    settings_keyboard,
)


def keyboard_texts(is_running: bool) -> list[str]:
    keyboard = account_keyboard(is_running)
    return [
        button.text
        for row in keyboard.inline_keyboard
        for button in row
    ]


class KeyboardTest(unittest.TestCase):
    def test_ai_test_button_is_shown_when_automation_is_stopped(self) -> None:
        texts = keyboard_texts(is_running=False)

        self.assertIn(AI_TEST_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_BUTTON_TEXT, texts)
        self.assertIn(SETTINGS_BUTTON_TEXT, texts)
        self.assertNotIn(COVER_LETTER_BUTTON_TEXT, texts)

    def test_ai_test_button_is_hidden_when_automation_is_running(self) -> None:
        texts = keyboard_texts(is_running=True)

        self.assertEqual(texts, [STOP_BUTTON_TEXT])
        self.assertNotIn(AI_TEST_BUTTON_TEXT, texts)
        self.assertNotIn(AI_DRY_RUN_BUTTON_TEXT, texts)

    def test_ai_dry_run_result_keyboard_has_repeat_and_back(self) -> None:
        texts = [
            button.text
            for row in ai_dry_run_result_keyboard().inline_keyboard
            for button in row
        ]

        self.assertEqual(
            texts,
            [
                AI_DRY_RUN_APPROVED_BUTTON_TEXT,
                AI_DRY_RUN_REJECTED_BUTTON_TEXT,
                AI_DRY_RUN_ALL_BUTTON_TEXT,
                AI_DRY_RUN_REPEAT_BUTTON_TEXT,
                AI_DRY_RUN_BACK_BUTTON_TEXT,
            ],
        )

    def test_ai_dry_run_limit_keyboard_has_supported_targets(self) -> None:
        texts = [
            button.text
            for row in ai_dry_run_limit_keyboard().inline_keyboard
            for button in row
        ]

        self.assertIn(AI_DRY_RUN_10_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_30_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_50_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_ALL_TARGET_BUTTON_TEXT, texts)

    def test_ai_dry_run_mode_keyboard_has_light_and_heavy(self) -> None:
        texts = [
            button.text
            for row in ai_dry_run_mode_keyboard().inline_keyboard
            for button in row
        ]

        self.assertIn(AI_DRY_RUN_LIGHT_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_HEAVY_BUTTON_TEXT, texts)

    def test_automation_type_keyboard_has_plain_and_ai_modes(self) -> None:
        texts = [
            button.text
            for row in automation_type_keyboard().inline_keyboard
            for button in row
        ]

        self.assertIn(AUTOMATION_PLAIN_BUTTON_TEXT, texts)
        self.assertIn(AUTOMATION_AI_BUTTON_TEXT, texts)

    def test_automation_ai_mode_keyboard_has_light_and_heavy(self) -> None:
        texts = [
            button.text
            for row in automation_ai_mode_keyboard().inline_keyboard
            for button in row
        ]

        self.assertIn(AI_DRY_RUN_LIGHT_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_HEAVY_BUTTON_TEXT, texts)

    def test_automation_limit_keyboard_has_supported_targets(self) -> None:
        texts = [
            button.text
            for row in automation_limit_keyboard("ai", "heavy").inline_keyboard
            for button in row
        ]

        self.assertIn(AI_DRY_RUN_10_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_30_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_50_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_ALL_TARGET_BUTTON_TEXT, texts)

    def test_automation_result_keyboard_has_repeat_and_account(self) -> None:
        texts = [
            button.text
            for row in automation_result_keyboard().inline_keyboard
            for button in row
        ]

        self.assertEqual(
            texts,
            [
                AI_DRY_RUN_REPEAT_BUTTON_TEXT,
                AI_DRY_RUN_BACK_BUTTON_TEXT,
            ],
        )

    def test_automation_preview_keyboard_has_confirm_change_and_back(self) -> None:
        texts = [
            button.text
            for row in automation_preview_keyboard().inline_keyboard
            for button in row
        ]

        self.assertEqual(
            texts,
            [
                AUTOMATION_CONFIRM_BUTTON_TEXT,
                AUTOMATION_CHANGE_QUERY_BUTTON_TEXT,
                "↩️ Назад",
            ],
        )

    def test_automation_search_query_keyboard_has_resume_title_history_and_back(self) -> None:
        keyboard = automation_search_query_keyboard(["Frontend", "Python backend"])
        texts = [
            button.text
            for row in keyboard.inline_keyboard
            for button in row
        ]
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertEqual(
            texts,
            [
                AUTOMATION_RESUME_TITLE_QUERY_BUTTON_TEXT,
                "Frontend",
                "Python backend",
                "↩️ Назад",
            ],
        )
        self.assertIn("automation:query:resume_title", callbacks)
        self.assertIn("automation:query:0", callbacks)
        self.assertIn("automation:query:1", callbacks)

    def test_settings_keyboard_has_cover_letter_and_ai_clear(self) -> None:
        texts = [
            button.text
            for row in settings_keyboard("4 часа").inline_keyboard
            for button in row
        ]

        self.assertIn(f"{RESUME_BUMP_BUTTON_PREFIX} 4 часа", texts)
        self.assertIn(COVER_LETTER_BUTTON_TEXT, texts)
        self.assertIn(AI_DRY_RUN_CLEAR_SKIPPED_BUTTON_TEXT, texts)

    def test_resume_bump_settings_keyboard_has_supported_modes(self) -> None:
        texts = [
            button.text
            for row in resume_bump_settings_keyboard().inline_keyboard
            for button in row
        ]

        self.assertIn(RESUME_BUMP_OFF_BUTTON_TEXT, texts)
        self.assertIn(RESUME_BUMP_4H_BUTTON_TEXT, texts)
        self.assertIn(RESUME_BUMP_5H_BUTTON_TEXT, texts)


if __name__ == "__main__":
    unittest.main()
