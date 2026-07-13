import asyncio
import html
import logging
import time
from contextlib import suppress
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import Settings, load_settings
from bot.keyboards import (
    AI_DRY_RUN_CALLBACK_DATA,
    AI_DRY_RUN_ALL_CALLBACK_DATA,
    AI_DRY_RUN_APPROVED_CALLBACK_DATA,
    AI_DRY_RUN_BUTTON_TEXT,
    AI_DRY_RUN_CLEAR_CONFIRM_NO_CALLBACK_DATA,
    AI_DRY_RUN_CLEAR_CONFIRM_YES_CALLBACK_DATA,
    AI_DRY_RUN_CLEAR_SKIPPED_CALLBACK_DATA,
    AI_DRY_RUN_HEAVY_CALLBACK_DATA,
    AI_DRY_RUN_LIGHT_CALLBACK_DATA,
    AI_DRY_RUN_REJECTED_CALLBACK_DATA,
    AI_TEST_CALLBACK_DATA,
    AI_TEST_BUTTON_TEXT,
    SETTINGS_CALLBACK_DATA,
    RESUME_BUMP_4H_CALLBACK_DATA,
    RESUME_BUMP_5H_CALLBACK_DATA,
    RESUME_BUMP_CALLBACK_DATA,
    RESUME_BUMP_OFF_CALLBACK_DATA,
    START_AUTOMATION_AI_CALLBACK_DATA,
    START_AUTOMATION_PLAIN_CALLBACK_DATA,
    AUTOMATION_CHANGE_QUERY_CALLBACK_DATA,
    AUTOMATION_CONFIRM_CALLBACK_DATA,
    AUTOMATION_NEW_QUERY_CALLBACK_DATA,
    BACK_BUTTON_TEXT,
    BACK_TO_ACCOUNT_CALLBACK_DATA,
    COVER_LETTER_CALLBACK_DATA,
    COVER_LETTER_BUTTON_TEXT,
    COVER_LETTER_EDIT_CALLBACK_DATA,
    COVER_LETTER_EDIT_BUTTON_TEXT,
    SETTINGS_BUTTON_TEXT,
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
    ai_dry_run_clear_confirm_keyboard,
    ai_dry_run_limit_keyboard,
    ai_dry_run_mode_keyboard,
    ai_dry_run_result_keyboard,
    automation_ai_mode_keyboard,
    automation_limit_keyboard,
    automation_preview_keyboard,
    automation_result_keyboard,
    automation_search_query_keyboard,
    automation_type_keyboard,
    back_keyboard,
    cover_letter_keyboard,
    logout_confirm_keyboard,
    resume_bump_settings_keyboard,
    settings_keyboard,
)
from bot.services.account_service import (
    AccountService,
    AccountServiceError,
    AccountSummary,
)
from bot.services.ai_dry_run_service import (
    AI_DRY_RUN_ALL_TARGET,
    AiDryRunStats,
    get_ai_dry_run_launch_options,
    parse_ai_dry_run_logs,
)
from bot.services.ai_client import (
    AI_TEST_PROMPT,
    AiClient,
    AiClientConnectionError,
    AiClientDisabledError,
    AiClientEmptyResponseError,
    AiClientError,
    AiClientEndpointError,
    AiClientTimeoutError,
)
from bot.services.account_cache_service import (
    AccountCacheService,
    AccountCacheServiceError,
    CachedAccount,
)
from bot.services.app_status_service import AppStatus, AppStatusService, AutomationStatus
from bot.services.auth_service import AuthService
from bot.services.automation_lock_service import AutomationLockService
from bot.services.automation_stats_service import (
    AutomationLogSummary,
    AutomationStats,
    AutomationStatsService,
    AutomationStatsServiceError,
)
from bot.services.command_runner import (
    AutomationLaunchOptions,
    CommandRunner,
    CommandRunnerError,
    VacancySearchEstimate,
)
from bot.services.cover_letter_service import (
    CoverLetterService,
    CoverLetterServiceError,
)
from bot.services.hh_ai_config_service import (
    HhAiConfigService,
    HhAiConfigServiceError,
)
from bot.services.resume_bump_settings_service import (
    ResumeBumpSettings,
    ResumeBumpSettingsService,
    ResumeBumpSettingsServiceError,
)
from bot.services.search_query_history_service import (
    SearchQueryHistoryService,
    SearchQueryHistoryServiceError,
)
from bot.states import AuthStates, AutomationStates, CoverLetterStates


router = Router()
_status_tasks_by_user_id: dict[int, asyncio.Task[None]] = {}
_ai_dry_run_sessions_by_user_id: dict[int, "AiDryRunSession"] = {}
_ai_dry_run_results_by_user_id: dict[int, AiDryRunStats] = {}
_tracked_message_ids_by_user_id: dict[int, list[int]] = {}
_cover_letter_screen_message_ids_by_user_id: dict[int, int] = {}


@dataclass
class AiDryRunSession:
    message: Message
    target_count: int
    ai_filter: str
    stats: AiDryRunStats
    task: asyncio.Task[None] | None = None
    stop_requested: bool = False


@dataclass(frozen=True)
class AiAutomationRun:
    target_count: int
    ai_filter: str


@dataclass(frozen=True)
class AutomationRunContext:
    started_at: float
    target_count: int
    total_pages: int
    per_page: int
    search_query: str
    estimated_found: int | None = None
    estimated_available: int | None = None
    ai_filter: str | None = None


_ai_automation_runs_by_user_id: dict[int, AiAutomationRun] = {}
_automation_runs_by_user_id: dict[int, AutomationRunContext] = {}


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


async def _ensure_resume_bump_running(
    telegram_user_id: int,
    command_runner: CommandRunner,
    resume_bump_settings_service: ResumeBumpSettingsService,
) -> None:
    resume_bump_settings = resume_bump_settings_service.get(telegram_user_id)
    if not resume_bump_settings.is_enabled or resume_bump_settings.interval_hours is None:
        return

    await asyncio.to_thread(
        command_runner.start_resume_bump,
        telegram_user_id,
        resume_bump_settings.interval_hours,
    )


async def _disable_resume_bump(
    telegram_user_id: int,
    command_runner: CommandRunner,
    resume_bump_settings_service: ResumeBumpSettingsService,
) -> None:
    await asyncio.to_thread(command_runner.stop_resume_bump, telegram_user_id)
    resume_bump_settings_service.disable(telegram_user_id)


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


def _format_ai_automation_status(
    *,
    ai_run: AiAutomationRun,
    ai_stats: AiDryRunStats,
    automation_stats: AutomationStats | None,
    is_running: bool,
) -> str:
    title = (
        "🟢 <b>AI-автоотклик запущен</b>"
        if is_running
        else "⚪ <b>AI-автоотклик остановлен</b>"
    )
    target_label = (
        "все доступные"
        if ai_run.target_count == AI_DRY_RUN_ALL_TARGET
        else str(ai_run.target_count)
    )
    checked_label = (
        str(ai_stats.checked_count)
        if ai_run.target_count == AI_DRY_RUN_ALL_TARGET or not is_running
        else f"{ai_stats.checked_count}/{ai_run.target_count}"
    )
    progress_text = (
        "до конца выдачи"
        if ai_run.target_count == AI_DRY_RUN_ALL_TARGET
        else _format_ai_dry_run_progress(ai_stats.checked_count, ai_run.target_count)
    )
    responses_count = automation_stats.responses_count if automation_stats else 0
    tests_count = automation_stats.tests_count if automation_stats else 0
    tail_text = "\n".join(html.escape(line[:350]) for line in ai_stats.events[-6:])
    filter_label = "Heavy" if ai_run.ai_filter == "heavy" else "Light"

    lines = [
        title,
        "",
        "⚙️ <b>Запуск</b>",
        f"• AI-фильтр: <b>{filter_label}</b>",
        f"• цель: <b>{target_label}</b>",
        "• письмо: <b>стандартное</b>",
        "",
        "📊 <b>Прогресс</b>",
        f"• проверено AI: <b>{checked_label}</b>",
        f"<pre>{html.escape(progress_text)}</pre>",
        "",
        "🧠 <b>Решения модели</b>",
        f"• подходит: <b>{ai_stats.suitable_count}</b>",
        f"• отклонено AI: <b>{ai_stats.rejected_count}</b>",
        f"• уже было отклонено: <b>{ai_stats.already_rejected_count}</b>",
        "",
        "📨 <b>Отклики</b>",
        f"• отправлено: <b>{responses_count}</b>",
        f"• тестов выполнено: <b>{tests_count}</b>",
    ]
    if ai_stats.current_resume:
        lines.extend(["", "📄 <b>Резюме</b>", html.escape(ai_stats.current_resume)])
    if tail_text:
        lines.extend(["", "<b>Последние события:</b>", f"<pre>{tail_text}</pre>"])

    return "\n".join(lines)


