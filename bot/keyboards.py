from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


START_BUTTON_TEXT = "▶️ Запустить"
STOP_BUTTON_TEXT = "⏹ Остановить"
COVER_LETTER_BUTTON_TEXT = "✉️ Сопроводительное письмо"
STATISTICS_BUTTON_TEXT = "📊 Статистика"
LOGOUT_BUTTON_TEXT = "🔴 Выйти из аккаунта"
LOGOUT_CONFIRM_YES_TEXT = "Да"
LOGOUT_CONFIRM_NO_TEXT = "Нет"
COVER_LETTER_EDIT_BUTTON_TEXT = "✏️ Изменить"
BACK_BUTTON_TEXT = "↩️ Назад"
START_AUTOMATION_CALLBACK_DATA = "automation:start"
STOP_AUTOMATION_CALLBACK_DATA = "automation:stop"
STATISTICS_CALLBACK_DATA = "statistics:show"
COVER_LETTER_CALLBACK_DATA = "cover_letter:menu"
COVER_LETTER_EDIT_CALLBACK_DATA = "cover_letter:edit"
BACK_TO_ACCOUNT_CALLBACK_DATA = "account:back"
LOGOUT_CALLBACK_DATA = "account:logout"
LOGOUT_CONFIRM_YES_CALLBACK_DATA = "account:logout:yes"
LOGOUT_CONFIRM_NO_CALLBACK_DATA = "account:logout:no"


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
                    text=COVER_LETTER_BUTTON_TEXT,
                    callback_data=COVER_LETTER_CALLBACK_DATA,
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
