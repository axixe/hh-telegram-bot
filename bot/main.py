import asyncio
import html
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import Settings, load_settings
from bot.keyboards import (
    BACK_BUTTON_TEXT,
    BACK_TO_ACCOUNT_CALLBACK_DATA,
    COVER_LETTER_CALLBACK_DATA,
    COVER_LETTER_BUTTON_TEXT,
    COVER_LETTER_EDIT_CALLBACK_DATA,
    COVER_LETTER_EDIT_BUTTON_TEXT,
    LOGOUT_CALLBACK_DATA,
    LOGOUT_CONFIRM_NO_CALLBACK_DATA,
    LOGOUT_CONFIRM_YES_CALLBACK_DATA,
    LOGOUT_BUTTON_TEXT,
    STATISTICS_CALLBACK_DATA,
    START_AUTOMATION_CALLBACK_DATA,
    START_BUTTON_TEXT,
    STOP_AUTOMATION_CALLBACK_DATA,
    STOP_BUTTON_TEXT,
    account_keyboard,
    back_keyboard,
    cover_letter_keyboard,
    logout_confirm_keyboard,
)
from bot.services.account_service import (
    AccountService,
    AccountServiceError,
    AccountSummary,
)
from bot.services.account_cache_service import (
    AccountCacheService,
    CachedAccount,
)
from bot.services.app_status_service import AppStatus, AppStatusService, AutomationStatus
from bot.services.auth_service import AuthService
from bot.services.automation_lock_service import AutomationLockService
from bot.services.automation_stats_service import (
    AutomationStatsService,
    AutomationStatsServiceError,
)
from bot.services.command_runner import CommandRunner, CommandRunnerError
from bot.services.cover_letter_service import (
    CoverLetterService,
    CoverLetterServiceError,
)
from bot.states import AuthStates, CoverLetterStates


router = Router()
_status_tasks_by_user_id: dict[int, asyncio.Task[None]] = {}
_tracked_message_ids_by_user_id: dict[int, list[int]] = {}
_cover_letter_screen_message_ids_by_user_id: dict[int, int] = {}


def _track_message(message: Message | None, telegram_user_id: int | None) -> None:
    if not message or telegram_user_id is None:
        return

    message_ids = _tracked_message_ids_by_user_id.setdefault(telegram_user_id, [])
    message_ids.append(message.message_id)
    del message_ids[:-80]


async def _answer_tracked(
    source: Message,
    telegram_user_id: int,
    text: str,
    **kwargs,
) -> Message:
    sent_message = await source.answer(text, **kwargs)
    _track_message(sent_message, telegram_user_id)
    return sent_message


async def _cleanup_tracked_messages(
    bot: Bot,
    chat_id: int,
    telegram_user_id: int,
    *,
    keep_message_id: int | None = None,
) -> None:
    message_ids = _tracked_message_ids_by_user_id.pop(telegram_user_id, [])
    for message_id in message_ids:
        if message_id == keep_message_id:
            continue
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id, message_id)


def _is_allowed(message: Message, settings: Settings) -> bool:
    return bool(
        message.from_user
        and message.from_user.id in settings.telegram_allowed_user_ids
    )


async def _deny_access(message: Message) -> None:
    await message.answer("У вас нет доступа к этому боту.")


async def _ensure_authorized(message: Message, auth_service: AuthService) -> bool:
    if message.from_user and auth_service.is_authorized(message.from_user.id):
        return True

    await message.answer(
        "🔐 <b>Нужна авторизация</b>\n\n"
        "Отправьте номер телефона, чтобы войти в HH.",
        parse_mode="HTML",
    )
    return False


async def _is_authorized_user(
    telegram_user_id: int,
    auth_service: AuthService,
    account_service: AccountService,
) -> bool:
    if auth_service.is_authorized(telegram_user_id):
        return True

    is_authorized = await asyncio.to_thread(
        account_service.is_authorized,
        telegram_user_id,
    )
    if is_authorized:
        auth_service.mark_authorized(telegram_user_id)
    return is_authorized