def _format_ai_error(exc: AiClientError) -> str:
    if isinstance(exc, AiClientDisabledError):
        return "AI сейчас выключен в настройках."
    if isinstance(exc, AiClientTimeoutError):
        return "⚠️ Модель не ответила вовремя. Попробуйте ещё раз."
    if isinstance(exc, AiClientConnectionError):
        return (
            "⚠️ <b>Не удалось подключиться к локальной модели</b>\n\n"
            "Проверьте, что Ollama запущена и адрес AI_BASE_URL указан верно."
        )
    if isinstance(exc, AiClientEmptyResponseError):
        return "⚠️ Модель ответила пустым сообщением. Попробуйте ещё раз."
    if isinstance(exc, AiClientEndpointError):
        return (
            "⚠️ <b>AI endpoint вернул ошибку</b>\n\n"
            "Проверьте, что модель скачана и имя AI_MODEL указано верно."
        )
    return "⚠️ Не получилось выполнить AI-тест. Попробуйте ещё раз позже."


def _format_ai_dry_run_limit_prompt() -> str:
    return (
        "🧪 <b>AI-анализ вакансий</b>\n\n"
        "Сколько вакансий дать модели проверить?\n\n"
        "Уже отклонённые ранее вакансии не считаются в прогон."
    )


def _format_ai_dry_run_mode_prompt() -> str:
    return (
        "🧪 <b>AI-анализ вакансий</b>\n\n"
        "Выберите режим фильтрации:\n\n"
        "⚡ <b>Light</b> — быстрее, смотрит роль и ключевые навыки.\n"
        "🧠 <b>Heavy</b> — медленнее, анализирует вакансию подробнее."
    )


def _format_ai_dry_run_limit_prompt_for_mode(ai_filter: str) -> str:
    label = "Heavy" if ai_filter == "heavy" else "Light"
    return (
        "🧪 <b>AI-анализ вакансий</b>\n\n"
        f"Режим: <b>{label}</b>\n\n"
        "Сколько вакансий дать модели проверить?\n\n"
        "Уже отклонённые ранее вакансии не считаются в прогон."
    )


def _format_automation_type_prompt() -> str:
    return (
        "▶️ <b>Запуск авто-отклика</b>\n\n"
        "Выберите режим:\n\n"
        "🚀 <b>Обычный</b> — без нейронки, только стандартные фильтры.\n"
        "🧠 <b>С AI-фильтром</b> — модель сначала оценивает вакансию, "
        "а сопроводительное пока берётся ваше стандартное."
    )


def _format_automation_ai_mode_prompt() -> str:
    return (
        "🧠 <b>Авто-отклик с AI</b>\n\n"
        "Выберите режим фильтрации:\n\n"
        "⚡ <b>Light</b> — быстрее, грубее.\n"
        "🧠 <b>Heavy</b> — медленнее, внимательнее читает вакансию."
    )


def _format_automation_limit_prompt(mode: str, ai_filter: str | None = None) -> str:
    if mode == "ai":
        filter_label = "Heavy" if ai_filter == "heavy" else "Light"
        mode_line = f"Режим: <b>AI / {filter_label}</b>"
    else:
        mode_line = "Режим: <b>обычный авто-отклик</b>"

    return (
        "🎯 <b>Сколько вакансий просмотреть?</b>\n\n"
        f"{mode_line}\n\n"
        "Для 10/30/50 бот ограничит один проход выбранным количеством вакансий. "
        "Для «Все доступные» возьмёт максимальный доступный объём выдачи."
    )


def _format_automation_search_prompt(mode: str, ai_filter: str | None = None) -> str:
    if mode == "ai":
        filter_label = "Heavy" if ai_filter == "heavy" else "Light"
        mode_line = f"Режим: <b>AI / {filter_label}</b>"
    else:
        mode_line = "Режим: <b>обычный авто-отклик</b>"

    return (
        "🔎 <b>Поисковый запрос</b>\n\n"
        f"{mode_line}\n\n"
        "Выберите запрос из истории или напишите новый запрос, по которому искать вакансии на HH.\n"
        "Например: <i>Python backend</i>, <i>Vue frontend</i>, <i>QA automation</i>."
    )


def _normalize_search_query(text: str | None) -> str:
    return " ".join((text or "").split())


def _get_automation_launch_options(
    target_count: int,
    ai_filter: str | None = None,
    search_query: str | None = None,
) -> AutomationLaunchOptions:
    if ai_filter:
        ai_options = get_ai_dry_run_launch_options(target_count, ai_filter)
        return AutomationLaunchOptions(
            target_count=target_count,
            total_pages=ai_options.total_pages,
            per_page=ai_options.per_page,
            ai_filter=ai_filter,
            search_query=search_query,
        )

    if target_count == AI_DRY_RUN_ALL_TARGET:
        return AutomationLaunchOptions(
            target_count=target_count,
            total_pages=20,
            per_page=100,
            search_query=search_query,
        )

    if target_count not in {10, 30, 50}:
        raise ValueError("Unsupported automation target")

    return AutomationLaunchOptions(
        target_count=target_count,
        total_pages=1,
        per_page=target_count,
        search_query=search_query,
    )


def _apply_estimate_to_launch_options(
    launch_options: AutomationLaunchOptions,
    estimate: VacancySearchEstimate,
) -> AutomationLaunchOptions:
    total_pages = launch_options.total_pages
    if launch_options.target_count == AI_DRY_RUN_ALL_TARGET and estimate.pages > 0:
        total_pages = estimate.pages

    return AutomationLaunchOptions(
        target_count=launch_options.target_count,
        total_pages=total_pages,
        per_page=launch_options.per_page,
        ai_filter=launch_options.ai_filter,
        search_query=launch_options.search_query,
        estimated_found=estimate.found,
        estimated_available=estimate.available_count,
    )


def _format_automation_preview(
    *,
    launch_options: AutomationLaunchOptions,
    estimate: VacancySearchEstimate,
) -> str:
    mode_label = (
        f"AI / {'Heavy' if launch_options.ai_filter == 'heavy' else 'Light'}"
        if launch_options.ai_filter
        else "обычный авто-отклик"
    )
    target_label = (
        "все доступные"
        if launch_options.target_count == AI_DRY_RUN_ALL_TARGET
        else str(launch_options.target_count)
    )
    available_count = estimate.available_count
    if launch_options.target_count == AI_DRY_RUN_ALL_TARGET:
        check_label = str(min(available_count, launch_options.total_pages * launch_options.per_page))
    else:
        check_label = str(min(available_count, launch_options.target_count))

    lines = [
        "🔎 <b>Проверка перед запуском</b>",
        "",
        f"• запрос: <b>{html.escape(estimate.search_query)}</b>",
        f"• режим: <b>{mode_label}</b>",
        f"• цель: <b>{target_label}</b>",
        "",
        "📊 <b>Выдача HH</b>",
        f"• HH нашёл: <b>{estimate.found}</b>",
        f"• доступно к проходу через API: <b>{available_count}</b>",
        f"• бот проверит максимум: <b>{check_label}</b>",
    ]

    if launch_options.target_count == AI_DRY_RUN_ALL_TARGET:
        lines.append(
            f"• технический лимит прохода: <b>{launch_options.total_pages} стр. × {launch_options.per_page}</b>"
        )
    elif available_count < launch_options.target_count:
        lines.append("• доступных вакансий меньше выбранного лимита")

    if estimate.found == 0:
        lines.extend(
            [
                "",
                "По этому запросу HH ничего не нашёл. Лучше изменить запрос перед запуском.",
            ]
        )
    else:
        lines.extend(["", "Запустить авто-отклик с такими параметрами?"])

    return "\n".join(lines)


