"""
Объяснимое rule-based ранжирование вакансий.

Каждая вакансия получает взвешенный score по пяти сигналам из `config.WEIGHTS`:

  keyword_overlap  — доля запрошенных навыков, найденных в тексте вакансии
  role_alignment   — насколько роль вакансии совпадает с ролью из запроса
  type_match       — занятость: полная или частичная
  location_match   — город или удалённый формат
  junior_fit       — соответствие уровню internship или junior

LLM не требуется: вся логика скоринга детерминирована и проверяема.
"""

import re

from ..config import WEIGHTS
from ..constants.ranking import (
    INTERNSHIP_MARKERS,
    JUNIOR_MARKERS,
    MIDDLE_MARKERS,
    ROLE_ALIASES,
    SENIORISH_TITLE_MARKERS,
)
from ..models import Job, RankedJob, UserQuery


def filter_and_rank_jobs(jobs: list[Job], query: UserQuery) -> list[RankedJob]:
    """Считает score для каждой вакансии относительно `query`, отбрасывает нули и возвращает ранжированный список."""
    ranked = [_score(job, query) for job in jobs]
    ranked = [r for r in ranked if r.score > 0]
    ranked.sort(
        key=lambda r: (
            r.score,
            r.score_breakdown.get("quality_signal", 0.0),
            r.score_breakdown.get("junior_fit", 0.0),
            r.score_breakdown.get("keyword_overlap", 0.0),
            r.job.posted_at,
        ),
        reverse=True,
    )
    return _diversify_companies(_dedupe_ranked(ranked))


def _score(job: Job, query: UserQuery) -> RankedJob:
    searchable_text   = " ".join([job.title, job.description, " ".join(job.tags)]).lower()
    searchable_tokens = set(job.tags) | _tokenize(job.title) | _tokenize(job.description)
    matched = [
        kw for kw in query.keywords
        if kw in searchable_tokens or kw in searchable_text
    ]
    kw_score = len(matched) / len(query.keywords) if query.keywords else 0.0

    # Жёсткий фильтр: в запросе явно указаны навыки, но ни один не совпал.
    if query.keywords and not matched:
        return RankedJob(
            job=job, score=0.0, matched_keywords=[],
            score_breakdown={k: 0.0 for k in ("keyword_overlap", "type_match", "location_match", "junior_fit", "role_alignment")},
        )

    type_score     = (1.0 if job.type == query.preferred_type else 0.0) if query.preferred_type else 0.5
    loc_score      = _location_score(job, query.preferred_location) if query.preferred_location else 0.5
    junior_score   = _junior_fit_score(job, query)
    role_score     = _role_alignment_score(job, query)
    quality_signal = _quality_signal(job)

    # Жёсткий фильтр: senior/lead-вакансия для запроса internship/junior.
    if _wants_junior(query) and _is_seniorish_title(job.title.lower()):
        return RankedJob(
            job=job, score=0.0, matched_keywords=matched,
            score_breakdown={
                "keyword_overlap": round(kw_score, 3),
                "type_match":      round(type_score, 3),
                "location_match":  round(loc_score, 3),
                "junior_fit":      round(junior_score, 3),
                "role_alignment":  round(role_score, 3),
                "quality_signal":  round(quality_signal, 3),
            },
        )

    # Жёсткий фильтр: запрос нацелен на конкретную роль, но вакансия ей не соответствует.
    if _has_role_intent(query) and role_score < 0.35:
        return RankedJob(
            job=job, score=0.0, matched_keywords=matched,
            score_breakdown={
                "keyword_overlap": round(kw_score, 3),
                "type_match":      round(type_score, 3),
                "location_match":  round(loc_score, 3),
                "junior_fit":      round(junior_score, 3),
                "role_alignment":  round(role_score, 3),
                "quality_signal":  round(quality_signal, 3),
            },
        )

    breakdown = {
        "keyword_overlap": round(kw_score, 3),
        "type_match":      round(type_score, 3),
        "location_match":  round(loc_score, 3),
        "junior_fit":      round(junior_score, 3),
        "role_alignment":  round(role_score, 3),
        "quality_signal":  round(quality_signal, 3),
    }

    base_total = (
        WEIGHTS["keyword_overlap"]  * kw_score
        + WEIGHTS["type_match"]     * type_score
        + WEIGHTS["location_match"] * loc_score
        + WEIGHTS["junior_fit"]     * junior_score
        + WEIGHTS["role_alignment"] * role_score
    )
    # Небольшая калибровка: более полные и качественные карточки ранжируются
    # чуть выше разреженных, не искажая объяснимые веса сигналов.
    calibration = 0.94 + 0.06 * quality_signal
    total = min(1.0, base_total * calibration)

    return RankedJob(job=job, score=round(total, 3), matched_keywords=matched, score_breakdown=breakdown)


