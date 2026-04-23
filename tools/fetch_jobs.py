"""Получает вакансии из Trudvsem Open Data API и нормализует их в объекты `Job`."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

from config import (
    API_TIMEOUT,
    JOBS_DATA_PATH,
    LIVE_API_ENABLED,
    TRUDVSEM_API_BASE,
    TRUDVSEM_LIMIT,
    TRUDVSEM_PAGE_SIZE,
)
from constants.jobs import CANONICAL_TAGS, TECH_TAGS
from constants.ranking import MIDDLE_MARKERS, SENIORISH_TITLE_MARKERS
from models import Job

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

# Количество вакансий, реально полученных из live API при последнем вызове `fetch_jobs`.
# None  — API отключён через `LIVE_API_ENABLED=0`.
# 0     — API вернул пустой ответ, поэтому использовался локальный кэш.
_last_live_count: int | None = None


def get_last_live_count() -> int | None:
    """Возвращает число вакансий из live API при последнем вызове `fetch_jobs`."""
    return _last_live_count


def fetch_jobs(query: str, limit: int = TRUDVSEM_LIMIT) -> list[Job]:
    """
    Получает вакансии по `query` из API Trudvsem.

    Если сеть недоступна, переключается на встроенный snapshot `data/jobs.json`,
    чтобы демо оставалось воспроизводимым офлайн.

    Побочный эффект: обновляет `_last_live_count`, чтобы отражать количество
    результатов, пришедших из live API (`None`, если `LIVE_API_ENABLED=0`).
    """
    global _last_live_count

    if LIVE_API_ENABLED:
        try:
            jobs = _fetch_from_api(query=query, limit=limit)
            _last_live_count = len(jobs)
            if jobs:
                return jobs
            print("  [Работа России] API вернул 0 вакансий. Загружаю локальный snapshot.")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
            print(f"  [Работа России] API недоступен: {exc}. Загружаю локальный кэш.")
            _last_live_count = 0
    else:
        _last_live_count = None

    return _load_local_cache()


def _fetch_from_api(query: str, limit: int) -> list[Job]:
    collected_at = date.today().isoformat()
    page_size = max(1, min(TRUDVSEM_PAGE_SIZE, limit, 3))
    raw_items: list[dict] = []
    seen_ids: set[str] = set()

    for offset in range(0, max(1, limit), page_size):
        try:
            data = _fetch_page(query=query, limit=page_size, offset=offset)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError):
            if raw_items:
                print(
                    "  [Работа России] API отдал только часть страниц; "
                    f"использую {len(raw_items)} live-вакансий."
                )
                break
            raise

        page_items = data.get("results", {}).get("vacancies", [])
        if not page_items:
            break

        for item in page_items:
            vacancy = item.get("vacancy", {})
            vacancy_id = str(vacancy.get("id") or "")
            if vacancy_id and vacancy_id in seen_ids:
                continue
            if vacancy_id:
                seen_ids.add(vacancy_id)
            raw_items.append(item)

        if len(page_items) < page_size or len(raw_items) >= limit:
            break

    raw_items = raw_items[:limit]
    if not raw_items:
        return []

    combined_data = {"results": {"vacancies": raw_items}}
    _save_raw(data=combined_data, query=query, collected_at=collected_at)
    vacancies = [item.get("vacancy", {}) for item in raw_items]
    return [
        job for item in vacancies
        if (job := normalize_trudvsem_vacancy(item, collected_at=collected_at))
    ]


def _fetch_page(query: str, limit: int, offset: int) -> dict:
    url = _build_url(query=query, limit=limit, offset=offset)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "JobMatchAgent/2.0 (educational project)",
            "Accept": "application/json",
            "Connection": "close",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_url(query: str, limit: int, offset: int = 0) -> str:
    # Убираем одиночные суррогаты, которые могут появляться при surrogateescape
    # в не-UTF-8 терминалах: `urlencode` падает на таких символах.
    safe_query = query.encode("utf-8", errors="replace").decode("utf-8")
    params = {
        "text": safe_query,
        "limit": max(1, min(limit, 100)),
        "offset": max(0, offset),
    }
    return f"{TRUDVSEM_API_BASE}/vacancies?{urllib.parse.urlencode(params)}"


def normalize_trudvsem_vacancy(item: dict, collected_at: str) -> Job | None:
    """Нормализует один raw-словарь вакансии Trudvsem во внутренний dataclass `Job`."""
    title = (item.get("job-name") or "").strip()
    if not title:
        return None

    company     = item.get("company") or {}
    region      = item.get("region") or {}
    requirement = item.get("requirement") or {}
    employment  = (item.get("employment") or "").strip()
    schedule    = (item.get("schedule") or "").strip()

    requirements = _clean_text(item.get("requirements") or "")
    duty         = _clean_text(item.get("duty") or "")
    description  = " ".join(part for part in [requirements, duty] if part)

    location    = (region.get("name") or "Россия").strip()
    work_format = _work_format(employment, schedule, description)
    if work_format == "remote" and "удал" not in location.lower():
        location = f"{location} (удалённо)"
    elif work_format == "hybrid" and "гибрид" not in location.lower():
        location = f"{location} (гибрид)"

    text_for_tags = " ".join([
        title,
        description,
        " ".join(item.get("skills") or []),
        item.get("qualification") or "",
    ])

    return Job(
        id=f"trudvsem_{item.get('id', '')}",
        title=title,
        company=(company.get("name") or "Неизвестно").strip(),
        location=location,
        type=_infer_type(title, employment, schedule, description),
        tags=_extract_tags(text_for_tags),
        description=description,
        posted_at=(item.get("creation-date") or item.get("date_modify") or "")[:10],
        salary_range=_format_salary(item),
        source="trudvsem.ru",
        url=item.get("vac_url") or "",
        collected_at=collected_at[:10],
        experience_years=_infer_experience_years(
            requirement.get("experience"),
            f"{title} {description}",
        ),
    )


def _infer_type(title: str, employment: str, schedule: str, description: str) -> str:
    title_scope = " ".join([title, employment, schedule]).lower()
    haystack    = " ".join([title_scope, description]).lower()

    if "частичная" in haystack or "непол" in haystack:
        return "part-time"
    if "полная" in haystack or "полный рабочий день" in haystack or "удал" in haystack:
        return "full-time"
    return "unknown"


def _work_format(employment: str, schedule: str, description: str) -> str | None:
    text = f"{employment} {schedule} {description}".lower()
    if "гибрид" in text or re.search(r"\d+\s*дн[яе][^.;]{0,40}удал", text):
        return "hybrid"
    if "удал" in text or "remote" in text:
        return "remote"
    return None


def _format_salary(item: dict) -> str | None:
    salary = item.get("salary")
    if salary:
        salary_text = str(salary).strip()
        if salary_text.lower() in {"0", "от 0", "до 0", "0 руб.", "от 0 руб.", "до 0 руб."}:
            return None
        return salary_text

    sal_min  = _to_int(item.get("salary_min"))
    sal_max  = _to_int(item.get("salary_max"))
    currency = str(item.get("currency") or "руб.").replace("«", "").replace("»", "")

    if sal_min and sal_max:
        return f"{sal_min:,}–{sal_max:,} {currency}".replace(",", " ")
    if sal_min:
        return f"от {sal_min:,} {currency}".replace(",", " ")
    if sal_max:
        return f"до {sal_max:,} {currency}".replace(",", " ")
    return None


def _extract_tags(text: str) -> list[str]:
    text_lower = text.lower().replace("питон", "python")
    found: list[str] = []
    for tag in sorted(TECH_TAGS, key=len, reverse=True):
        if tag in text_lower and tag not in found:
            found.append(_canonical_tag(tag))
    return list(dict.fromkeys(found))[:12]


def _canonical_tag(tag: str) -> str:
    return CANONICAL_TAGS.get(tag, tag)


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _to_int(value) -> int | None:
    try:
        return None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None


def _infer_experience_years(value, text: str) -> int | None:
    explicit   = _to_int(value)
    text_lower = text.lower()

    patterns = [
        r"от\s+(\d+)\s*(?:лет|года|год)",
        r"(\d+)\s*[–-]\s*\d+\s*(?:лет|года|год)",
        r"(\d+)\+\s*(?:лет|года|год)",
        r"(\d+)\s*(?:лет|года|год)\s+(?:опыта|коммерческой|разработки|работы)",
    ]
    inferred: list[int] = []
    for pattern in patterns:
        inferred.extend(int(m) for m in re.findall(pattern, text_lower))

    if inferred:
        return max([explicit or 0, min(inferred)])
    return explicit


def _is_seniorish_title(title: str) -> bool:
    title_lower = title.lower()
    markers = SENIORISH_TITLE_MARKERS + MIDDLE_MARKERS
    return any(word in title_lower for word in markers)


def _save_raw(data: dict, query: str, collected_at: str) -> None:
    """Сохраняет очищенный snapshot API для аудита и воспроизводимости Track C."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "source":       "trudvsem.ru",
        "api_endpoint": f"{TRUDVSEM_API_BASE}/vacancies",
        "query":        query,
        "collected_at": datetime.now().isoformat(),
        "count":        len(data.get("results", {}).get("vacancies", [])),
        "data_note":    "Public open-data response; contact fields removed before saving.",
        "results": {
            "vacancies": [
                {"vacancy": _sanitize_vacancy(item.get("vacancy", {}))}
                for item in data.get("results", {}).get("vacancies", [])
            ]
        },
    }
    path = RAW_DIR / f"trudvsem_latest_{collected_at}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def _sanitize_vacancy(vacancy: dict) -> dict:
    """Удаляет персональные контактные поля перед записью на диск."""
    cleaned = dict(vacancy)
    cleaned.pop("contact_list", None)
    cleaned.pop("contact_person", None)
    company = dict(cleaned.get("company") or {})
    company.pop("email", None)
    cleaned["company"] = company
    return cleaned


def _load_local_cache() -> list[Job]:
    if not JOBS_DATA_PATH.exists():
        return []
    with open(JOBS_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return [
        Job(
            id=item["id"],
            title=item["title"],
            company=item["company"],
            location=item["location"],
            type=item["type"],
            tags=[t.lower() for t in item.get("tags", [])],
            description=item.get("description", ""),
            posted_at=item.get("posted_at", ""),
            salary_range=item.get("salary_range"),
            source=item.get("source", "cache"),
            url=item.get("url", ""),
            collected_at=item.get("collected_at", ""),
            experience_years=item.get("experience_years"),
        )
        for item in raw
    ]