def _format_duration(seconds: int) -> str:
    seconds = max(seconds, 0)
    minutes, rest_seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин {rest_seconds} сек"
    return f"{rest_seconds} сек"


def _format_automation_final_report(
    *,
    summary: AutomationLogSummary,
    context: AutomationRunContext | None,
    fallback_stats: AutomationStats | None,
) -> str:
    duration_seconds = summary.duration_seconds
    if duration_seconds <= 0 and context:
        duration_seconds = round(time.time() - context.started_at)

    search_query = summary.search_query or (context.search_query if context else "")
    found_count = summary.found_count or (context.estimated_found if context else 0) or 0
    available_count = (
        summary.available_count
        or (context.estimated_available if context else 0)
        or 0
    )
    responses_count = summary.responses_count or (
        fallback_stats.responses_count if fallback_stats else 0
    )
    tests_count = summary.tests_count or (
        fallback_stats.tests_count if fallback_stats else 0
    )

    lines = [
        "⚪ <b>Авто-отклик завершён</b>",
        "",
        "⚙️ <b>Запуск</b>",
    ]
    if search_query:
        lines.append(f"• запрос: <b>{html.escape(search_query)}</b>")
    lines.append(f"• время работы: <b>{_format_duration(duration_seconds)}</b>")

    lines.extend(
        [
            "",
            "📊 <b>Вакансии</b>",
            f"• HH нашёл: <b>{found_count}</b>",
            f"• доступно через API: <b>{available_count}</b>",
            f"• обработано ботом: <b>{summary.processed_count}</b>",
            "",
            "📨 <b>Отклики</b>",
            f"• отправлено: <b>{responses_count}</b>",
            f"• с тестами: <b>{tests_count}</b>",
            "",
            "🧹 <b>Пропуски</b>",
            f"• уже был отклик/отказ: <b>{summary.relation_skipped_count}</b>",
            f"• из них отказов: <b>{summary.rejection_relation_count}</b>",
            f"• уже отклонено AI раньше: <b>{summary.already_ai_rejected_count}</b>",
            f"• AI отклонил сейчас: <b>{summary.ai_rejected_count}</b>",
            f"• regex-фильтр: <b>{summary.excluded_filter_count}</b>",
        ]
    )

    other_skipped = (
        summary.archived_count
        + summary.skipped_tests_count
        + summary.redirect_count
    )
    if other_skipped:
        lines.append(f"• прочие пропуски: <b>{other_skipped}</b>")
    if summary.limit_reached:
        lines.extend(["", "⛔ Остановлено из-за лимита откликов HH."])

    return "\n".join(lines)


def _format_ai_dry_run_stats(
    stats: AiDryRunStats,
    *,
    title: str,
    is_running: bool,
) -> str:
    if stats.target_count == AI_DRY_RUN_ALL_TARGET:
        target_label = "все доступные"
        checked_label = str(stats.checked_count)
        progress_text = "до конца выдачи"
    else:
        target_label = str(stats.target_count)
        checked_label = f"{stats.checked_count}/{stats.target_count}" if is_running else str(stats.checked_count)
        progress_text = _format_ai_dry_run_progress(stats.checked_count, stats.target_count)

    tail_text = "\n".join(html.escape(line[:350]) for line in stats.events[-6:])
    filter_label = "Heavy" if stats.ai_filter == "heavy" else "Light"
    lines = [
        title,
        "",
        "⚙️ <b>Запуск</b>",
        "• режим: <b>dry-run</b>",
        f"• AI-фильтр: <b>{filter_label}</b>",
        f"• цель: <b>{target_label}</b>",
        "",
        "📊 <b>Прогресс</b>",
        f"• проверено AI: <b>{checked_label}</b>",
        f"<pre>{html.escape(progress_text)}</pre>",
        "",
        "🧠 <b>Решения модели</b>",
        f"• подходит: <b>{stats.suitable_count}</b>",
        f"• отклонено: <b>{stats.rejected_count}</b>",
        f"• уже было отклонено: <b>{stats.already_rejected_count}</b>",
        "• реальных откликов: <b>0</b>",
    ]
    if stats.current_resume:
        lines.extend(
            [
                "",
                "📄 <b>Резюме</b>",
                html.escape(stats.current_resume),
            ]
        )

    if (
        stats.target_count != AI_DRY_RUN_ALL_TARGET
        and stats.checked_count < stats.target_count
        and stats.already_rejected_count > 0
    ):
        lines.extend(
            [
                "",
                "Много вакансий уже было отклонено раньше, поэтому они не считаются в прогон.",
            ]
        )
    if tail_text:
        lines.extend(["", "<b>Последние события:</b>", f"<pre>{tail_text}</pre>"])

    return "\n".join(lines)


def _format_ai_dry_run_progress(checked_count: int, target_count: int) -> str:
    if target_count <= 0:
        return "до конца выдачи"

    ratio = min(1.0, checked_count / target_count)
    filled = round(ratio * 12)
    empty = 12 - filled
    percent = round(ratio * 100)
    return f"[{'#' * filled}{'-' * empty}] {percent}%"


def _format_ai_dry_run_vacancy_report(stats: AiDryRunStats, report_type: str) -> str:
    if report_type == "approved":
        title = "✅ <b>Подходящие вакансии</b>"
        urls = stats.approved_urls
        empty_text = "AI не отметил подходящих вакансий в последнем прогоне."
    elif report_type == "rejected":
        title = "🧠 <b>Отклонённые вакансии</b>"
        urls = stats.rejected_urls
        empty_text = "AI не отклонил вакансии в последнем прогоне."
    else:
        title = "📋 <b>Все проверенные вакансии</b>"
        urls = (*stats.approved_urls, *stats.rejected_urls)
        empty_text = "В последнем прогоне нет вакансий, которые модель реально проверила."

    lines = [title, ""]
    if urls:
        for index, url in enumerate(urls, start=1):
            lines.append(f"{index}. {html.escape(url)}")
    else:
        lines.append(empty_text)

    if stats.already_rejected_urls:
        lines.extend(
            [
                "",
                f"Уже были отклонены ранее: <b>{len(stats.already_rejected_urls)}</b>",
                "Они не входят в список проверенных моделью.",
            ]
        )

    return "\n".join(lines)


async def _edit_ai_dry_run_message(
    message: Message,
    text: str,
    *,
    is_running: bool,
    is_result: bool = False,
) -> None:
    reply_markup = (
        ai_dry_run_result_keyboard()
        if is_result
        else account_keyboard(is_running=is_running)
    )
    with suppress(TelegramBadRequest):
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


async def _safe_edit_ai_dry_run_screen(
    session: AiDryRunSession,
    *,
    title: str,
    is_running: bool,
    is_result: bool = False,
) -> None:
    await _edit_ai_dry_run_message(
        session.message,
        _format_ai_dry_run_stats(
            session.stats,
            title=title,
            is_running=is_running,
        ),
        is_running=is_running,
        is_result=is_result,
    )


def _get_ai_dry_run_search_query(
    telegram_user_id: int,
    account_cache_service: AccountCacheService,
) -> str | None:
    account = account_cache_service.get(telegram_user_id)
    if not account or not account.resumes:
        return None

    title = account.resumes[0].title.strip()
    return title or None


def _get_ai_dry_run_log_tail(target_count: int) -> int | str:
    return "all" if target_count == AI_DRY_RUN_ALL_TARGET else 1200


