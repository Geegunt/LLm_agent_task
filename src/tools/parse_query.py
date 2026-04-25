"""
Преобразует свободный текст запроса о вакансиях в структурированный `UserQuery`.

Два режима работы:
  - Groq Function Calling: если задан `GROQ_API_KEY`, LLM вызывает
    `extract_job_search_params` по строгой JSON-схеме.
  - Резервный rule-based режим: словарный разбор русских и транслитерированных терминов.
"""

from __future__ import annotations

import re

from ..constants.parsing import (
    AMBIGUOUS_INTERNSHIP_SIGNALS,
    AMBIGUOUS_WORK_SIGNALS,
    LOCATION_SIGNALS,
    SENIORITY_SIGNALS,
    SKILL_ALIASES,
    TYPE_SIGNALS,
)
from ..constants.prompts import PARSE_QUERY_SYSTEM_PROMPT, PARSE_QUERY_TOOL, PARSE_QUERY_USER_TEMPLATE
from ..llm_client import LLMError, llm_available, tool_call_completion
from ..models import UserQuery


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def _has_ambiguous_seniority(raw: str) -> bool:
    """
    Возвращает `True`, если пользователь перечислил несколько уровней через «или».

    Например, запрос «стажировку или работу джуном» должен приводить к
    `seniority=None`, чтобы скорер не штрафовал половину результатов.
    """
    text = raw.lower()
    if not ("или" in text or " or " in text or "/" in text):
        return False
    return (
        any(s in text for s in AMBIGUOUS_INTERNSHIP_SIGNALS)
        and any(s in text for s in AMBIGUOUS_WORK_SIGNALS)
    )


def _build_source_query(raw: str, keywords: list[str], seniority: str | None) -> str:
    parts: list[str] = []
    if seniority == "internship":
        parts.append("стажировка")
    elif seniority == "junior":
        parts.append("разработчик")
    parts.extend(_unique(keywords)[:3])
    return " ".join(parts) if parts else raw


def _is_additive_refinement(raw: str) -> bool:
    """Понимает, что пользователь хочет добавить навык к прошлому запросу, а не заменить его."""
    text = raw.lower()
    return any(marker in text for marker in ("добавь", "добавить", "ещё", "еще", "также", "плюс"))


def _valid_or_none(value, allowed: set[str]) -> str | None:
    if value is None:
        return None
    value_str = str(value).lower().strip()
    return value_str if value_str in allowed else None


def _normalize_location(value) -> str | None:
    if value is None:
        return None
    location = str(value).lower().strip()
    if location in {"", "null", "none"}:
        return None
    for loc, signals in LOCATION_SIGNALS.items():
        if location == loc or location in signals:
            return loc
    return location


def _clean_source_query(source_query: str) -> str:
    """Убирает названия городов из `source_query`, потому что API ищет по тексту, а не по полям локации."""
    query = source_query.lower().strip()
    for signals in LOCATION_SIGNALS.values():
        for signal in signals:
            query = re.sub(rf"\b{re.escape(signal)}\b", " ", query)
    query = re.sub(r"\s+", " ", query).strip()
    return query or source_query


def _explicitly_mentions(raw: str, value: str | None) -> bool:
    """Проверяет, содержит ли `raw` значение `value` или один из его известных алиасов."""
    if not value:
        return False
    text = raw.lower()
    if value in text:
        return True
    aliases: dict[str, list[str]] = {
        "full-time":  TYPE_SIGNALS["full-time"],
        "part-time":  TYPE_SIGNALS["part-time"],
        "internship": SENIORITY_SIGNALS["internship"],
        "junior":     SENIORITY_SIGNALS["junior"],
        "remote":     LOCATION_SIGNALS["remote"],
    }
    return any(alias in text for alias in aliases.get(value, []))


