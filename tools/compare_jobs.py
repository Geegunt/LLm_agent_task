"""Рендерит компактную сравнительную таблицу для топ-N ранжированных вакансий."""

from constants.display import EMPTY_LABEL, LEVEL_LABELS, TYPE_LABELS_SHORT
from constants.ranking import INTERNSHIP_MARKERS, JUNIOR_MARKERS
from models import RankedJob


def compare_jobs(ranked_jobs: list[RankedJob]) -> str:
    """Возвращает отформатированную сравнительную таблицу одной строкой, максимум на пять вакансий."""
    if not ranked_jobs:
        return "Нет вакансий для сравнения."

    jobs  = ranked_jobs[:5]
    lines = ["Сравнение вакансий", "─" * 90]
    lines.append(f"{'#':<3} {'score':<5} {'уровень':<11} {'занятость':<12} {'совпало':<14} вакансия")
    lines.append("─" * 90)

    for i, r in enumerate(jobs, 1):
        matched = ", ".join(r.matched_keywords) or EMPTY_LABEL
        title   = f"{r.job.title} · {r.job.company}"
        lines.append(
            f"{i:<3} {r.score:<5.2f} "
            f"{_trim(_job_level_ru(r), 11):<11} "
            f"{_trim(_type_ru(r.job.type), 12):<12} "
            f"{_trim(matched, 14):<14} "
            f"{_trim(title, 39)}"
        )

    lines.append("─" * 90)
    return "\n".join(lines)


def _trim(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _type_ru(t: str) -> str:
    return TYPE_LABELS_SHORT.get(t, EMPTY_LABEL)


def _job_level_ru(r: RankedJob) -> str:
    text = " ".join([r.job.title, r.job.description]).lower()
    if r.job.type == "internship" or any(word in text for word in INTERNSHIP_MARKERS):
        return LEVEL_LABELS["internship"]
    if any(word in text for word in JUNIOR_MARKERS):
        return LEVEL_LABELS["junior"]
    return EMPTY_LABEL