async def _monitor_ai_dry_run(
    *,
    telegram_user_id: int,
    command_runner: CommandRunner,
    status_service: AppStatusService,
) -> None:
    try:
        while True:
            session = _ai_dry_run_sessions_by_user_id.get(telegram_user_id)
            if not session:
                return

            logs = await asyncio.to_thread(
                command_runner.get_container_logs,
                telegram_user_id,
                tail=_get_ai_dry_run_log_tail(session.target_count),
            )
            session.stats = parse_ai_dry_run_logs(
                logs,
                target_count=session.target_count,
                ai_filter=session.ai_filter,
            )

            if (
                session.target_count != AI_DRY_RUN_ALL_TARGET
                and session.stats.checked_count >= session.target_count
            ):
                await asyncio.to_thread(command_runner.stop_main_automation, telegram_user_id)
                break

            status = status_service.get_status(telegram_user_id)
            if session.stats.is_finished or not status.is_running:
                break

            await _safe_edit_ai_dry_run_screen(
                session,
                title="🧪 <b>AI-анализ идёт</b>",
                is_running=True,
            )
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        raise
    except (CommandRunnerError, HhAiConfigServiceError):
        session = _ai_dry_run_sessions_by_user_id.get(telegram_user_id)
        if session:
            await _edit_ai_dry_run_message(
                session.message,
                _format_ai_dry_run_error(CommandRunnerError()),
                is_running=False,
            )
    finally:
        session = _ai_dry_run_sessions_by_user_id.pop(telegram_user_id, None)
        status_service.clear_transient_status(telegram_user_id)
        if session:
            _ai_dry_run_results_by_user_id[telegram_user_id] = session.stats
            title = (
                "⏹ <b>AI-анализ остановлен</b>"
                if session.stop_requested and not session.stats.is_finished
                else "🧪 <b>AI-анализ завершён</b>"
            )
            await _safe_edit_ai_dry_run_screen(
                session,
                title=title,
                is_running=False,
                is_result=True,
            )


async def _stop_ai_dry_run_session(
    *,
    telegram_user_id: int,
    command_runner: CommandRunner,
    status_service: AppStatusService,
) -> bool:
    session = _ai_dry_run_sessions_by_user_id.pop(telegram_user_id, None)
    if not session:
        return False

    session.stop_requested = True
    if session.task:
        session.task.cancel()
        with suppress(asyncio.CancelledError):
            await session.task

    with suppress(CommandRunnerError):
        logs = await asyncio.to_thread(
            command_runner.get_container_logs,
            telegram_user_id,
            tail=_get_ai_dry_run_log_tail(session.target_count),
        )
        session.stats = parse_ai_dry_run_logs(
            logs,
            target_count=session.target_count,
            ai_filter=session.ai_filter,
        )

    await _safe_edit_ai_dry_run_screen(
        session,
        title="⏹ <b>AI-анализ останавливается</b>",
        is_running=True,
    )
    await asyncio.to_thread(command_runner.stop_main_automation, telegram_user_id)
    status_service.clear_transient_status(telegram_user_id)
    await _safe_edit_ai_dry_run_screen(
        session,
        title="⏹ <b>AI-анализ остановлен</b>",
        is_running=False,
        is_result=True,
    )
    _ai_dry_run_results_by_user_id[telegram_user_id] = session.stats
    return True


def _format_ai_dry_run_error(exc: Exception) -> str:
    if isinstance(exc, HhAiConfigServiceError):
        return (
            "⚠️ <b>Не получилось подготовить AI-настройки для hh-applicant-tool</b>\n\n"
            "Проверьте AI-переменные в .env и попробуйте ещё раз."
        )
    if isinstance(exc, CommandRunnerError):
        return (
            "⚠️ <b>Не получилось запустить AI-анализ</b>\n\n"
            "Проверьте, что hh-applicant-tool настроен, Docker работает, а локальная модель доступна из контейнера."
        )
    return "⚠️ Не получилось выполнить AI-анализ. Попробуйте ещё раз позже."


async def _start_ai_dry_run_session(
    *,
    status_message: Message,
    telegram_user_id: int,
    target_count: int,
    ai_filter: str,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    cover_letter_service: CoverLetterService,
    hh_ai_config_service: HhAiConfigService,
    search_query: str | None = None,
) -> None:
    options = get_ai_dry_run_launch_options(
        target_count,
        ai_filter,
        search_query=search_query,
    )
    session = AiDryRunSession(
        message=status_message,
        target_count=target_count,
        ai_filter=ai_filter,
        stats=AiDryRunStats(target_count=target_count, ai_filter=ai_filter),
    )
    status_service.mark_starting(telegram_user_id)
    await _safe_edit_ai_dry_run_screen(
        session,
        title="🧪 <b>AI-анализ запускается</b>",
        is_running=True,
    )

    try:
        await asyncio.to_thread(
            hh_ai_config_service.configure_vacancy_filter,
            telegram_user_id,
        )
        await asyncio.to_thread(
            command_runner.start_ai_dry_run,
            telegram_user_id,
            options,
            cover_letter_service.get_letter_path(telegram_user_id),
            ai_filter=ai_filter,
        )
        status_service.clear_transient_status(telegram_user_id)
    except (HhAiConfigServiceError, CommandRunnerError) as exc:
        status_service.clear_transient_status(telegram_user_id)
        lock_service.release_automation_lock(telegram_user_id)
        await _edit_ai_dry_run_message(
            status_message,
            _format_ai_dry_run_error(exc),
            is_running=False,
            is_result=True,
        )
        return

    task = asyncio.create_task(
        _monitor_ai_dry_run(
            telegram_user_id=telegram_user_id,
            command_runner=command_runner,
            status_service=status_service,
        )
    )
    session.task = task
    _ai_dry_run_sessions_by_user_id[telegram_user_id] = session
    lock_service.release_automation_lock(telegram_user_id)


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
    show_result_buttons: bool = False,
) -> None:
    if show_result_buttons:
        reply_markup = automation_result_keyboard()
    elif show_stop_button:
        reply_markup = account_keyboard(is_running=True)
    else:
        reply_markup = None
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
    command_runner: CommandRunner,
    status_service: AppStatusService,
    stats_service: AutomationStatsService,
) -> None:
    last_text = ""
    while status_service.get_status(telegram_user_id).is_running:
        ai_run = _ai_automation_runs_by_user_id.get(telegram_user_id)
        try:
            stats = await asyncio.to_thread(stats_service.get_stats, telegram_user_id)
        except AutomationStatsServiceError:
            stats = None

        if ai_run:
            should_stop_ai_run = False
            try:
                logs = await asyncio.to_thread(
                    command_runner.get_container_logs,
                    telegram_user_id,
                    tail=_get_ai_dry_run_log_tail(ai_run.target_count),
                )
                ai_stats = parse_ai_dry_run_logs(
                    logs,
                    target_count=ai_run.target_count,
                    ai_filter=ai_run.ai_filter,
                )
                text = _format_ai_automation_status(
                    ai_run=ai_run,
                    ai_stats=ai_stats,
                    automation_stats=stats,
                    is_running=True,
                )
                should_stop_ai_run = (
                    ai_run.target_count != AI_DRY_RUN_ALL_TARGET
                    and ai_stats.checked_count >= ai_run.target_count
                )
            except CommandRunnerError:
                text = "🟢 <b>AI-автоотклик запущен</b>\n\nСтатистика пока недоступна."
            if should_stop_ai_run:
                with suppress(CommandRunnerError):
                    await asyncio.to_thread(
                        command_runner.stop_main_automation,
                        telegram_user_id,
                    )
        elif stats:
            text = stats_service.format_status(stats)
        else:
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

    final_stats = None
    with suppress(AutomationStatsServiceError):
        final_stats = await asyncio.to_thread(stats_service.get_stats, telegram_user_id)

    final_summary = None
    with suppress(CommandRunnerError):
        logs = await asyncio.to_thread(
            command_runner.get_container_logs,
            telegram_user_id,
            tail="all",
        )
        final_summary = stats_service.parse_automation_summary(logs)

    context = _automation_runs_by_user_id.pop(telegram_user_id, None)
    if final_summary:
        if final_stats:
            with suppress(AutomationStatsServiceError):
                await asyncio.to_thread(
                    stats_service.record_session,
                    telegram_user_id,
                    final_stats,
                )
        final_text = _format_automation_final_report(
            summary=final_summary,
            context=context,
            fallback_stats=final_stats,
        )
    elif final_stats:
        with suppress(AutomationStatsServiceError):
            await asyncio.to_thread(
                stats_service.record_session,
                telegram_user_id,
                final_stats,
            )
        final_text = stats_service.format_status_with_state(
            final_stats,
            is_running=False,
        )
    elif last_text:
        final_text = last_text.replace("запущен", "остановлен", 1).replace("🟢", "⚪", 1)
    else:
        final_text = ""

    if final_text:
        await _safe_edit_message(
            bot,
            chat_id,
            message_id,
            final_text,
            show_stop_button=False,
            show_result_buttons=True,
        )
    _ai_automation_runs_by_user_id.pop(telegram_user_id, None)


