"""
normalize_jobs.py — нормализация raw-снапшотов Trudvsem в `data/jobs.json`.

На вход подаются файлы `data/raw/trudvsem_*.json`, созданные `collect_jobs.py`
или live-инструментом `fetch_jobs`. Выходная схема повторяет `models.Job`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from src.tools.fetch_jobs import normalize_trudvsem_vacancy

RAW_DIR = Path(__file__).parent / "data" / "raw"
OUT_PATH = Path(__file__).parent / "data" / "jobs.json"


def normalize_all(raw_dir: Path, out_path: Path) -> None:
    raw_files = sorted(raw_dir.glob("trudvsem_*.json"))
    if not raw_files:
        print(f"Нет файлов trudvsem_*.json в {raw_dir}. Запустите collect_jobs.py.")
        sys.exit(1)

    records: list[dict] = []
    seen_ids: set[str] = set()
    stats = {"loaded": 0, "normalized": 0, "duplicate": 0, "invalid": 0}

    for raw_file in raw_files:
        print(f"  Читаю {raw_file.name}...")
        with open(raw_file, encoding="utf-8") as f:
            raw_data = json.load(f)

        collected_at = raw_data.get("collected_at", date.today().isoformat())[:10]
        items = raw_data.get("results", {}).get("vacancies", [])
        print(f"    {len(items)} записей")

        for wrapped in items:
            stats["loaded"] += 1
            vacancy = wrapped.get("vacancy", {})
            job = normalize_trudvsem_vacancy(vacancy, collected_at=collected_at)
            if job is None:
                stats["invalid"] += 1
                continue
            if job.id in seen_ids:
                stats["duplicate"] += 1
                continue
            seen_ids.add(job.id)
            records.append(asdict(job))
            stats["normalized"] += 1

    records.sort(key=lambda item: item.get("posted_at") or "", reverse=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\nСохранено: {out_path}")
    print(f"  Загружено:     {stats['loaded']}")
    print(f"  Нормализовано: {stats['normalized']}")
    print(f"  Дубликатов:    {stats['duplicate']}")
    print(f"  Ошибок:        {stats['invalid']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="normalize-jobs",
        description="Нормализует открытые данные «Работа России» в data/jobs.json.",
    )
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR,
                        help=f"Папка с raw JSON (по умолчанию: {RAW_DIR})")
    parser.add_argument("--out", type=Path, default=OUT_PATH,
                        help=f"Выходной файл (по умолчанию: {OUT_PATH})")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(f"Нормализация данных из {args.raw_dir}...\n")
    normalize_all(raw_dir=args.raw_dir, out_path=args.out)


if __name__ == "__main__":
    main()