def _format_cover_letter_menu(letter: str | None) -> str:
    lines = ["✉️ <b>Сопроводительное письмо</b>"]
    if letter:
        lines.extend(["", html.escape(letter)])
    else:
        lines.extend(["", "Письмо ещё не задано."])

    return "\n".join(lines)


async def _show_cover_letter_menu(
    message: Message,
    cover_letter_service: CoverLetterService,
) -> None:
    if not message.from_user:
        return
    await _delete_cover_letter_screen(message.bot, message.chat.id, message.from_user.id)

    try:
        letter = cover_letter_service.get_letter(message.from_user.id)
    except CoverLetterServiceError:
        letter = None

    sent_message = await _answer_tracked(
        message,
        message.from_user.id,
        _format_cover_letter_menu(letter),
        reply_markup=cover_letter_keyboard(),
        parse_mode="HTML",
    )
    _cover_letter_screen_message_ids_by_user_id[message.from_user.id] = sent_message.message_id


async def _delete_cover_letter_screen(
    bot: Bot,
    chat_id: int,
    telegram_user_id: int,
) -> None:
    message_id = _cover_letter_screen_message_ids_by_user_id.pop(
        telegram_user_id,
        None,
    )
    if message_id is None:
        return
    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id, message_id)


def _format_account_panel(account: CachedAccount) -> str:
    lines = [
        "👤 <b>Личный кабинет</b>",
        "",
        "📌 <b>Аккаунт</b>",
        f"• Имя: <b>{html.escape(account.full_name or 'HH')}</b>",
        f"• Резюме: <b>{account.resumes_count}</b>",
    ]

    if account.resumes:
        lines.extend(["", "🧾 <b>Резюме</b>"])
        for resume in account.resumes[:5]:
            lines.append(
                "• "
                f"<b>{html.escape(resume.title)}</b> "
                f"(<i>{html.escape(resume.status)}</i>)\n"
                f"  👁 просмотры: <b>{resume.total_views}</b>, "
                f"новые: <b>{resume.new_views}</b>"
            )

    return "\n".join(lines)


def _format_automation_state(status: AppStatus) -> str:
    if status.status == AutomationStatus.STARTING:
        return "🟡 <b>Авто-отклик запускается</b>\n\nПодождите немного."
    if status.status == AutomationStatus.STOPPING:
        return "🟡 <b>Авто-отклик останавливается</b>\n\nПодождите немного."
    if status.status == AutomationStatus.FAILED:
        return (
            "⚠️ <b>Последний запуск завершился с ошибкой</b>\n\n"
            "Можно попробовать запустить сценарий ещё раз."
        )
    if status.status == AutomationStatus.STOPPED:
        return "⚪ <b>Авто-отклик остановлен</b>"
    return "🟢 <b>Авто-отклик бот запущен</b>\n\nСтатистика пока недоступна."


async def _send_account_panel(
    message: Message,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
) -> None:
    if not message.from_user:
        return
    await _send_account_panel_for_user(
        message,
        message.from_user.id,
        account_service,
        account_cache_service,
        status_service,
    )


async def _send_account_panel_for_user(
    message: Message,
    telegram_user_id: int,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
) -> None:
    cached_account = account_cache_service.get(telegram_user_id)
    if cached_account:
        status = status_service.get_status(telegram_user_id)
        await message.answer(
            _format_account_panel(cached_account),
            reply_markup=account_keyboard(status.shows_stop_button),
            parse_mode="HTML",
        )
        return

    try:
        summary = await asyncio.to_thread(
            account_service.get_summary,
            telegram_user_id,
        )
    except AccountServiceError:
        await _answer_tracked(
            message,
            telegram_user_id,
            "⚠️ <b>Не получилось обновить личный кабинет</b>\n\n"
            "Попробуйте ещё раз чуть позже.",
            parse_mode="HTML",
        )
        return

    cached_account = account_cache_service.save_summary(telegram_user_id, summary)
    status = status_service.get_status(telegram_user_id)
    await _answer_tracked(
        message,
        telegram_user_id,
        _format_account_panel(cached_account),
        reply_markup=account_keyboard(status.shows_stop_button),
        parse_mode="HTML",
    )