def _location_score(job: Job, preferred_location: str) -> float:
    wanted   = preferred_location.lower()
    location = job.location.lower()
    if wanted == "remote":
        if "удал" in location or "remote" in location:
            return 1.0
        if "гибрид" in location:
            return 0.7
        return 0.0
    return 1.0 if wanted in location else 0.0


def _junior_fit_score(job: Job, query: UserQuery) -> float:
    title       = job.title.lower()
    level = query.seniority

    if level not in {"internship", "junior"}:
        if _is_seniorish_title(title):        return 0.2
        if _has_middle_marker(title):         return 0.35
        return 0.5

    if _is_seniorish_title(title):            return 0.0
    if _has_middle_marker(title):             return 0.15

    is_internship_job = _is_internship_job(job)
    if level == "internship":
        if is_internship_job:
            return 1.0
        if _has_junior_marker(title):
            return 0.55
        if job.experience_years is None:
            return 0.45
        if job.experience_years <= 1:
            return 0.5
        return 0.0

    if is_internship_job:
        return 1.0
    if _has_junior_marker(title):             return 0.95
    if job.experience_years is None:          return 0.65
    if job.experience_years <= 1:             return 0.9
    if job.experience_years <= 3:             return 0.45
    return 0.0


def _wants_junior(query: UserQuery) -> bool:
    return query.seniority in {"internship", "junior"}


def _is_internship_job(job: Job) -> bool:
    text = " ".join([job.title, job.description]).lower()
    return job.type == "internship" or any(w in text for w in INTERNSHIP_MARKERS)


def _role_alignment_score(job: Job, query: UserQuery) -> float:
    role_keywords = [kw for kw in query.keywords if kw in ROLE_ALIASES]
    if not role_keywords:
        return 1.0

    title       = job.title.lower()
    tags        = " ".join(job.tags).lower()
    description = job.description.lower()
    scores: list[float] = []
    for role in role_keywords:
        aliases = ROLE_ALIASES[role]
        if   any(a in title       for a in aliases): scores.append(1.0)
        elif any(a in tags        for a in aliases): scores.append(0.65)
        elif any(a in description for a in aliases): scores.append(0.2)
        else:                                        scores.append(0.0)
    return sum(scores) / len(scores)


def _has_role_intent(query: UserQuery) -> bool:
    return any(kw in ROLE_ALIASES for kw in query.keywords)


def _dedupe_ranked(ranked: list[RankedJob]) -> list[RankedJob]:
    """Удаляет дубликаты с одинаковым ключом `(title, company, location)`."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[RankedJob] = []
    for item in ranked:
        key = (
            _normalize_key(item.job.title),
            _normalize_key(item.job.company),
            _normalize_key(item.job.location),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _diversify_companies(ranked: list[RankedJob], max_per_company: int = 2) -> list[RankedJob]:
    """
    Ограничивает количество вакансий одного работодателя в верхней части выдачи.

    Лишние позиции не удаляются, а переносятся в конец списка, чтобы они всё
    ещё были доступны, если вызывающая сторона запросит больше результатов.
    """
    company_counts: dict[str, int] = {}
    first_pass: list[RankedJob] = []
    overflow:   list[RankedJob] = []

    for item in ranked:
        key = _normalize_company(item.job.company)
        if company_counts.get(key, 0) < max_per_company:
            first_pass.append(item)
            company_counts[key] = company_counts.get(key, 0) + 1
        else:
            overflow.append(item)

    return first_pass + overflow


def _normalize_company(value: str) -> str:
    value = _normalize_key(value)
    value = re.sub(r"\b(пао|ао|ооо|зао|ип)\b", "", value)
    return _normalize_key(value.replace('"', "").replace("'", ""))


def _normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _is_seniorish_title(title: str) -> bool:
    return any(word in title for word in SENIORISH_TITLE_MARKERS)


def _has_middle_marker(title: str) -> bool:
    return any(word in title for word in MIDDLE_MARKERS)


def _has_junior_marker(title: str) -> bool:
    return any(word in title for word in JUNIOR_MARKERS)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zа-яё0-9#+.]+", text.lower()))


def _quality_signal(job: Job) -> float:
    """
    Вычисляет оценку качества вакансии в диапазоне `[0, 1]` по полноте карточки.

    Используется только для лёгкой калибровки: не меняет объяснимые веса
    breakdown-сигналов, а лишь помогает развязывать равные score в пользу более
    полных карточек.
    """
    description_len = len((job.description or "").strip())
    richness = min(description_len / 700, 1.0)

    salary = (job.salary_range or "").lower()
    has_salary = bool(salary and "от 0" not in salary and "до 0" not in salary and salary != "0")

    return (
        0.45 * richness
        + 0.25 * (1.0 if has_salary else 0.0)
        + 0.15 * (1.0 if job.experience_years is not None else 0.6)
        + 0.15 * (1.0 if job.url else 0.0)
    )
