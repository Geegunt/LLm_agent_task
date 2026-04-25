"""CLI-рендеринг: карточки вакансий, заголовок запроса и итоговая сводка."""

import shutil
import textwrap

from .constants.display import EMPTY_LABEL, LEVEL_LABELS, TYPE_LABELS_FULL
from .constants.ranking import INTERNSHIP_MARKERS, JUNIOR_MARKERS
from .models import RankedJob, UserQuery

W       = max(90, min(shutil.get_terminal_size((110, 24)).columns, 140))
LABEL_W = 10
VALUE_W = W - LABEL_W - 7
FULL_W  = W - 4


def _type_ru(t: str) -> str:
    return TYPE_LABELS_FULL.get(t, EMPTY_LABEL)


def _level_ru(level: str | None) -> str:
    return LEVEL_LABELS.get(level or "", EMPTY_LABEL)


def _job_level_ru(r: RankedJob) -> str:
    text = " ".join([r.job.title, r.job.description]).lower()
    if r.job.type == "internship" or any(word in text for word in INTERNSHIP_MARKERS):
        return LEVEL_LABELS["internship"]
    if any(word in text for word in JUNIOR_MARKERS):
        return LEVEL_LABELS["junior"]
    return EMPTY_LABEL


def _salary_ru(s: str | None) -> str:
    if not s:
        return EMPTY_LABEL
    low = s.strip().lower()
    if low in {"0", "от 0", "до 0", "0 руб.", "от 0 руб.", "до 0 руб."}:
        return EMPTY_LABEL
    return s


def _clean(text: str | None) -> str:
    return " ".join(str(text or "").split()) or EMPTY_LABEL


def _clip(text: str, n: int) -> str:
    """Обрезает `text` до `n` символов и добавляет многоточие при усечении."""
    t = _clean(text)
    return t if len(t) <= n else t[: max(1, n - 1)].rstrip() + "…"


def _box_top(label: str) -> str:
    prefix = f"┌─ {label} "
    return prefix + "─" * max(0, W - len(prefix) - 1) + "┐"


def _box_mid() -> str:
    return f"├{'─' * (LABEL_W + 2)}┬{'─' * (VALUE_W + 2)}┤"


def _box_bottom() -> str:
    return f"└{'─' * (LABEL_W + 2)}┴{'─' * (VALUE_W + 2)}┘"


def _box_full(text: str) -> list[str]:
    """Строка на всю ширину блока без деления на ключ и значение."""
    parts = textwrap.wrap(
        _clean(text), width=FULL_W,
        break_long_words=True, break_on_hyphens=False,
    ) or [EMPTY_LABEL]
    return [f"│ {part:<{FULL_W}} │" for part in parts]


def _box_row(label: str, value: str) -> list[str]:
    """Строка вида «ключ + значение»; длинные значения переносятся, а колонка ключа остаётся пустой."""
    parts = textwrap.wrap(
        _clean(value), width=VALUE_W,
        break_long_words=True, break_on_hyphens=False,
    ) or [EMPTY_LABEL]
    rows: list[str] = []
    for i, part in enumerate(parts):
        cell_label = label if i == 0 else ""
        rows.append(f"│ {cell_label:<{LABEL_W}} │ {part:<{VALUE_W}} │")
    return rows


def _render_card(rank: int, r: RankedJob, explanation: str) -> str:
    j = r.job
    lines: list[str] = []

    lines.append(_box_top(f"#{rank} · оценка {r.score:.2f}"))
    lines.extend(_box_full(_clip(j.title, max(30, FULL_W))))
    lines.append(_box_mid())

    salary = _salary_ru(j.salary_range)
    format_parts = [
        f"уровень: {_job_level_ru(r)}",
        f"занятость: {_type_ru(j.type)}",
        j.location,
    ]
    if salary != EMPTY_LABEL:
        format_parts.append(f"зарплата: {salary}")

    lines.extend(_box_row("Компания", j.company))
    lines.extend(_box_row("Формат",   " · ".join(format_parts)))

    matched = ", ".join(r.matched_keywords) if r.matched_keywords else EMPTY_LABEL
    lines.extend(_box_row("Совпало", matched))

    if explanation and explanation.strip():
        lines.extend(_box_row("Почему", _clip(explanation, 190)))

    lines.extend(_box_row("Описание", _clip(j.description, 160)))

    if j.url:
        lines.extend(_box_row("Ссылка", j.url))

    lines.append(_box_bottom())
    return "\n".join(lines)


def print_results(
    results:      list[RankedJob],
    explanations: list[str],
    query_str:    str,
    parsed:       UserQuery,
    comparison:   str | None = None,
) -> None:
    """Рендерит полный набор результатов: заголовок, карточки вакансий и опциональную таблицу сравнения."""
    kw    = ", ".join(parsed.keywords) if parsed.keywords else EMPTY_LABEL
    typ   = _type_ru(parsed.preferred_type) if parsed.preferred_type else "любая"
    loc   = parsed.preferred_location or "любое"
    level = _level_ru(parsed.seniority)

    print()
    print("Агент подбора вакансий")
    print("─" * W)
    print(f"Запрос:  «{query_str}»")
    print(f"Фильтр:  навыки: {kw} · занятость: {typ} · место: {loc} · уровень: {level}")

    if not results:
        print("  Вакансии не найдены. Попробуйте более общий запрос.")
        print()
        return

    n = len(results)
    print(f"Итог:    {n} {'вакансия' if n == 1 else 'вакансии' if 2 <= n <= 4 else 'вакансий'}")
    print()

    for i, r in enumerate(results, 1):
        exp = explanations[i - 1] if i - 1 < len(explanations) else ""
        print(_render_card(i, r, exp))
        if i != len(results):
            print()

    if comparison:
        print("─" * W)
        print()
        print(comparison)
        print()