async def _delete_message(message: Message | None) -> None:
    if not message:
        return
    with suppress(TelegramBadRequest):
        await message.delete()


async def _delete_callback_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    if isinstance(message, Message):
        await _delete_message(message)
        return message
    return None


async def _safe_edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    show_stop_button: bool,
) -> None:
    reply_markup = account_keyboard(is_running=True) if show_stop_button else None
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def _update_automation_status_message(
    *,
    bot: Bot,
    chat_id: int,
    message_id: int,
    telegram_user_id: int,
    status_service: AppStatusService,
    stats_service: AutomationStatsService,
) -> None:
    last_text = ""
    while status_service.get_status(telegram_user_id).is_running:
        try:
            stats = await asyncio.to_thread(stats_service.get_stats, telegram_user_id)
            text = stats_service.format_status(stats)
        except AutomationStatsServiceError:
            text = "🟢 <b>Авто-отклик бот запущен</b>\n\nСтатистика пока недоступна."

        if text != last_text:
            await _safe_edit_message(
                bot,
                chat_id,
                message_id,
                text,
                show_stop_button=True,
            )
            last_text = text

        await asyncio.sleep(10)

    if last_text:
        await _safe_edit_message(
            bot,
            chat_id,
            message_id,
            last_text.replace("запущен", "остановлен", 1).replace("🟢", "⚪", 1),
            show_stop_button=False,
        )


def _start_status_updates(
    *,
    bot: Bot,
    chat_id: int,
    message_id: int,
    telegram_user_id: int,
    status_service: AppStatusService,
    stats_service: AutomationStatsService,
) -> None:
    old_task = _status_tasks_by_user_id.pop(telegram_user_id, None)
    if old_task:
        old_task.cancel()

    task = asyncio.create_task(
        _update_automation_status_message(
            bot=bot,
            chat_id=chat_id,
            message_id=message_id,
            telegram_user_id=telegram_user_id,
            status_service=status_service,
            stats_service=stats_service,
        )
    )
    _status_tasks_by_user_id[telegram_user_id] = task
    task.add_done_callback(lambda _: _status_tasks_by_user_id.pop(telegram_user_id, None))


