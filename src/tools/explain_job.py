"""Генерирует объяснение для каждой вакансии: почему результат подходит запросу."""

import re

from ..constants.display import TYPE_LABELS_FULL
from ..constants.ranking import (
    INTERNSHIP_MARKERS,
    JUNIOR_MARKERS,
    MIDDLE_MARKERS,
    SENIORISH_TITLE_MARKERS,
)
from ..constants.prompts import EXPLAIN_SYSTEM_PROMPT, EXPLAIN_USER_TEMPLATE
from ..llm_client import LLMError, chat_completion, llm_available
from ..models import RankedJob, UserQuery


def explain_top_jobs(ranked_jobs: list[RankedJob], query: UserQuery) -> list[str]:
    """
    Возвращает по одному объяснению на каждую вакансию из `ranked_jobs`.

    При доступном Groq делегирует генерацию модели, иначе использует шаблонный
    fallback. Длина возвращаемого списка всегда равна длине `ranked_jobs`.
    """
    if not ranked_jobs:
        return []

    if llm_available():
        try:
            return _explain_via_groq(ranked_jobs, query)
        except LLMError as exc:
            print(f"  [Groq] explain_top_jobs: {exc}. Используется шаблон.")

    return [_explain_template(rj, query) for rj in ranked_jobs]


def _explain_via_groq(ranked_jobs: list[RankedJob], query: UserQuery) -> list[str]:
    jobs_text = "\n\n".join(
        f"#{i + 1}. {rj.job.title} — {rj.job.company}\n"
        f"   Занятость: {rj.job.type} | Место: {rj.job.location}\n"
        f"   Опыт: {rj.job.experience_years if rj.job.experience_years is not None else 'не указан'}\n"
        f"   Навыки: {', '.join(rj.job.tags) or '—'}\n"
        f"   Score breakdown: {rj.score_breakdown}\n"
        f"   Описание: {rj.job.description[:400]}"
        for i, rj in enumerate(ranked_jobs)
    )

    prompt = EXPLAIN_USER_TEMPLATE.format(
        raw_query=query.raw,
        keywords=", ".join(query.keywords) or "не указаны",
        jobs_text=jobs_text,
    )

    content = chat_completion(
        [
            {
                "role": "system",
                "content": EXPLAIN_SYSTEM_PROMPT,
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=900,
    )

    return _parse_numbered(content, len(ranked_jobs), ranked_jobs, query)


def _parse_numbered(
    content: str,
    n: int,
    ranked_jobs: list[RankedJob],
    query: UserQuery,
) -> list[str]:
    """Извлекает секции вида `#1: … #2: …` из `content`, а при пропусках использует шаблоны."""
    results: list[str] = []
    for i in range(n):
        end_marker = f"#{i + 2}:" if i + 1 < n else None
        start = content.find(f"#{i + 1}:")
        if start == -1:
            results.append(_explain_template(ranked_jobs[i], query))
            continue
        start += len(f"#{i + 1}:")
        end = content.find(end_marker, start) if end_marker else len(content)
        results.append(content[start:end].strip())
    return results


def _explain_template(ranked: RankedJob, query: UserQuery) -> str:
    """Строит rule-based объяснение на основе полей вакансии и результатов скоринга."""
    j = ranked.job
    parts: list[str] = []

    matched = ranked.matched_keywords
    if matched:
        if len(matched) == 1:
            parts.append(f"Совпадает навык: {matched[0]}.")
        elif len(matched) == 2:
            parts.append(f"Совпадают навыки: {matched[0]} и {matched[1]}.")
        else:
            skills = ", ".join(matched[:-1]) + f" и {matched[-1]}"
            parts.append(f"Сильное совпадение по навыкам: {skills}.")
    else:
        parts.append("Широкое совпадение по роли и локации.")

    if query.preferred_type:
        if j.type == query.preferred_type:
            type_ru = TYPE_LABELS_FULL.get(j.type, j.type).lower()
            parts.append(f"Занятость совпадает: {type_ru}.")
        else:
            parts.append(f"Занятость: {j.type} — проверьте соответствие.")

    if query.seniority:
        title_lower = j.title.lower()
        is_internship = j.type == "internship" or any(w in title_lower for w in INTERNSHIP_MARKERS)
        is_junior = any(w in title_lower for w in JUNIOR_MARKERS)
        if query.seniority == "internship" and is_internship:
            parts.append("Уровень совпадает: стажировка.")
        elif query.seniority == "junior" and (is_junior or is_internship):
            parts.append("Уровень подходит для junior-кандидата.")

    if query.preferred_location:
        wanted   = query.preferred_location.lower()
        location = j.location.lower()
        if wanted in location or (wanted == "remote" and "удал" in location):
            parts.append(f"Локация: {j.location} — как в запросе.")
        elif wanted == "remote" and "гибрид" in location:
            parts.append(f"Локация: {j.location} — частично соответствует удалённому формату.")
        else:
            parts.append(f"Локация: {j.location}.")

    if query.seniority in {"internship", "junior"}:
        title_lower = j.title.lower()
        if any(w in title_lower for w in SENIORISH_TITLE_MARKERS):
            parts.append("Риск: в названии явно senior/lead-уровень, для стартового уровня это слабое совпадение.")
        elif any(w in title_lower for w in MIDDLE_MARKERS):
            parts.append("Риск: в названии middle-уровень, это может быть выше стартового уровня.")
        elif j.experience_years is None:
            parts.append("Требуемый опыт в данных не указан — стоит проверить карточку.")
        elif j.experience_years <= 1:
            parts.append(f"Требуемый опыт {j.experience_years} год(а) подходит для стартового уровня.")
        elif j.experience_years <= 3:
            if query.seniority == "internship":
                parts.append(f"Опыт {j.experience_years} год(а) может быть выше обычной стажировки.")
            else:
                parts.append(f"Опыт {j.experience_years} год(а) может быть верхней границей для junior.")
        else:
            parts.append(f"Риск: указан опыт {j.experience_years} лет, это может быть не стартовый уровень.")

    return " ".join(parts)
