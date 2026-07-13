from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


START_BUTTON_TEXT = "▶️ Запустить"
STOP_BUTTON_TEXT = "⏹ Остановить"
COVER_LETTER_BUTTON_TEXT = "✉️ Сопроводительное письмо"
SETTINGS_BUTTON_TEXT = "⚙️ Настройки"
STATISTICS_BUTTON_TEXT = "📊 Статистика"
AI_TEST_BUTTON_TEXT = "🧠 AI тест"
AI_DRY_RUN_BUTTON_TEXT = "🧪 AI-анализ"
LOGOUT_BUTTON_TEXT = "🔴 Выйти из аккаунта"
LOGOUT_CONFIRM_YES_TEXT = "Да"
LOGOUT_CONFIRM_NO_TEXT = "Нет"
COVER_LETTER_EDIT_BUTTON_TEXT = "✏️ Изменить"
BACK_BUTTON_TEXT = "↩️ Назад"
AI_DRY_RUN_REPEAT_BUTTON_TEXT = "🔁 Запустить повторно"
AI_DRY_RUN_BACK_BUTTON_TEXT = "👤 Личный кабинет"
AI_DRY_RUN_10_BUTTON_TEXT = "10 вакансий"
AI_DRY_RUN_30_BUTTON_TEXT = "30 вакансий"
AI_DRY_RUN_50_BUTTON_TEXT = "50 вакансий"
AI_DRY_RUN_ALL_TARGET_BUTTON_TEXT = "Все доступные"
AI_DRY_RUN_APPROVED_BUTTON_TEXT = "✅ Подходящие"
AI_DRY_RUN_REJECTED_BUTTON_TEXT = "🧠 Отклонённые"
AI_DRY_RUN_ALL_BUTTON_TEXT = "📋 Все проверенные"
AI_DRY_RUN_LIGHT_BUTTON_TEXT = "⚡ Light"
AI_DRY_RUN_HEAVY_BUTTON_TEXT = "🧠 Heavy"
AI_DRY_RUN_CLEAR_SKIPPED_BUTTON_TEXT = "🧹 Очистить AI-отклонённые"
AI_DRY_RUN_CLEAR_CONFIRM_YES_TEXT = "Да, очистить"
AI_DRY_RUN_CLEAR_CONFIRM_NO_TEXT = "Отмена"
AUTOMATION_PLAIN_BUTTON_TEXT = "🚀 Обычный авто-отклик"
AUTOMATION_AI_BUTTON_TEXT = "🧠 Авто-отклик с AI"
AUTOMATION_CONFIRM_BUTTON_TEXT = "✅ Запустить"
AUTOMATION_CHANGE_QUERY_BUTTON_TEXT = "✏️ Изменить запрос"
AUTOMATION_NEW_QUERY_BUTTON_TEXT = "➕ Новый запрос"
RESUME_BUMP_BUTTON_PREFIX = "🔁 Поднятие резюме:"
RESUME_BUMP_OFF_BUTTON_TEXT = "Выключить"
RESUME_BUMP_4H_BUTTON_TEXT = "Каждые 4 часа"
RESUME_BUMP_5H_BUTTON_TEXT = "Каждые 5 часов"
START_AUTOMATION_CALLBACK_DATA = "automation:start"
START_AUTOMATION_PLAIN_CALLBACK_DATA = "automation:start:plain"
START_AUTOMATION_AI_CALLBACK_DATA = "automation:start:ai"
STOP_AUTOMATION_CALLBACK_DATA = "automation:stop"
STATISTICS_CALLBACK_DATA = "statistics:show"
AI_TEST_CALLBACK_DATA = "ai:test"
AI_DRY_RUN_CALLBACK_DATA = "ai:dry_run"
AI_DRY_RUN_APPROVED_CALLBACK_DATA = "ai:dry_run:approved"
AI_DRY_RUN_REJECTED_CALLBACK_DATA = "ai:dry_run:rejected"
AI_DRY_RUN_ALL_CALLBACK_DATA = "ai:dry_run:all"
AI_DRY_RUN_LIGHT_CALLBACK_DATA = "ai:dry_run:mode:light"
AI_DRY_RUN_HEAVY_CALLBACK_DATA = "ai:dry_run:mode:heavy"
AI_DRY_RUN_CLEAR_SKIPPED_CALLBACK_DATA = "ai:dry_run:clear_skipped"
AI_DRY_RUN_CLEAR_CONFIRM_YES_CALLBACK_DATA = "ai:dry_run:clear_skipped:yes"
AI_DRY_RUN_CLEAR_CONFIRM_NO_CALLBACK_DATA = "ai:dry_run:clear_skipped:no"
SETTINGS_CALLBACK_DATA = "settings:menu"
RESUME_BUMP_CALLBACK_DATA = "settings:resume_bump"
RESUME_BUMP_OFF_CALLBACK_DATA = "settings:resume_bump:off"
RESUME_BUMP_4H_CALLBACK_DATA = "settings:resume_bump:4"
RESUME_BUMP_5H_CALLBACK_DATA = "settings:resume_bump:5"
COVER_LETTER_CALLBACK_DATA = "cover_letter:menu"
COVER_LETTER_EDIT_CALLBACK_DATA = "cover_letter:edit"
BACK_TO_ACCOUNT_CALLBACK_DATA = "account:back"
LOGOUT_CALLBACK_DATA = "account:logout"
LOGOUT_CONFIRM_YES_CALLBACK_DATA = "account:logout:yes"
LOGOUT_CONFIRM_NO_CALLBACK_DATA = "account:logout:no"
AUTOMATION_CONFIRM_CALLBACK_DATA = "automation:confirm"
AUTOMATION_CHANGE_QUERY_CALLBACK_DATA = "automation:change_query"
AUTOMATION_NEW_QUERY_CALLBACK_DATA = "automation:query:new"
AUTOMATION_QUERY_CALLBACK_PREFIX = "automation:query"


