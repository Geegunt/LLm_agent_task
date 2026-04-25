#!/usr/bin/env python3
"""Проверки перед сдачей для агента подбора вакансий Track A+C."""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).parent


def main() -> None:
    # Валидация должна быть детерминированной и не требовать LLM-ключа.
    os.environ.pop("GROQ_API_KEY", None)
    os.environ["LOAD_DOTENV"] = "0"
    os.environ["LIVE_API_ENABLED"] = "0"

    checks = [
        ("README has Track tag", check_readme_track),
        ("README documents one-command run", check_readme_run),
        ("REFLECTION has 300+ words", check_reflection_length),
        ("Track C raw data has source/date", check_raw_data),
        ("Normalized data schema is complete", check_normalized_data),
        (".env is gitignored", check_env_gitignored),
        ("No API key committed", check_no_secret_committed),
        ("Agent tools are registered", check_tools_registered),
        ("Russian fallback parser handles demo query", check_parser),
        ("Parser handles ambiguous level and remote aliases", check_parser_edge_cases),
        ("Interactive context keeps previous role intent", check_interactive_context),
        ("Ranking returns explainable internship-fit results", check_ranking),
        ("Top results are not dominated by one employer", check_result_diversity),
        ("Skill-less matches are filtered out", check_skill_filtering),
        ("Role intent is reflected in ranking", check_role_alignment),
    ]

    failures: list[str] = []
    for name, fn in checks:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
            print(f"FAIL  {name}: {exc}")

    if failures:
        print("\nValidation failed:")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)

    print("\nAll validation checks passed.")


def check_readme_track() -> None:
    first = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0].strip()
    assert first == "Track: A+C", f"expected 'Track: A+C', got {first!r}"


def check_readme_run() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'python3 main.py "стажировка python москва" --top 5 --compare' in readme
    assert "GROQ_API_KEY" in readme
    assert "Работа России" in readme


def check_reflection_length() -> None:
    text = (ROOT / "REFLECTION.md").read_text(encoding="utf-8")
    words = re.findall(r"\S+", text)
    assert len(words) >= 300, f"only {len(words)} words"


def check_raw_data() -> None:
    raw_path = ROOT / "data" / "raw" / "trudvsem_2026-04-23.json"
    assert raw_path.exists(), "missing raw snapshot"
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    assert data.get("source") == "trudvsem.ru"
    assert data.get("api_endpoint", "").endswith("/vacancies")
    assert data.get("collected_at", "").startswith("2026-04-23")
    assert data.get("count", 0) >= 30
    assert "contact fields removed" in data.get("data_note", "")


def check_normalized_data() -> None:
    jobs = json.loads((ROOT / "data" / "jobs.json").read_text(encoding="utf-8"))
    assert len(jobs) >= 30, f"expected at least 30 jobs, got {len(jobs)}"
    required = {
        "id", "title", "company", "location", "type", "tags", "description",
        "posted_at", "salary_range", "source", "url", "collected_at",
        "experience_years",
    }
    for job in jobs:
        missing = required - set(job)
        assert not missing, f"{job.get('id')} missing {sorted(missing)}"
        assert job["source"] == "trudvsem.ru"
        assert job["collected_at"] == "2026-04-23"
        assert job["url"].startswith("https://trudvsem.ru/vacancy/card/")


def check_no_secret_committed() -> None:
    secret_prefix = "g" + "sk_"
    for path in ROOT.rglob("*"):
        if path.is_dir() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == ".env":
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            continue
        assert secret_prefix not in text, f"possible Groq key in {path.relative_to(ROOT)}"


def check_env_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in {line.strip() for line in gitignore.splitlines()}, ".env is not ignored"


def check_tools_registered() -> None:
    from src import agent

    expected = {
        "parse_query",
        "fetch_jobs",
        "filter_and_rank_jobs",
        "explain_top_jobs",
        "compare_jobs",
    }
    assert expected <= set(agent.TOOLS), f"missing tools: {expected - set(agent.TOOLS)}"


def check_parser() -> None:
    from src import agent

    query = agent.dispatch("parse_query", raw="я студент, хочу стажировку по питону в москве")
    assert "python" in query.keywords
    assert query.preferred_type is None
    assert query.preferred_location == "москва"
    assert query.seniority == "internship"
    assert query.source_query == "стажировка python"

    part_time = agent.dispatch("parse_query", raw="стажировка python частичная занятость")
    assert part_time.preferred_type == "part-time"
    assert part_time.seniority == "internship"

    full_time = agent.dispatch("parse_query", raw="junior python полная занятость удаленно")
    assert full_time.preferred_type == "full-time"
    assert full_time.preferred_location == "remote"
    assert full_time.seniority == "junior"


def check_parser_edge_cases() -> None:
    from src import agent

    ambiguous = agent.dispatch(
        "parse_query",
        raw="ищу стажировку или работу джуном по python на удаленке",
    )
    assert ambiguous.preferred_type is None
    assert ambiguous.preferred_location == "remote"
    assert ambiguous.seniority is None
    assert "python" in ambiguous.keywords


def check_interactive_context() -> None:
    from src import agent

    context = agent.dispatch("parse_query", raw="frontend")
    query, results, _, _ = agent.run(
        "хочу стажировку и частичную занятость, потому что буду совмещать с учебой",
        top_n=3,
        compare=False,
        context=context,
    )
    assert "frontend" in query.keywords
    assert query.seniority == "internship"
    assert query.preferred_type == "part-time"
    assert query.source_query == "стажировка frontend"
    assert all("frontend" in r.matched_keywords for r in results)


def check_ranking() -> None:
    from src import agent

    query, results, explanations, comparison = agent.run(
        "стажировка python москва",
        top_n=3,
        compare=True,
    )
    assert query.preferred_type is None
    assert query.seniority == "internship"
    assert len(results) == 3
    assert len(explanations) == 3
    assert comparison and "Сравнение вакансий" in comparison
    top = results[0]
    assert top.score >= 0.9
    assert "python" in top.matched_keywords
    assert top.score_breakdown["junior_fit"] == 1.0
    assert top.job.source == "trudvsem.ru"


def check_result_diversity() -> None:
    from src import agent

    _, results, _, _ = agent.run("стажировка python москва", top_n=5, compare=False)
    assert len(results) == 5
    counts = Counter(r.job.company for r in results)
    assert max(counts.values()) <= 2, f"one employer dominates top-5: {counts}"


def check_skill_filtering() -> None:
    from src import agent

    query = agent.dispatch("parse_query", raw="frontend")
    jobs = agent.dispatch("fetch_jobs", query=query.source_query)
    ranked = agent.dispatch("filter_and_rank_jobs", jobs=jobs, query=query)
    assert ranked, "expected at least one frontend-ish result"
    assert all(r.matched_keywords for r in ranked[:5]), "top results include zero-skill matches"


def check_role_alignment() -> None:
    from src import agent

    query = agent.dispatch("parse_query", raw="junior backend python удалённо")
    jobs = agent.dispatch("fetch_jobs", query=query.source_query)
    ranked = agent.dispatch("filter_and_rank_jobs", jobs=jobs, query=query)
    assert ranked, "expected backend results"
    assert ranked[0].score_breakdown["role_alignment"] > 0, "top result has no backend alignment"


if __name__ == "__main__":
    main()