@router.message(CommandStart())
async def handle_start(
    message: Message,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if message.from_user:
        _track_message(message, message.from_user.id)
    await state.clear()
    if message.from_user:
        try:
            summary = account_service.get_summary(message.from_user.id)
        except AccountServiceError:
            summary = None

        if summary and summary.is_authorized:
            auth_service.mark_authorized(message.from_user.id)
            account_cache_service.save_summary(message.from_user.id, summary)
            await _send_account_panel(
                message,
                account_service,
                account_cache_service,
                status_service,
            )
            return

    await state.set_state(AuthStates.waiting_for_phone)
    if message.from_user:
        await _answer_tracked(
            message,
            message.from_user.id,
            "👋 <b>Привет!</b>\n\n"
            "Я помогу управлять hh-applicant-tool прямо из Telegram.\n\n"
            "🔐 <b>Авторизация HH</b>\n"
            "Отправьте номер телефона, и я начну вход.",
            parse_mode="HTML",
        )


@router.message(AuthStates.waiting_for_phone)
async def handle_phone(
    message: Message,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not message.from_user or not message.text:
        await message.answer("Отправьте номер телефона текстом.")
        return

    _track_message(message, message.from_user.id)
    await _answer_tracked(
        message,
        message.from_user.id,
        "📱 Номер принят. Запускаю вход в HH, это может занять немного времени.",
    )
    result = await asyncio.to_thread(
        auth_service.start_phone_authorization,
        message.from_user.id,
        message.text,
    )
    await _answer_tracked(message, message.from_user.id, result.user_message)

    if result.is_success and result.requires_captcha and result.captcha_path:
        sent_message = await message.answer_photo(
            FSInputFile(result.captcha_path),
            caption="Введите символы с картинки одним сообщением.",
        )
        _track_message(sent_message, message.from_user.id)
        await state.set_state(AuthStates.waiting_for_captcha)
    elif result.is_success:
        await state.set_state(AuthStates.waiting_for_sms_code)
    elif not result.keep_waiting:
        await state.clear()


@router.message(AuthStates.waiting_for_captcha)
async def handle_captcha(
    message: Message,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not message.from_user or not message.text:
        await message.answer("Отправьте текст с картинки сообщением.")
        return

    _track_message(message, message.from_user.id)
    await _answer_tracked(message, message.from_user.id, "Капчу принял. Проверяю, подождите немного.")
    result = await asyncio.to_thread(
        auth_service.submit_captcha,
        message.from_user.id,
        message.text,
    )
    await _answer_tracked(message, message.from_user.id, result.user_message)

    if result.is_success:
        await state.set_state(AuthStates.waiting_for_sms_code)
    elif not result.keep_waiting:
        await state.set_state(AuthStates.waiting_for_phone)


@router.message(AuthStates.waiting_for_sms_code)
async def handle_sms_code(
    message: Message,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not message.from_user or not message.text:
        await message.answer("Отправьте SMS-код текстом.")
        return

    _track_message(message, message.from_user.id)
    if auth_service.is_checking_code(message.from_user.id):
        await message.answer("Код уже проверяется. Подождите немного.")
        return

    await _answer_tracked(message, message.from_user.id, "Код принят. Проверяю авторизацию в HH, подождите немного.")
    result = await asyncio.to_thread(
        auth_service.submit_sms_code,
        message.from_user.id,
        message.text,
    )
    if not result.is_success:
        await _answer_tracked(message, message.from_user.id, result.user_message)
        if not result.keep_waiting:
            await state.set_state(AuthStates.waiting_for_phone)
        return

    await state.clear()
    await _answer_tracked(
        message,
        message.from_user.id,
        f"✅ <b>{html.escape(result.user_message)}</b>",
        parse_mode="HTML",
    )
    await _send_account_panel(
        message,
        account_service,
        account_cache_service,
        status_service,
    )
    tracked = _tracked_message_ids_by_user_id.get(message.from_user.id, [])
    keep_message_id = tracked[-1] if tracked else None
    _tracked_message_ids_by_user_id[message.from_user.id] = (
        [keep_message_id] if keep_message_id else []
    )
    await _cleanup_tracked_messages(
        message.bot,
        message.chat.id,
        message.from_user.id,
        keep_message_id=keep_message_id,
    )


async def _send_automation_status_panel(
    message: Message,
    bot: Bot,
    telegram_user_id: int,
    status_service: AppStatusService,
    stats_service: AutomationStatsService,
    *,
    edit_existing: bool = False,
) -> None:
    status = status_service.get_status(telegram_user_id)
    if status.is_running:
        try:
            stats = await asyncio.to_thread(stats_service.get_stats, telegram_user_id)
            text = stats_service.format_status(stats)
        except AutomationStatsServiceError:
            text = _format_automation_state(status)
    else:
        text = _format_automation_state(status)

    if edit_existing:
        await bot.edit_message_text(
            text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=account_keyboard(status.shows_stop_button),
            parse_mode="HTML",
        )
        status_message = message
    else:
        status_message = await message.answer(
            text,
            reply_markup=account_keyboard(status.shows_stop_button),
            parse_mode="HTML",
        )
    if status.is_running:
        _start_status_updates(
            bot=bot,
            chat_id=status_message.chat.id,
            message_id=status_message.message_id,
            telegram_user_id=telegram_user_id,
            status_service=status_service,
            stats_service=stats_service,
        )


async def _start_automation(
    message: Message,
    bot: Bot,
    telegram_user_id: int,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    cover_letter_service: CoverLetterService,
    stats_service: AutomationStatsService,
    edit_existing: bool = False,
) -> None:
    if not lock_service.acquire_automation_lock(telegram_user_id):
        await message.answer("Сценарий уже запускается. Подождите немного.")
        return

    status = status_service.get_status(telegram_user_id)
    if status.blocks_start:
        lock_service.release_automation_lock(telegram_user_id)
        await _send_automation_status_panel(
            message,
            bot=bot,
            telegram_user_id=telegram_user_id,
            status_service=status_service,
            stats_service=stats_service,
            edit_existing=edit_existing,
        )
        return

    status_service.mark_starting(telegram_user_id)
    start_text = _format_automation_state(status_service.get_status(telegram_user_id))
    if edit_existing:
        await bot.edit_message_text(
            start_text,
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=account_keyboard(is_running=True),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            start_text,
            reply_markup=account_keyboard(is_running=True),
            parse_mode="HTML",
        )

    try:
        await asyncio.to_thread(
            command_runner.start_main_automation,
            telegram_user_id,
            cover_letter_service.get_letter_path(telegram_user_id),
        )
    except CommandRunnerError:
        status_service.mark_failed(telegram_user_id)
        lock_service.release_automation_lock(telegram_user_id)
        await message.answer(
            "⚠️ <b>Не получилось запустить авто-отклик</b>\n\n"
            "Проверьте настройки и hh-applicant-tool.",
            reply_markup=account_keyboard(
                status_service.get_status(telegram_user_id).shows_stop_button
            ),
            parse_mode="HTML",
        )
        return

    status_service.clear_transient_status(telegram_user_id)
    lock_service.release_automation_lock(telegram_user_id)
    await _send_automation_status_panel(
        message,
        bot=bot,
        telegram_user_id=telegram_user_id,
        status_service=status_service,
        stats_service=stats_service,
        edit_existing=edit_existing,
    )


@router.message(F.text == START_BUTTON_TEXT)
async def handle_start_button(
    message: Message,
    bot: Bot,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    auth_service: AuthService,
    cover_letter_service: CoverLetterService,
    stats_service: AutomationStatsService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    await _start_automation(
        message,
        bot=bot,
        telegram_user_id=message.from_user.id,
        command_runner=command_runner,
        status_service=status_service,
        lock_service=lock_service,
        cover_letter_service=cover_letter_service,
        stats_service=stats_service,
    )


@router.callback_query(F.data == START_AUTOMATION_CALLBACK_DATA)
async def handle_start_automation_callback(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    auth_service: AuthService,
    account_service: AccountService,
    cover_letter_service: CoverLetterService,
    stats_service: AutomationStatsService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    await _start_automation(
        message,
        bot=bot,
        telegram_user_id=user.id,
        command_runner=command_runner,
        status_service=status_service,
        lock_service=lock_service,
        cover_letter_service=cover_letter_service,
        stats_service=stats_service,
        edit_existing=True,
    )
    await callback.answer()


@router.callback_query(F.data == STATISTICS_CALLBACK_DATA)
async def handle_statistics_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    stats_service: AutomationStatsService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    source_message = await _delete_callback_message(callback)
    if not source_message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    stats = await asyncio.to_thread(stats_service.get_period_stats, user.id)
    await source_message.answer(
        stats_service.format_period_stats(stats),
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == COVER_LETTER_CALLBACK_DATA)
async def handle_cover_letter_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    cover_letter_service: CoverLetterService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    source_message = await _delete_callback_message(callback)
    if not source_message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    try:
        letter = cover_letter_service.get_letter(user.id)
    except CoverLetterServiceError:
        letter = None
    sent_message = await _answer_tracked(
        source_message,
        user.id,
        _format_cover_letter_menu(letter),
        reply_markup=cover_letter_keyboard(),
        parse_mode="HTML",
    )
    _cover_letter_screen_message_ids_by_user_id[user.id] = sent_message.message_id
    await callback.answer()


@router.callback_query(F.data == COVER_LETTER_EDIT_CALLBACK_DATA)
async def handle_cover_letter_edit_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    source_message = await _delete_callback_message(callback)
    if not source_message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await state.set_state(CoverLetterStates.waiting_for_text)
    sent_message = await _answer_tracked(
        source_message,
        user.id,
        "✏️ <b>Новое сопроводительное письмо</b>\n\n"
        "Отправьте текст одним сообщением.",
        reply_markup=cover_letter_keyboard(),
        parse_mode="HTML",
    )
    _cover_letter_screen_message_ids_by_user_id[user.id] = sent_message.message_id
    await callback.answer()


@router.callback_query(F.data == BACK_TO_ACCOUNT_CALLBACK_DATA)
async def handle_back_to_account_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    await state.clear()
    source_message = await _delete_callback_message(callback)
    if not source_message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await _send_account_panel_for_user(
        source_message,
        user.id,
        account_service,
        account_cache_service,
        status_service,
    )
    await callback.answer()


@router.message(F.text == COVER_LETTER_BUTTON_TEXT)
async def handle_cover_letter_button(
    message: Message,
    settings: Settings,
    auth_service: AuthService,
    cover_letter_service: CoverLetterService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    await _show_cover_letter_menu(message, cover_letter_service)


@router.message(F.text == COVER_LETTER_EDIT_BUTTON_TEXT)
async def handle_cover_letter_edit_button(
    message: Message,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    await _delete_cover_letter_screen(message.bot, message.chat.id, message.from_user.id)
    await state.set_state(CoverLetterStates.waiting_for_text)
    sent_message = await _answer_tracked(
        message,
        message.from_user.id,
        "✏️ <b>Новое сопроводительное письмо</b>\n\n"
        "Отправьте текст одним сообщением.",
        reply_markup=cover_letter_keyboard(),
        parse_mode="HTML",
    )
    _cover_letter_screen_message_ids_by_user_id[message.from_user.id] = sent_message.message_id


@router.message(CoverLetterStates.waiting_for_text, F.text == BACK_BUTTON_TEXT)
async def handle_cover_letter_edit_back(
    message: Message,
    state: FSMContext,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    await state.clear()
    await message.answer(
        "👤 <b>Вернулся в личный кабинет</b>",
        reply_markup=account_keyboard(
            status_service.get_status(message.from_user.id).shows_stop_button
        ),
        parse_mode="HTML",
    )


@router.message(CoverLetterStates.waiting_for_text)
async def handle_cover_letter_text(
    message: Message,
    state: FSMContext,
    settings: Settings,
    auth_service: AuthService,
    cover_letter_service: CoverLetterService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    if not message.from_user or not message.text:
        await message.answer("Отправьте текст письма обычным сообщением.")
        return

    await _delete_message(message)
    await _delete_cover_letter_screen(message.bot, message.chat.id, message.from_user.id)
    try:
        cover_letter_service.save_letter(message.from_user.id, message.text)
    except CoverLetterServiceError:
        sent_message = await _answer_tracked(
            message,
            message.from_user.id,
            "⚠️ Не получилось сохранить письмо. Попробуйте ещё раз.",
        )
        _cover_letter_screen_message_ids_by_user_id[message.from_user.id] = sent_message.message_id
        return

    await state.clear()
    await _show_cover_letter_menu(message, cover_letter_service)


@router.message(F.text == STOP_BUTTON_TEXT)
async def handle_stop_button(
    message: Message,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    if not lock_service.acquire_automation_lock(message.from_user.id):
        await message.answer("Сценарий уже меняет состояние. Подождите немного.")
        return

    status_service.mark_stopping(message.from_user.id)
    await message.answer(
        _format_automation_state(status_service.get_status(message.from_user.id)),
        reply_markup=account_keyboard(is_running=True),
        parse_mode="HTML",
    )
    try:
        await asyncio.to_thread(command_runner.stop_main_automation, message.from_user.id)
    except CommandRunnerError:
        status_service.mark_failed(message.from_user.id)
        lock_service.release_automation_lock(message.from_user.id)
        await message.answer(
            "⚠️ <b>Не получилось остановить авто-отклик</b>\n\n"
            "Проверьте hh-applicant-tool.",
            reply_markup=account_keyboard(
                status_service.get_status(message.from_user.id).shows_stop_button
            ),
            parse_mode="HTML",
        )
        return

    status_service.clear_transient_status(message.from_user.id)
    lock_service.release_automation_lock(message.from_user.id)
    await _send_account_panel(
        message,
        account_service,
        account_cache_service,
        status_service,
    )


@router.callback_query(F.data == STOP_AUTOMATION_CALLBACK_DATA)
async def handle_stop_automation_callback(
    callback: CallbackQuery,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    auth_service: AuthService,
    stats_service: AutomationStatsService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
) -> None:
    message = callback.message
    user = callback.from_user
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    if not lock_service.acquire_automation_lock(user.id):
        await callback.answer("Сценарий уже меняет состояние.", show_alert=True)
        return

    try:
        stats = await asyncio.to_thread(stats_service.get_stats, user.id)
    except AutomationStatsServiceError:
        stats = None

    task = _status_tasks_by_user_id.pop(user.id, None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    status_service.mark_stopping(user.id)
    if isinstance(message, Message):
        await message.edit_text(
            _format_automation_state(status_service.get_status(user.id)),
            reply_markup=account_keyboard(is_running=True),
            parse_mode="HTML",
        )

    try:
        await asyncio.to_thread(command_runner.stop_main_automation, user.id)
    except CommandRunnerError:
        status_service.mark_failed(user.id)
        lock_service.release_automation_lock(user.id)
        await callback.answer("Не получилось остановить сценарий.", show_alert=True)
        return

    status_service.clear_transient_status(user.id)
    lock_service.release_automation_lock(user.id)
    if isinstance(message, Message):
        if stats:
            with suppress(AutomationStatsServiceError):
                await asyncio.to_thread(stats_service.record_session, user.id, stats)
            text = stats_service.format_status_with_state(stats, is_running=False)
        else:
            text = "⚪ <b>Авто-отклик бот остановлен</b>"

        await message.edit_text(
            f"{text}\n\n<i>Загружаем личный кабинет, пожалуйста, подождите.</i>",
            parse_mode="HTML",
        )
        try:
            summary = await asyncio.to_thread(account_service.get_summary, user.id)
            cached_account = account_cache_service.save_summary(user.id, summary)
            await _delete_message(message)
            await message.answer(
                _format_account_panel(cached_account),
                reply_markup=account_keyboard(is_running=False),
                parse_mode="HTML",
            )
        except AccountServiceError:
            await _delete_message(message)
            await message.answer(
                "👤 <b>Личный кабинет</b>\n\nНе получилось обновить данные аккаунта.",
                reply_markup=account_keyboard(is_running=False),
                parse_mode="HTML",
            )

    await callback.answer("Остановил.")


@router.message(F.text == BACK_BUTTON_TEXT)
async def handle_back_button(
    message: Message,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    await _send_account_panel(
        message,
        account_service,
        account_cache_service,
        status_service,
    )


@router.message(F.text == LOGOUT_BUTTON_TEXT)
async def handle_logout_button(
    message: Message,
    state: FSMContext,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    status = status_service.get_status(message.from_user.id)
    if status.status in {AutomationStatus.STARTING, AutomationStatus.STOPPING}:
        await message.answer(
            "Подождите, сценарий сейчас меняет состояние. Потом можно выйти из аккаунта.",
            reply_markup=account_keyboard(status.shows_stop_button),
        )
        return

    if status.is_running:
        try:
            status_service.mark_stopping(message.from_user.id)
            await asyncio.to_thread(command_runner.stop_main_automation, message.from_user.id)
            status_service.clear_transient_status(message.from_user.id)
        except CommandRunnerError:
            status_service.mark_failed(message.from_user.id)
            await message.answer(
                "⚠️ <b>Не получилось остановить авто-отклик перед выходом</b>\n\n"
                "Сначала остановите его вручную.",
                reply_markup=account_keyboard(
                    status_service.get_status(message.from_user.id).shows_stop_button
                ),
                parse_mode="HTML",
            )
            return

    try:
        account_service.logout(message.from_user.id)
    except AccountServiceError:
        await message.answer(
            "⚠️ <b>Не получилось выйти из аккаунта HH</b>\n\n"
            "Попробуйте ещё раз чуть позже.",
            reply_markup=account_keyboard(
                status_service.get_status(message.from_user.id).shows_stop_button
            ),
            parse_mode="HTML",
        )
        return

    if message.from_user:
        auth_service.forget_authorized(message.from_user.id)
    await state.set_state(AuthStates.waiting_for_phone)
    await message.answer(
        "🔴 <b>Вы вышли из аккаунта HH</b>\n\n"
        "Отправьте новый номер телефона, чтобы войти под другим аккаунтом.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == LOGOUT_CALLBACK_DATA)
async def handle_logout_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    source_message = await _delete_callback_message(callback)
    if not source_message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    await source_message.answer(
        "🔴 <b>Выход из аккаунта</b>\n\n"
        "Вы действительно хотите выйти из аккаунта?",
        reply_markup=logout_confirm_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == LOGOUT_CONFIRM_NO_CALLBACK_DATA)
async def handle_logout_cancel_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    await _delete_message(message)
    await _send_account_panel_for_user(
        message,
        user.id,
        account_service,
        account_cache_service,
        status_service,
    )
    await callback.answer()


@router.callback_query(F.data == LOGOUT_CONFIRM_YES_CALLBACK_DATA)
async def handle_logout_confirm_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
) -> None:
    user = callback.from_user
    message = callback.message
    if user.id not in settings.telegram_allowed_user_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    status = status_service.get_status(user.id)
    if status.status in {AutomationStatus.STARTING, AutomationStatus.STOPPING}:
        await callback.answer("Подождите, сценарий сейчас меняет состояние.", show_alert=True)
        return

    if status.is_running:
        try:
            status_service.mark_stopping(user.id)
            await asyncio.to_thread(command_runner.stop_main_automation, user.id)
            status_service.clear_transient_status(user.id)
        except CommandRunnerError:
            status_service.mark_failed(user.id)
            await callback.answer("Сначала остановите авто-отклик.", show_alert=True)
            return

    try:
        account_service.logout(user.id)
    except AccountServiceError:
        await callback.answer("Не получилось выйти из аккаунта HH.", show_alert=True)
        return

    auth_service.forget_authorized(user.id)
    await state.set_state(AuthStates.waiting_for_phone)
    await _delete_message(message)
    await message.answer(
        "🔴 <b>Вы вышли из аккаунта HH</b>\n\n"
        "Отправьте новый номер телефона, чтобы войти под другим аккаунтом.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message()
async def handle_unknown(
    message: Message,
    state: FSMContext,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if message.from_user:
        if auth_service.is_authorized(message.from_user.id):
            await _send_account_panel(
                message,
                account_service,
                account_cache_service,
                status_service,
            )
            return
        try:
            summary = await asyncio.to_thread(
                account_service.get_summary,
                message.from_user.id,
            )
        except AccountServiceError:
            summary = None
        if summary and summary.is_authorized:
            auth_service.mark_authorized(message.from_user.id)
            cached_account = account_cache_service.save_summary(
                message.from_user.id,
                summary,
            )
            await message.answer(
                _format_account_panel(cached_account),
                reply_markup=account_keyboard(
                    status_service.get_status(message.from_user.id).shows_stop_button
                ),
                parse_mode="HTML",
            )
            return

    await state.set_state(AuthStates.waiting_for_phone)
    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Чтобы открыть личный кабинет, сначала войдём в HH.\n\n"
        "🔐 <b>Авторизация HH</b>\n"
        "Отправьте номер телефона.",
        parse_mode="HTML",
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    command_runner = CommandRunner(settings.hh_tool_workdir)
    status_service = AppStatusService(command_runner)
    lock_service = AutomationLockService()
    account_service = AccountService(settings.hh_tool_workdir)
    account_cache_service = AccountCacheService(settings.hh_tool_workdir)
    auth_service = AuthService(account_service, settings.hh_tool_workdir)
    cover_letter_service = CoverLetterService(settings.hh_tool_workdir)
    stats_service = AutomationStatsService(settings.hh_tool_workdir)

    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)

    await dispatcher.start_polling(
        bot,
        settings=settings,
        command_runner=command_runner,
        status_service=status_service,
        lock_service=lock_service,
        account_service=account_service,
        account_cache_service=account_cache_service,
        auth_service=auth_service,
        cover_letter_service=cover_letter_service,
        stats_service=stats_service,
    )


if __name__ == "__main__":
    asyncio.run(main())