def account_keyboard(is_running: bool) -> InlineKeyboardMarkup:
    if is_running:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=STOP_BUTTON_TEXT,
                        callback_data=STOP_AUTOMATION_CALLBACK_DATA,
                    )
                ]
            ],
        )

    action_button = InlineKeyboardButton(
        text=START_BUTTON_TEXT,
        callback_data=START_AUTOMATION_CALLBACK_DATA,
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [action_button],
            [
                InlineKeyboardButton(
                    text=STATISTICS_BUTTON_TEXT,
                    callback_data=STATISTICS_CALLBACK_DATA,
                ),
                InlineKeyboardButton(
                    text=AI_TEST_BUTTON_TEXT,
                    callback_data=AI_TEST_CALLBACK_DATA,
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_CALLBACK_DATA,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=SETTINGS_BUTTON_TEXT,
                    callback_data=SETTINGS_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=LOGOUT_BUTTON_TEXT,
                    callback_data=LOGOUT_CALLBACK_DATA,
                )
            ],
        ],
    )


def cover_letter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=COVER_LETTER_EDIT_BUTTON_TEXT,
                    callback_data=COVER_LETTER_EDIT_CALLBACK_DATA,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ],
        ]
    )


def settings_keyboard(resume_bump_label: str = "выкл") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{RESUME_BUMP_BUTTON_PREFIX} {resume_bump_label}",
                    callback_data=RESUME_BUMP_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=COVER_LETTER_BUTTON_TEXT,
                    callback_data=COVER_LETTER_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_CLEAR_SKIPPED_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_CLEAR_SKIPPED_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ],
        ]
    )


def resume_bump_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=RESUME_BUMP_OFF_BUTTON_TEXT,
                    callback_data=RESUME_BUMP_OFF_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=RESUME_BUMP_4H_BUTTON_TEXT,
                    callback_data=RESUME_BUMP_4H_CALLBACK_DATA,
                ),
                InlineKeyboardButton(
                    text=RESUME_BUMP_5H_BUTTON_TEXT,
                    callback_data=RESUME_BUMP_5H_CALLBACK_DATA,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=SETTINGS_CALLBACK_DATA,
                )
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ]
        ]
    )


def automation_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AUTOMATION_PLAIN_BUTTON_TEXT,
                    callback_data=START_AUTOMATION_PLAIN_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=AUTOMATION_AI_BUTTON_TEXT,
                    callback_data=START_AUTOMATION_AI_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ],
        ]
    )


def automation_ai_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_LIGHT_BUTTON_TEXT,
                    callback_data="automation:start:ai:light",
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_HEAVY_BUTTON_TEXT,
                    callback_data="automation:start:ai:heavy",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=START_AUTOMATION_CALLBACK_DATA,
                )
            ],
        ]
    )