def _start_status_updates(
    *,
    bot: Bot,
    chat_id: int,
    message_id: int,
    telegram_user_id: int,
    command_runner: CommandRunner,
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
            command_runner=command_runner,
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
    command_runner: CommandRunner,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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
            with suppress(CommandRunnerError):
                await _ensure_resume_bump_running(
                    message.from_user.id,
                    command_runner,
                    resume_bump_settings_service,
                )
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
    account_cache_service: AccountCacheService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not message.from_user or not message.text:
        await message.answer("Отправьте номер телефона текстом.")
        return

    _track_message(message, message.from_user.id)
    with suppress(AccountCacheServiceError):
        account_cache_service.clear(message.from_user.id)
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
    command_runner: CommandRunner,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    status_service: AppStatusService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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
    with suppress(AccountCacheServiceError):
        account_cache_service.clear(message.from_user.id)
    with suppress(CommandRunnerError):
        await _ensure_resume_bump_running(
            message.from_user.id,
            command_runner,
            resume_bump_settings_service,
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
    command_runner: CommandRunner,
    status_service: AppStatusService,
    stats_service: AutomationStatsService,
    *,
    edit_existing: bool = False,
) -> None:
    status = status_service.get_status(telegram_user_id)
    ai_run = _ai_automation_runs_by_user_id.get(telegram_user_id)
    if status.is_running and ai_run:
        try:
            logs = await asyncio.to_thread(
                command_runner.get_container_logs,
                telegram_user_id,
                tail=_get_ai_dry_run_log_tail(ai_run.target_count),
            )
            ai_stats = parse_ai_dry_run_logs(
                logs,
                target_count=ai_run.target_count,
                ai_filter=ai_run.ai_filter,
            )
            automation_stats = await asyncio.to_thread(
                stats_service.get_stats,
                telegram_user_id,
            )
            text = _format_ai_automation_status(
                ai_run=ai_run,
                ai_stats=ai_stats,
                automation_stats=automation_stats,
                is_running=True,
            )
        except (AutomationStatsServiceError, CommandRunnerError):
            text = "🟢 <b>AI-автоотклик запущен</b>\n\nСтатистика пока недоступна."
    elif status.is_running:
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
            command_runner=command_runner,
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
    hh_ai_config_service: HhAiConfigService | None = None,
    launch_options: AutomationLaunchOptions | None = None,
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
            command_runner=command_runner,
            status_service=status_service,
            stats_service=stats_service,
            edit_existing=edit_existing,
        )
        return

    status_service.mark_starting(telegram_user_id)
    if launch_options:
        _automation_runs_by_user_id[telegram_user_id] = AutomationRunContext(
            started_at=time.time(),
            target_count=launch_options.target_count,
            total_pages=launch_options.total_pages,
            per_page=launch_options.per_page,
            search_query=launch_options.search_query or "",
            estimated_found=launch_options.estimated_found,
            estimated_available=launch_options.estimated_available,
            ai_filter=launch_options.ai_filter,
        )
    if launch_options and launch_options.ai_filter:
        _ai_automation_runs_by_user_id[telegram_user_id] = AiAutomationRun(
            target_count=launch_options.target_count,
            ai_filter=launch_options.ai_filter,
        )
    else:
        _ai_automation_runs_by_user_id.pop(telegram_user_id, None)

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
        if launch_options and launch_options.ai_filter:
            if not hh_ai_config_service:
                raise CommandRunnerError("AI config service is not available")
            await asyncio.to_thread(
                hh_ai_config_service.configure_vacancy_filter,
                telegram_user_id,
            )
        await asyncio.to_thread(
            command_runner.start_main_automation,
            telegram_user_id,
            cover_letter_service.get_letter_path(telegram_user_id),
            launch_options,
        )
    except (CommandRunnerError, HhAiConfigServiceError):
        _automation_runs_by_user_id.pop(telegram_user_id, None)
        _ai_automation_runs_by_user_id.pop(telegram_user_id, None)
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
        command_runner=command_runner,
        status_service=status_service,
        stats_service=stats_service,
        edit_existing=edit_existing,
    )


