"""
collect_jobs.py — сбор данных Track C из открытого API «Работа России».

Скрипт сохраняет очищенный raw-snapshot в `data/raw/trudvsem_YYYY-MM-DD.json`.
Перед сохранением удаляются контактные поля; в нормализованный датасет попадают
только поля вакансии, которые реально использует агент.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

from config import API_TIMEOUT, TRUDVSEM_API_BASE, TRUDVSEM_PAGE_SIZE

RAW_DIR = Path(__file__).parent / "data" / "raw"

DEFAULT_QUERIES = [
    "стажировка python",
    "стажер frontend react",
    "стажировка аналитик данных",
    "junior backend python",
    "junior golang разработчик",
    "стажер devops docker",
    "стажировка android kotlin",
    "junior machine learning",
    "python удаленная",
    "backend python удалённая",
]


def fetch_query(query: str, limit: int = 30) -> list[dict]:
    page_size = max(1, min(TRUDVSEM_PAGE_SIZE, limit, 3))
    items: list[dict] = []

    for offset in range(0, max(1, limit), page_size):
        data = fetch_page(query=query, limit=page_size, offset=offset)
        page_items = data.get("results", {}).get("vacancies", [])
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < page_size or len(items) >= limit:
            break

    return items[:limit]


def fetch_page(query: str, limit: int, offset: int) -> dict:
    params = urllib.parse.urlencode({
        "text": query,
        "limit": max(1, min(limit, 100)),
        "offset": max(0, offset),
    })
    url = f"{TRUDVSEM_API_BASE}/vacancies?{params}"
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


def collect_all(queries: list[str], limit: int) -> list[dict]:
    seen: set[str] = set()
    all_items: list[dict] = []

    for query in queries:
        print(f"  -> «{query}» ...", end=" ", flush=True)
        try:
            items = fetch_query(query=query, limit=limit)
            new_items = []
            for wrapped in items:
                vacancy = wrapped.get("vacancy", {})
                vacancy_id = vacancy.get("id")
                if not vacancy_id or vacancy_id in seen:
                    continue
                seen.add(vacancy_id)
                new_items.append({"vacancy": _sanitize_vacancy(vacancy)})
            all_items.extend(new_items)
            print(f"{len(new_items)} новых ({len(all_items)} всего)")
        except OSError as exc:
            print(f"ОШИБКА: {exc}")
        time.sleep(0.4)

    return all_items


def save_raw(items: list[dict], queries: list[str]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    out = {
        "source": "trudvsem.ru",
        "api_endpoint": f"{TRUDVSEM_API_BASE}/vacancies",
        "collected_at": datetime.now().isoformat(),
        "queries": queries,
        "count": len(items),
        "data_note": "Public open-data response; contact fields removed before saving.",
        "results": {"vacancies": items},
    }
    path = RAW_DIR / f"trudvsem_{today}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  Сохранено: {path} ({len(items)} вакансий)")
    return path


def _sanitize_vacancy(vacancy: dict) -> dict:
    cleaned = dict(vacancy)
    cleaned.pop("contact_list", None)
    cleaned.pop("contact_person", None)
    company = dict(cleaned.get("company") or {})
    company.pop("email", None)
    cleaned["company"] = company
    return cleaned


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect-jobs",
        description="Сбор вакансий из открытого API «Работа России» для Track C.",
    )
    parser.add_argument("--query", "-q", action="append", metavar="ТЕКСТ",
                        help="Поисковый запрос; можно передать несколько раз.")
    parser.add_argument("--per-page", type=int, default=30, metavar="N",
                        help="Вакансий на запрос, максимум 100 (по умолчанию: 30).")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    queries = args.query or DEFAULT_QUERIES

    print(f"Сбор данных из API «Работа России» ({len(queries)} запросов)...\n")
    items = collect_all(queries=queries, limit=args.per_page)

    if not items:
        print("Ничего не собрано. Проверьте интернет или попробуйте другой запрос.")
        sys.exit(1)

    save_raw(items, queries)
    print("\nГотово. Запустите normalize_jobs.py для обновления data/jobs.json.")


if __name__ == "__main__":
    main()