def parse_query_fallback(raw: str) -> UserQuery:
    """
    Разбирает запрос без LLM через словарный поиск по известным алиасам.

    Используется, когда `GROQ_API_KEY` не задан или Groq вернул ошибку.
    """
    text = raw.lower()
    found_keywords: list[str] = []
    remaining = text
    for alias, canonical in sorted(SKILL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in remaining:
            found_keywords.append(canonical)
            remaining = remaining.replace(alias, " ")

    preferred_type = None
    for jtype, signals in TYPE_SIGNALS.items():
        if any(s in text for s in signals):
            preferred_type = jtype
            break

    preferred_location = None
    for loc, signals in LOCATION_SIGNALS.items():
        if any(s in text for s in signals):
            preferred_location = loc
            break

    seniority = None
    if not _has_ambiguous_seniority(raw):
        for level, signals in SENIORITY_SIGNALS.items():
            if any(s in text for s in signals):
                seniority = level
                break

    return UserQuery(
        raw=raw,
        keywords=_unique(found_keywords),
        preferred_type=preferred_type,
        preferred_location=preferred_location,
        seniority=seniority,
        source_query=_build_source_query(raw, found_keywords, seniority),
    )


def merge_query_context(current: UserQuery, previous: UserQuery | None) -> UserQuery:
    """
    Наследует недостающие параметры из предыдущего запроса interactive-сессии.

    Это делает уточнения вроде «хочу стажировку и частичную занятость» устойчивыми:
    если до этого пользователь искал `frontend`, новый запрос сохранит этот навык,
    но обновит явно названные уровень и занятость.
    """
    if previous is None:
        return current

    if current.keywords and _is_additive_refinement(current.raw):
        keywords = previous.keywords + current.keywords
    else:
        keywords = current.keywords or previous.keywords
    seniority = current.seniority if current.seniority is not None else previous.seniority

    return UserQuery(
        raw=current.raw,
        keywords=_unique(keywords),
        preferred_type=(
            current.preferred_type
            if current.preferred_type is not None
            else previous.preferred_type
        ),
        preferred_location=(
            current.preferred_location
            if current.preferred_location is not None
            else previous.preferred_location
        ),
        seniority=seniority,
        source_query=_build_source_query(current.raw, keywords, seniority),
    )


def _parse_via_groq(raw: str, history: list[dict] | None = None) -> UserQuery:
    """
    Извлекает параметры поиска через Groq Function Calling.

    `history` — предыдущие реплики диалога для multi-turn REPL: LLM понимает
    уточнения вроде «теперь только удалённо» в контексте прошлых ходов.
    При любой ошибке LLM происходит fallback в `parse_query_fallback`.
    """
    system_msg = {"role": "system", "content": PARSE_QUERY_SYSTEM_PROMPT}
    user_msg = {"role": "user", "content": PARSE_QUERY_USER_TEMPLATE.format(raw=raw)}

    messages: list[dict] = [system_msg]
    if history:
        messages.extend(history)
    messages.append(user_msg)

    try:
        data = tool_call_completion(
            messages=messages,
            tool_schema=PARSE_QUERY_TOOL,
            temperature=0.1,
            max_tokens=400,
        )
        fallback    = parse_query_fallback(raw)
        llm_type     = _valid_or_none(data.get("preferred_type"), {"full-time", "part-time"})
        llm_location = _normalize_location(data.get("preferred_location"))
        llm_seniority = _valid_or_none(data.get("seniority"), {"internship", "junior"})
        ambiguous_seniority = _has_ambiguous_seniority(raw)

        return UserQuery(
            raw=raw,
            keywords=_unique([str(k).lower() for k in data.get("keywords", [])]),
            preferred_type=fallback.preferred_type or (
                llm_type if _explicitly_mentions(raw, llm_type) else None
            ),
            preferred_location=fallback.preferred_location or (
                llm_location if _explicitly_mentions(raw, llm_location) else None
            ),
            seniority=None if ambiguous_seniority else fallback.seniority or (
                llm_seniority if _explicitly_mentions(raw, llm_seniority) else None
            ),
            source_query=_clean_source_query(
                str(data.get("source_query") or fallback.source_query)
            ),
        )
    except (LLMError, TypeError, KeyError) as exc:
        print(f"  [Groq] parse_query (function calling) ошибка: {exc}. Fallback.")

    return parse_query_fallback(raw)


def parse_query(raw: str, history: list[dict] | None = None) -> UserQuery:
    """
    Преобразует свободный текст запроса в структурированный `UserQuery`.

    При доступном Groq использует Function Calling, иначе переключается на
    rule-based реализацию.
    """
    if llm_available():
        return _parse_via_groq(raw, history=history)
    return parse_query_fallback(raw)