@router.message(F.text == START_BUTTON_TEXT)
async def handle_start_button(
    message: Message,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return
    if not message.from_user:
        return

    if status_service.get_status(message.from_user.id).blocks_start:
        await message.answer("Авто-отклик уже запущен. Сначала остановите текущий сценарий.")
        return

    await message.answer(
        _format_automation_type_prompt(),
        reply_markup=automation_type_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == START_AUTOMATION_CALLBACK_DATA)
async def handle_start_automation_callback(
    callback: CallbackQuery,
    settings: Settings,
    status_service: AppStatusService,
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
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Авто-отклик уже запущен.", show_alert=True)
        return
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    await message.edit_text(
        _format_automation_type_prompt(),
        reply_markup=automation_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == START_AUTOMATION_PLAIN_CALLBACK_DATA)
async def handle_start_plain_automation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
    search_query_history_service: SearchQueryHistoryService,
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
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Авто-отклик уже запущен.", show_alert=True)
        return

    await state.update_data(automation_mode="plain", automation_ai_filter=None)
    await state.set_state(AutomationStates.waiting_for_search_query)
    history = search_query_history_service.get_queries(user.id, limit=5)
    await message.edit_text(
        _format_automation_search_prompt("plain"),
        reply_markup=automation_search_query_keyboard(history),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == START_AUTOMATION_AI_CALLBACK_DATA)
async def handle_start_ai_automation_callback(
    callback: CallbackQuery,
    settings: Settings,
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
    if not settings.ai.enabled:
        await callback.answer("AI выключен в настройках.", show_alert=True)
        return
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Авто-отклик уже запущен.", show_alert=True)
        return

    await message.edit_text(
        _format_automation_ai_mode_prompt(),
        reply_markup=automation_ai_mode_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^automation:start:ai:(light|heavy)$"))
async def handle_start_ai_automation_mode_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
    search_query_history_service: SearchQueryHistoryService,
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
    if not settings.ai.enabled:
        await callback.answer("AI выключен в настройках.", show_alert=True)
        return
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Авто-отклик уже запущен.", show_alert=True)
        return

    ai_filter = str(callback.data).rsplit(":", 1)[-1]
    await state.update_data(automation_mode="ai", automation_ai_filter=ai_filter)
    await state.set_state(AutomationStates.waiting_for_search_query)
    history = search_query_history_service.get_queries(user.id, limit=5)
    await message.edit_text(
        _format_automation_search_prompt("ai", ai_filter),
        reply_markup=automation_search_query_keyboard(history),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AutomationStates.waiting_for_search_query)
async def handle_automation_search_query(
    message: Message,
    state: FSMContext,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return
    if not message.from_user:
        return
    if not await _is_authorized_user(message.from_user.id, auth_service, account_service):
        await message.answer("Сначала пройдите авторизацию.")
        return
    if status_service.get_status(message.from_user.id).blocks_start:
        await state.clear()
        await message.answer("Авто-отклик уже запущен. Сначала остановите текущий сценарий.")
        return

    search_query = _normalize_search_query(message.text)
    if len(search_query) < 2:
        await message.answer(
            "Запрос слишком короткий. Напишите, какую работу искать, например: <i>Python backend</i>.",
            parse_mode="HTML",
        )
        return
    if len(search_query) > 120:
        await message.answer("Запрос слишком длинный. Сократите его до 120 символов.")
        return

    data = await state.get_data()
    mode = str(data.get("automation_mode") or "plain")
    ai_filter = data.get("automation_ai_filter")
    await state.update_data(automation_search_query=search_query)
    await message.answer(
        _format_automation_limit_prompt(mode, str(ai_filter) if ai_filter else None),
        reply_markup=automation_limit_keyboard(mode, str(ai_filter) if ai_filter else None),
        parse_mode="HTML",
    )


@router.callback_query(F.data.regexp(r"^automation:query:(new|\d+)$"))
async def handle_automation_history_query_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
    search_query_history_service: SearchQueryHistoryService,
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
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Авто-отклик уже запущен.", show_alert=True)
        return

    data = await state.get_data()
    mode = str(data.get("automation_mode") or "plain")
    ai_filter = data.get("automation_ai_filter")
    selected = str(callback.data).rsplit(":", 1)[-1]
    if selected == "new":
        await state.set_state(AutomationStates.waiting_for_search_query)
        history = search_query_history_service.get_queries(user.id, limit=5)
        await message.edit_text(
            _format_automation_search_prompt(mode, str(ai_filter) if ai_filter else None),
            reply_markup=automation_search_query_keyboard(history),
            parse_mode="HTML",
        )
        await callback.answer("Напишите новый запрос сообщением.")
        return

    try:
        index = int(selected)
    except ValueError:
        await callback.answer("Неизвестный запрос.", show_alert=True)
        return

    history = search_query_history_service.get_queries(user.id, limit=5)
    if index < 0 or index >= len(history):
        await callback.answer("Запрос уже недоступен.", show_alert=True)
        return

    search_query = history[index]
    await state.update_data(automation_search_query=search_query)
    await message.edit_text(
        _format_automation_limit_prompt(mode, str(ai_filter) if ai_filter else None),
        reply_markup=automation_limit_keyboard(mode, str(ai_filter) if ai_filter else None),
        parse_mode="HTML",
    )
    await callback.answer("Запрос выбран.")


@router.callback_query(
    F.data.regexp(r"^automation:start:(plain:(10|30|50|all)|ai:(light|heavy):(10|30|50|all))$")
)
async def handle_start_automation_limit_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
    search_query_history_service: SearchQueryHistoryService,
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

    parts = str(callback.data).split(":")
    try:
        mode = parts[2]
        if mode == "plain":
            ai_filter = None
            raw_target = parts[3]
        else:
            ai_filter = parts[3]
            raw_target = parts[4]
        target_count = AI_DRY_RUN_ALL_TARGET if raw_target == "all" else int(raw_target)
    except (IndexError, ValueError):
        await callback.answer("Неизвестный режим запуска.", show_alert=True)
        return

    if ai_filter and not settings.ai.enabled:
        await callback.answer("AI выключен в настройках.", show_alert=True)
        return

    data = await state.get_data()
    search_query = _normalize_search_query(str(data.get("automation_search_query") or ""))
    if not search_query:
        await state.update_data(automation_mode=mode, automation_ai_filter=ai_filter)
        await state.set_state(AutomationStates.waiting_for_search_query)
        history = search_query_history_service.get_queries(user.id, limit=5)
        await message.edit_text(
            _format_automation_search_prompt(mode, ai_filter),
            reply_markup=automation_search_query_keyboard(history),
            parse_mode="HTML",
        )
        await callback.answer("Сначала задайте поисковый запрос.", show_alert=True)
        return

    try:
        launch_options = _get_automation_launch_options(
            target_count,
            ai_filter,
            search_query=search_query,
        )
    except ValueError:
        await callback.answer("Неизвестный режим запуска.", show_alert=True)
        return

    await callback.answer("Проверяю выдачу HH...")
    try:
        estimate = await asyncio.to_thread(
            command_runner.estimate_vacancy_search,
            user.id,
            search_query=search_query,
            total_pages=launch_options.total_pages,
            per_page=launch_options.per_page,
        )
    except CommandRunnerError:
        await message.edit_text(
            "⚠️ <b>Не получилось проверить выдачу HH</b>\n\n"
            "Проверьте авторизацию HH и попробуйте ещё раз.",
            reply_markup=automation_limit_keyboard(mode, ai_filter),
            parse_mode="HTML",
        )
        return

    launch_options = _apply_estimate_to_launch_options(launch_options, estimate)
    with suppress(SearchQueryHistoryServiceError):
        search_query_history_service.add_query(user.id, search_query)

    await state.update_data(
        automation_mode=mode,
        automation_ai_filter=ai_filter,
        automation_target_count=target_count,
        automation_search_query=search_query,
        automation_total_pages=launch_options.total_pages,
        automation_per_page=launch_options.per_page,
        automation_estimated_found=estimate.found,
        automation_estimated_available=estimate.available_count,
    )
    await message.edit_text(
        _format_automation_preview(
            launch_options=launch_options,
            estimate=estimate,
        ),
        reply_markup=automation_preview_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == AUTOMATION_CHANGE_QUERY_CALLBACK_DATA)
async def handle_automation_change_query_callback(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
    account_service: AccountService,
    search_query_history_service: SearchQueryHistoryService,
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
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Авто-отклик уже запущен.", show_alert=True)
        return

    data = await state.get_data()
    mode = str(data.get("automation_mode") or "plain")
    ai_filter = data.get("automation_ai_filter")
    await state.set_state(AutomationStates.waiting_for_search_query)
    history = search_query_history_service.get_queries(user.id, limit=5)
    await message.edit_text(
        _format_automation_search_prompt(mode, str(ai_filter) if ai_filter else None),
        reply_markup=automation_search_query_keyboard(history),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == AUTOMATION_CONFIRM_CALLBACK_DATA)
async def handle_automation_confirm_callback(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    auth_service: AuthService,
    account_service: AccountService,
    cover_letter_service: CoverLetterService,
    stats_service: AutomationStatsService,
    hh_ai_config_service: HhAiConfigService,
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
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Авто-отклик уже запущен.", show_alert=True)
        return

    data = await state.get_data()
    mode = str(data.get("automation_mode") or "plain")
    ai_filter = data.get("automation_ai_filter")
    search_query = _normalize_search_query(str(data.get("automation_search_query") or ""))
    raw_target_count = data.get("automation_target_count")
    try:
        target_count = int(raw_target_count)
        launch_options = AutomationLaunchOptions(
            target_count=target_count,
            total_pages=int(data.get("automation_total_pages") or 0),
            per_page=int(data.get("automation_per_page") or 0),
            ai_filter=str(ai_filter) if ai_filter else None,
            search_query=search_query,
            estimated_found=int(data.get("automation_estimated_found") or 0),
            estimated_available=int(data.get("automation_estimated_available") or 0),
        )
        if launch_options.total_pages <= 0 or launch_options.per_page <= 0:
            raise ValueError("Invalid automation limits")
    except (TypeError, ValueError):
        await callback.answer("Параметры запуска устарели. Начните запуск заново.", show_alert=True)
        return

    if mode == "ai" and not settings.ai.enabled:
        await callback.answer("AI выключен в настройках.", show_alert=True)
        return
    if not search_query:
        await callback.answer("Сначала задайте поисковый запрос.", show_alert=True)
        return

    await state.clear()
    await _start_automation(
        message,
        bot=bot,
        telegram_user_id=user.id,
        command_runner=command_runner,
        status_service=status_service,
        lock_service=lock_service,
        cover_letter_service=cover_letter_service,
        stats_service=stats_service,
        hh_ai_config_service=hh_ai_config_service,
        launch_options=launch_options,
        edit_existing=True,
    )
    await callback.answer("Запускаю авто-отклик...")


@router.callback_query(F.data == STATISTICS_CALLBACK_DATA)
async def handle_statistics_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    status_service: AppStatusService,
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

    include_current_session = status_service.get_status(user.id).is_running
    stats = await asyncio.to_thread(
        stats_service.get_period_stats,
        user.id,
        include_current_session=include_current_session,
    )
    await source_message.answer(
        stats_service.format_period_stats(stats),
        reply_markup=back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == AI_TEST_CALLBACK_DATA)
async def handle_ai_test_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    ai_client: AiClient,
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

    await callback.answer("Проверяю AI...")
    try:
        answer = await asyncio.to_thread(ai_client.chat, AI_TEST_PROMPT)
    except AiClientError as exc:
        await message.answer(_format_ai_error(exc), parse_mode="HTML")
        return

    await message.answer(
        f"🧠 <b>AI тест</b>\n\n{html.escape(answer)}",
        parse_mode="HTML",
    )


@router.callback_query(F.data == AI_DRY_RUN_CALLBACK_DATA)
async def handle_ai_dry_run_callback(
    callback: CallbackQuery,
    settings: Settings,
    status_service: AppStatusService,
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
    if not settings.ai.enabled:
        await callback.answer("AI выключен в настройках.", show_alert=True)
        return

    status = status_service.get_status(user.id)
    if status.blocks_start:
        await callback.answer("Сначала остановите авто-отклик.", show_alert=True)
        return

    source_message = await _delete_callback_message(callback)
    if not source_message:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    await source_message.answer(
        _format_ai_dry_run_mode_prompt(),
        reply_markup=ai_dry_run_mode_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    F.data.in_(
        {
            AI_DRY_RUN_LIGHT_CALLBACK_DATA,
            AI_DRY_RUN_HEAVY_CALLBACK_DATA,
        }
    )
)
async def handle_ai_dry_run_mode_callback(
    callback: CallbackQuery,
    settings: Settings,
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
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Сначала остановите авто-отклик.", show_alert=True)
        return

    ai_filter = str(callback.data).rsplit(":", 1)[-1]
    await message.edit_text(
        _format_ai_dry_run_limit_prompt_for_mode(ai_filter),
        reply_markup=ai_dry_run_limit_keyboard(ai_filter),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ai:dry_run:(light|heavy):(10|30|50|all)$"))
async def handle_ai_dry_run_limit_callback(
    callback: CallbackQuery,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    auth_service: AuthService,
    account_service: AccountService,
    account_cache_service: AccountCacheService,
    cover_letter_service: CoverLetterService,
    hh_ai_config_service: HhAiConfigService,
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
    if not settings.ai.enabled:
        await callback.answer("AI выключен в настройках.", show_alert=True)
        return

    parts = str(callback.data).split(":")
    try:
        ai_filter = parts[-2]
        target_count = (
            AI_DRY_RUN_ALL_TARGET
            if parts[-1] == "all"
            else int(parts[-1])
        )
    except (IndexError, ValueError):
        await callback.answer("Неизвестный режим AI-анализа.", show_alert=True)
        return

    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Сначала остановите авто-отклик.", show_alert=True)
        return
    if not lock_service.acquire_automation_lock(user.id):
        await callback.answer("Сценарий уже выполняется. Подождите немного.", show_alert=True)
        return

    search_query = (
        _get_ai_dry_run_search_query(user.id, account_cache_service)
        if target_count == AI_DRY_RUN_ALL_TARGET
        else None
    )
    if target_count == AI_DRY_RUN_ALL_TARGET and not search_query:
        with suppress(AccountServiceError):
            summary = await asyncio.to_thread(account_service.get_summary, user.id)
            account_cache_service.save_summary(user.id, summary)
            if summary.resumes:
                search_query = summary.resumes[0].title.strip() or None

    source_message = await _delete_callback_message(callback)
    if not source_message:
        lock_service.release_automation_lock(user.id)
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    status_message = await source_message.answer(
        "🧪 <b>AI-анализ запускается</b>",
        reply_markup=account_keyboard(is_running=True),
        parse_mode="HTML",
    )
    await _start_ai_dry_run_session(
        status_message=status_message,
        telegram_user_id=user.id,
        target_count=target_count,
        ai_filter=ai_filter,
        command_runner=command_runner,
        status_service=status_service,
        lock_service=lock_service,
        cover_letter_service=cover_letter_service,
        hh_ai_config_service=hh_ai_config_service,
        search_query=search_query,
    )
    await callback.answer("Запускаю AI-анализ...")


@router.callback_query(
    F.data.in_(
        {
            AI_DRY_RUN_APPROVED_CALLBACK_DATA,
            AI_DRY_RUN_REJECTED_CALLBACK_DATA,
            AI_DRY_RUN_ALL_CALLBACK_DATA,
        }
    )
)
async def handle_ai_dry_run_report_callback(
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
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    stats = _ai_dry_run_results_by_user_id.get(user.id)
    if not stats:
        await callback.answer("Последний AI-анализ уже недоступен.", show_alert=True)
        return

    report_type = str(callback.data).rsplit(":", 1)[-1]
    try:
        await message.edit_text(
            _format_ai_dry_run_vacancy_report(stats, report_type),
            reply_markup=ai_dry_run_result_keyboard(),
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await callback.answer()


@router.callback_query(F.data == AI_DRY_RUN_CLEAR_SKIPPED_CALLBACK_DATA)
async def handle_ai_dry_run_clear_skipped_callback(
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
    if not isinstance(message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not await _is_authorized_user(user.id, auth_service, account_service):
        await callback.answer("Сначала пройдите авторизацию.", show_alert=True)
        return

    await message.edit_text(
        "🧹 <b>Очистить AI-отклонённые?</b>\n\n"
        "Будет очищен список вакансий, которые AI ранее отклонил для этого профиля.\n\n"
        "После этого AI-анализ сможет снова проверять эти вакансии.",
        reply_markup=ai_dry_run_clear_confirm_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == SETTINGS_CALLBACK_DATA)
async def handle_settings_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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

    await message.edit_text(
        "⚙️ <b>Настройки</b>\n\n"
        "Здесь можно изменить сопроводительное письмо и очистить список вакансий, "
        "которые AI уже счёл неподходящими.",
        reply_markup=settings_keyboard(
            resume_bump_settings_service.get(user.id).label,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == RESUME_BUMP_CALLBACK_DATA)
async def handle_resume_bump_settings_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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

    resume_bump_settings = resume_bump_settings_service.get(user.id)
    await message.edit_text(
        "🔁 <b>Поднятие резюме</b>\n\n"
        f"Сейчас: <b>{html.escape(resume_bump_settings.label)}</b>\n\n"
        "Можно включить отдельный фоновый режим без авто-откликов.",
        reply_markup=resume_bump_settings_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    F.data.in_(
        {
            RESUME_BUMP_OFF_CALLBACK_DATA,
            RESUME_BUMP_4H_CALLBACK_DATA,
            RESUME_BUMP_5H_CALLBACK_DATA,
        }
    )
)
async def handle_resume_bump_setting_change_callback(
    callback: CallbackQuery,
    settings: Settings,
    command_runner: CommandRunner,
    auth_service: AuthService,
    account_service: AccountService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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

    try:
        if callback.data == RESUME_BUMP_OFF_CALLBACK_DATA:
            await _disable_resume_bump(
                user.id,
                command_runner,
                resume_bump_settings_service,
            )
            result_text = "Авто-поднятие резюме выключено."
        else:
            interval_hours = 4 if callback.data == RESUME_BUMP_4H_CALLBACK_DATA else 5
            resume_bump_settings = ResumeBumpSettings(interval_hours=interval_hours)
            await asyncio.to_thread(
                command_runner.start_resume_bump,
                user.id,
                interval_hours,
            )
            try:
                resume_bump_settings_service.save(user.id, resume_bump_settings)
            except ResumeBumpSettingsServiceError:
                await asyncio.to_thread(command_runner.stop_resume_bump, user.id)
                raise
            result_text = (
                "Авто-поднятие резюме включено. "
                f"Буду обновлять резюме каждые {interval_hours} часа."
            )
    except (CommandRunnerError, ResumeBumpSettingsServiceError):
        await callback.answer("Не получилось изменить авто-поднятие.", show_alert=True)
        return

    resume_bump_settings = resume_bump_settings_service.get(user.id)
    await message.edit_text(
        "⚙️ <b>Настройки</b>\n\n"
        f"{html.escape(result_text)}",
        reply_markup=settings_keyboard(resume_bump_settings.label),
        parse_mode="HTML",
    )
    await callback.answer(result_text)


@router.callback_query(F.data == AI_DRY_RUN_CLEAR_CONFIRM_NO_CALLBACK_DATA)
async def handle_ai_dry_run_clear_cancel_callback(
    callback: CallbackQuery,
    settings: Settings,
    auth_service: AuthService,
    account_service: AccountService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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

    await message.edit_text(
        "⚙️ <b>Настройки</b>\n\n"
        "Очистка AI-отклонённых отменена.",
        reply_markup=settings_keyboard(
            resume_bump_settings_service.get(user.id).label,
        ),
        parse_mode="HTML",
    )
    await callback.answer("Отменено.")


@router.callback_query(F.data == AI_DRY_RUN_CLEAR_CONFIRM_YES_CALLBACK_DATA)
async def handle_ai_dry_run_clear_confirm_callback(
    callback: CallbackQuery,
    settings: Settings,
    command_runner: CommandRunner,
    status_service: AppStatusService,
    lock_service: AutomationLockService,
    auth_service: AuthService,
    account_service: AccountService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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
    if status_service.get_status(user.id).blocks_start:
        await callback.answer("Сначала остановите текущий сценарий.", show_alert=True)
        return
    if not lock_service.acquire_automation_lock(user.id):
        await callback.answer("Сценарий уже выполняется. Подождите немного.", show_alert=True)
        return

    await message.edit_text("🧹 Очищаю AI-отклонённые вакансии...", parse_mode="HTML")
    try:
        output = await asyncio.to_thread(command_runner.clear_ai_rejected_vacancies, user.id)
    except CommandRunnerError as exc:
        details = str(exc).strip()
        details_text = (
            f"\n\n<pre>{html.escape(details[-1000:])}</pre>"
            if details
            else ""
        )
        await message.edit_text(
            "⚠️ <b>Не получилось очистить AI-отклонённые</b>\n\n"
            "Проверьте Docker и hh-applicant-tool."
            f"{details_text}",
            reply_markup=ai_dry_run_result_keyboard(),
            parse_mode="HTML",
        )
        return
    finally:
        lock_service.release_automation_lock(user.id)

    _ai_dry_run_results_by_user_id.pop(user.id, None)
    await message.edit_text(
        "✅ <b>AI-отклонённые очищены</b>\n\n"
        "Список AI-отклонённых вакансий очищен. "
        "Теперь можно запустить AI-анализ заново.",
        reply_markup=settings_keyboard(
            resume_bump_settings_service.get(user.id).label,
        ),
        parse_mode="HTML",
    )
    await callback.answer("Очищено.")


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


@router.message(F.text == AI_TEST_BUTTON_TEXT)
async def handle_ai_test_button(
    message: Message,
    settings: Settings,
    auth_service: AuthService,
    ai_client: AiClient,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return

    await message.answer("Проверяю AI...")
    try:
        answer = await asyncio.to_thread(ai_client.chat, AI_TEST_PROMPT)
    except AiClientError as exc:
        await message.answer(_format_ai_error(exc), parse_mode="HTML")
        return

    await message.answer(
        f"🧠 <b>AI тест</b>\n\n{html.escape(answer)}",
        parse_mode="HTML",
    )


@router.message(F.text == AI_DRY_RUN_BUTTON_TEXT)
async def handle_ai_dry_run_button(
    message: Message,
    settings: Settings,
    status_service: AppStatusService,
    auth_service: AuthService,
) -> None:
    if not _is_allowed(message, settings):
        await _deny_access(message)
        return

    if not await _ensure_authorized(message, auth_service):
        return
    if not message.from_user:
        return
    if not settings.ai.enabled:
        await message.answer("AI сейчас выключен в настройках.")
        return

    status = status_service.get_status(message.from_user.id)
    if status.blocks_start:
        await message.answer("Сначала остановите авто-отклик, потом можно запустить AI-анализ.")
        return

    await message.answer(
        _format_ai_dry_run_mode_prompt(),
        reply_markup=ai_dry_run_mode_keyboard(),
        parse_mode="HTML",
    )


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

    if message.from_user and message.from_user.id in _ai_dry_run_sessions_by_user_id:
        if not lock_service.acquire_automation_lock(message.from_user.id):
            await message.answer("AI-анализ уже меняет состояние. Подождите немного.")
            return
        try:
            await _stop_ai_dry_run_session(
                telegram_user_id=message.from_user.id,
                command_runner=command_runner,
                status_service=status_service,
            )
        except CommandRunnerError:
            status_service.mark_failed(message.from_user.id)
            await message.answer("⚠️ Не получилось остановить AI-анализ.")
        finally:
            lock_service.release_automation_lock(message.from_user.id)
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

    if user.id in _ai_dry_run_sessions_by_user_id:
        if not lock_service.acquire_automation_lock(user.id):
            await callback.answer("AI-анализ уже меняет состояние.", show_alert=True)
            return
        try:
            await _stop_ai_dry_run_session(
                telegram_user_id=user.id,
                command_runner=command_runner,
                status_service=status_service,
            )
        except CommandRunnerError:
            status_service.mark_failed(user.id)
            await callback.answer("Не получилось остановить AI-анализ.", show_alert=True)
            return
        finally:
            lock_service.release_automation_lock(user.id)

        await callback.answer("AI-анализ остановлен.")
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
    account_cache_service: AccountCacheService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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
        await _disable_resume_bump(
            message.from_user.id,
            command_runner,
            resume_bump_settings_service,
        )
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
    except (CommandRunnerError, ResumeBumpSettingsServiceError):
        await message.answer(
            "⚠️ <b>Не получилось остановить авто-поднятие резюме перед выходом</b>\n\n"
            "Попробуйте ещё раз чуть позже.",
            reply_markup=account_keyboard(
                status_service.get_status(message.from_user.id).shows_stop_button
            ),
            parse_mode="HTML",
        )
        return

    if message.from_user:
        auth_service.forget_authorized(message.from_user.id)
        with suppress(AccountCacheServiceError):
            account_cache_service.clear(message.from_user.id)
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
    account_cache_service: AccountCacheService,
    resume_bump_settings_service: ResumeBumpSettingsService,
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
        await _disable_resume_bump(
            user.id,
            command_runner,
            resume_bump_settings_service,
        )
        account_service.logout(user.id)
    except AccountServiceError:
        await callback.answer("Не получилось выйти из аккаунта HH.", show_alert=True)
        return

    except (CommandRunnerError, ResumeBumpSettingsServiceError):
        await callback.answer("Не получилось остановить авто-поднятие резюме.", show_alert=True)
        return

    auth_service.forget_authorized(user.id)
    with suppress(AccountCacheServiceError):
        account_cache_service.clear(user.id)
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
    ai_client = AiClient(settings.ai)
    hh_ai_config_service = HhAiConfigService(settings.hh_tool_workdir, settings.ai)
    resume_bump_settings_service = ResumeBumpSettingsService(settings.hh_tool_workdir)
    search_query_history_service = SearchQueryHistoryService(settings.hh_tool_workdir)

    for telegram_user_id in settings.telegram_allowed_user_ids:
        try:
            if account_service.is_authorized(telegram_user_id):
                await _ensure_resume_bump_running(
                    telegram_user_id,
                    command_runner,
                    resume_bump_settings_service,
                )
        except (AccountServiceError, CommandRunnerError):
            logging.warning(
                "Failed to ensure resume bump container for allowed user %s",
                telegram_user_id,
            )

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
        ai_client=ai_client,
        hh_ai_config_service=hh_ai_config_service,
        resume_bump_settings_service=resume_bump_settings_service,
        search_query_history_service=search_query_history_service,
    )


if __name__ == "__main__":
    asyncio.run(main())