def automation_limit_keyboard(mode: str, ai_filter: str | None = None) -> InlineKeyboardMarkup:
    callback_prefix = f"automation:start:{mode}"
    if ai_filter:
        callback_prefix = f"{callback_prefix}:{ai_filter}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_10_BUTTON_TEXT,
                    callback_data=f"{callback_prefix}:10",
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_30_BUTTON_TEXT,
                    callback_data=f"{callback_prefix}:30",
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_50_BUTTON_TEXT,
                    callback_data=f"{callback_prefix}:50",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_ALL_TARGET_BUTTON_TEXT,
                    callback_data=f"{callback_prefix}:all",
                )
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=(
                        START_AUTOMATION_AI_CALLBACK_DATA
                        if mode == "ai"
                        else START_AUTOMATION_CALLBACK_DATA
                    ),
                )
            ],
        ]
    )


def automation_search_query_keyboard(history: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, query in enumerate(history[:5]):
        rows.append(
            [
                InlineKeyboardButton(
                    text=query[:60],
                    callback_data=f"{AUTOMATION_QUERY_CALLBACK_PREFIX}:{index}",
                )
            ]
        )

    if rows:
        rows.append(
            [
                InlineKeyboardButton(
                    text=AUTOMATION_NEW_QUERY_BUTTON_TEXT,
                    callback_data=AUTOMATION_NEW_QUERY_CALLBACK_DATA,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=BACK_BUTTON_TEXT,
                callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def automation_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_REPEAT_BUTTON_TEXT,
                    callback_data=START_AUTOMATION_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ],
        ]
    )


def automation_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AUTOMATION_CONFIRM_BUTTON_TEXT,
                    callback_data=AUTOMATION_CONFIRM_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=AUTOMATION_CHANGE_QUERY_BUTTON_TEXT,
                    callback_data=AUTOMATION_CHANGE_QUERY_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=START_AUTOMATION_CALLBACK_DATA,
                )
            ],
        ]
    )


def ai_dry_run_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_LIGHT_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_LIGHT_CALLBACK_DATA,
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_HEAVY_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_HEAVY_CALLBACK_DATA,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ],
        ]
    )


def ai_dry_run_limit_keyboard(ai_filter: str = "light") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_10_BUTTON_TEXT,
                    callback_data=f"ai:dry_run:{ai_filter}:10",
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_30_BUTTON_TEXT,
                    callback_data=f"ai:dry_run:{ai_filter}:30",
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_50_BUTTON_TEXT,
                    callback_data=f"ai:dry_run:{ai_filter}:50",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_ALL_TARGET_BUTTON_TEXT,
                    callback_data=f"ai:dry_run:{ai_filter}:all",
                )
            ],
            [
                InlineKeyboardButton(
                    text=BACK_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_CALLBACK_DATA,
                )
            ],
        ]
    )


def ai_dry_run_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_APPROVED_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_APPROVED_CALLBACK_DATA,
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_REJECTED_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_REJECTED_CALLBACK_DATA,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_ALL_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_ALL_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_REPEAT_BUTTON_TEXT,
                    callback_data=AI_DRY_RUN_CALLBACK_DATA,
                )
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ],
        ]
    )


def ai_dry_run_clear_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_CLEAR_CONFIRM_YES_TEXT,
                    callback_data=AI_DRY_RUN_CLEAR_CONFIRM_YES_CALLBACK_DATA,
                ),
                InlineKeyboardButton(
                    text=AI_DRY_RUN_CLEAR_CONFIRM_NO_TEXT,
                    callback_data=AI_DRY_RUN_CLEAR_CONFIRM_NO_CALLBACK_DATA,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=AI_DRY_RUN_BACK_BUTTON_TEXT,
                    callback_data=BACK_TO_ACCOUNT_CALLBACK_DATA,
                )
            ],
        ]
    )


def logout_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=LOGOUT_CONFIRM_YES_TEXT,
                    callback_data=LOGOUT_CONFIRM_YES_CALLBACK_DATA,
                ),
                InlineKeyboardButton(
                    text=LOGOUT_CONFIRM_NO_TEXT,
                    callback_data=LOGOUT_CONFIRM_NO_CALLBACK_DATA,
                ),
            ]
        ]
    )
