from dataclasses import dataclass, field
import re


AI_DRY_RUN_ALL_TARGET = 0

AI_DRY_RUN_LIMITS: dict[int, tuple[int, int]] = {
    AI_DRY_RUN_ALL_TARGET: (20, 100),
    10: (2, 100),
    30: (4, 100),
    50: (6, 100),
}


@dataclass(frozen=True)
class AiDryRunLaunchOptions:
    target_count: int
    total_pages: int
    per_page: int
    ai_filter: str = "light"
    search_query: str | None = None


@dataclass(frozen=True)
class AiDryRunStats:
    target_count: int
    ai_filter: str = "light"
    checked_count: int = 0
    rejected_count: int = 0
    suitable_count: int = 0
    already_rejected_count: int = 0
    current_resume: str = ""
    is_finished: bool = False
    events: tuple[str, ...] = field(default_factory=tuple)
    approved_urls: tuple[str, ...] = field(default_factory=tuple)
    rejected_urls: tuple[str, ...] = field(default_factory=tuple)
    already_rejected_urls: tuple[str, ...] = field(default_factory=tuple)


def get_ai_dry_run_launch_options(
    target_count: int,
    ai_filter: str = "light",
    search_query: str | None = None,
) -> AiDryRunLaunchOptions:
    if ai_filter not in {"light", "heavy"}:
        raise ValueError("Unsupported AI dry-run filter")

    try:
        total_pages, per_page = AI_DRY_RUN_LIMITS[target_count]
    except KeyError as exc:
        raise ValueError("Unsupported AI dry-run target") from exc

    return AiDryRunLaunchOptions(
        target_count=target_count,
        total_pages=total_pages,
        per_page=per_page,
        ai_filter=ai_filter,
        search_query=search_query,
    )


def parse_ai_dry_run_logs(
    logs: str,
    *,
    target_count: int,
    ai_filter: str = "light",
) -> AiDryRunStats:
    answer_count = 0
    rejected_count = 0
    already_rejected_count = 0
    current_resume = ""
    is_finished = False
    events: list[str] = []
    approved_urls: list[str] = []
    rejected_urls: list[str] = []
    already_rejected_urls: list[str] = []

    for raw_line in logs.splitlines():
        line = _clean_log_line(raw_line)
        if not line:
            continue

        if "AI (light) ответ" in line or "AI (heavy) ответ" in line:
            answer_count += 1
            continue

        if "AI (light) посчитал неподходящей" in line or "AI (heavy) посчитал неподходящей" in line:
            rejected_count += 1
            if url := _extract_hh_vacancy_url(line):
                rejected_urls.append(url)
            events.append(line)
            continue

        if "Вакансия уже отклонена ранее" in line:
            already_rejected_count += 1
            if url := _extract_hh_vacancy_url(line):
                already_rejected_urls.append(url)
            events.append(line)
            continue

        if (
            "Пробуем откликнуться на вакансию:" in line
            or "Отправили отклик на вакансию" in line
        ):
            if url := _extract_hh_vacancy_url(line):
                approved_urls.append(url)
            continue

        if "Начинаю рассылку откликов для резюме:" in line:
            current_resume = line.split(":", 1)[-1].strip()
            events.append(line)
            continue

        if "Закончили рассылку для резюме:" in line:
            is_finished = True
            events.append(line)
            continue

        if "Отклики на вакансии разосланы" in line:
            is_finished = True
            continue

    approved_urls = _unique_in_order(approved_urls)
    rejected_urls = _unique_in_order(rejected_urls)
    already_rejected_urls = _unique_in_order(already_rejected_urls)
    checked_count = max(answer_count, len(approved_urls) + rejected_count)
    suitable_count = max(len(approved_urls), checked_count - rejected_count)
    return AiDryRunStats(
        target_count=target_count,
        ai_filter=ai_filter,
        checked_count=checked_count,
        rejected_count=rejected_count,
        suitable_count=suitable_count,
        already_rejected_count=already_rejected_count,
        current_resume=current_resume,
        is_finished=is_finished,
        events=tuple(events[-8:]),
        approved_urls=tuple(approved_urls),
        rejected_urls=tuple(rejected_urls),
        already_rejected_urls=tuple(already_rejected_urls),
    )


def _clean_log_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("time="):
        return ""
    if stripped.startswith("Container "):
        return ""
    if stripped.startswith("hh_applicant_tool_"):
        return ""
    if stripped.startswith("[D] AI запрос:"):
        return ""
    if "AI системный промпт" in stripped:
        return ""

    for prefix in ("[D] ", "[I] ", "[W] ", "[E] "):
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()

    return stripped


def _extract_hh_vacancy_url(line: str) -> str | None:
    match = re.search(r"https://hh\.ru/vacancy/\d+", line)
    return match.group(0) if match else None


def _unique_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
