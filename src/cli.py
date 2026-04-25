#!/usr/bin/env python3
"""
CLI-точка входа агента подбора вакансий.

Использование:
  python main.py "стажировка python москва"
  python main.py "junior backend python удалённо" --top 3 --compare
  python main.py --interactive
"""

import argparse
import contextlib
import io
import sys

from . import agent
from .constants.parsing import SKILL_ALIASES
from .display import print_results
from .models import UserQuery


def _run_agent(
    query: str,
    *,
    top_n:   int,
    compare: bool,
    history: list[dict] | None = None,
    context: UserQuery | None = None,
    verbose: bool = False,
) -> tuple[UserQuery, list, list[str], str | None]:
    if verbose:
        return agent.run(query, top_n=top_n, compare=compare, history=history, context=context)
    with contextlib.redirect_stdout(io.StringIO()):
        return agent.run(query, top_n=top_n, compare=compare, history=history, context=context)


_KNOWN_KEYWORDS = set(SKILL_ALIASES.values())


def _has_context_signal(parsed: UserQuery) -> bool:
    """Проверяет, есть ли в запросе параметры, которые полезно помнить в REPL."""
    return bool(
        parsed.preferred_type
        or parsed.preferred_location
        or parsed.seniority
        or any(keyword in _KNOWN_KEYWORDS for keyword in parsed.keywords)
    )


def _should_update_context(parsed: UserQuery, results: list) -> bool:
    """Не запоминает бессмысленные запросы без результатов, но сохраняет реальные уточнения."""
    if not _has_context_signal(parsed):
        return False
    if results:
        return True
    return bool(
        parsed.preferred_type
        or parsed.preferred_location
        or parsed.seniority
        or any(keyword in _KNOWN_KEYWORDS for keyword in parsed.keywords)
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="job-agent",
        description="Агент подбора вакансий — Работа России Open Data + Groq",
    )
    p.add_argument("query", nargs="?",
                   help='Запрос на естественном языке, например: "стажировка python москва"')
    p.add_argument("--top",  "-n", type=int, default=5, metavar="N",
                   help="Сколько результатов показать (по умолчанию: 5)")
    p.add_argument("--compare", "-c", action="store_true",
                   help="Показать сравнительную таблицу после карточек")
    p.add_argument("--interactive", "-i", action="store_true",
                   help="Запустить интерактивный REPL-режим")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Показывать пошаговую трассу работы агента")
    return p


def _prompt_query() -> str:
    print()
    print("  Агент подбора вакансий")
    print("  " + "─" * 32)
    print("  Примеры:")
    print("    стажировка python москва")
    print("    junior backend python удалённо")
    print("    стажер devops docker linux")
    try:
        raw = input("\n  Запрос: ").strip()
        return raw.encode("utf-8", errors="replace").decode("utf-8")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def interactive_loop(top_n: int, compare: bool, verbose: bool = False) -> None:
    """
    REPL с накоплением multi-turn истории.

    Сессия хранит последний осмысленный `UserQuery` и передаёт его в
    `agent.run()`. Так уточнения наследуют предыдущие навыки, локацию, уровень
    и занятость даже без LLM:

        Запрос: стажировка python москва
        Запрос: теперь только удалённо    ← агент сохраняет python
        Запрос: добавь django             ← агент ищет python + django + remote

    Специальные команды: `new` / `reset` — очистить историю; `quit` / `q` — выход.
    """
    print()
    print("  Агент подбора вакансий — интерактивный режим")
    print("  Уточнять можно контекстно: «теперь только удалённо», «добавь django».")
    print("  Команды: new — сбросить контекст  |  quit — выход")
    print()

    history: list[dict] = []
    context: UserQuery | None = None

    while True:
        try:
            query_str = input("  Запрос: ").strip()
            query_str = query_str.encode("utf-8", errors="replace").decode("utf-8")
        except (EOFError, KeyboardInterrupt):
            print("\n  До свидания!")
            break

        if not query_str:
            continue
        if query_str.lower() in {"quit", "exit", "выход", "q"}:
            print("  До свидания!")
            break
        if query_str.lower() in {"new", "сброс", "reset"}:
            history = []
            context = None
            print("  Контекст сброшен.\n")
            continue

        parsed, results, explanations, comparison = _run_agent(
            query_str,
            top_n=top_n,
            compare=compare,
            history=history or None,
            context=context,
            verbose=verbose,
        )
        print_results(results, explanations, query_str, parsed, comparison)

        history.append({"role": "user", "content": f"Запрос: «{query_str}»"})
        if _should_update_context(parsed, results):
            context = parsed
            history.append({
                "role": "assistant",
                "content": (
                    f"Агент нашёл {len(results)} вакансий по запросу «{query_str}». "
                    f"Навыки: {', '.join(parsed.keywords) or '—'}. "
                    f"Занятость: {parsed.preferred_type or 'любая'}. "
                    f"Уровень: {parsed.seniority or 'любой'}. "
                    f"Место: {parsed.preferred_location or 'любое'}."
                ),
            })

        if len(history) > 12:
            history = history[-12:]


def main() -> None:
    args = build_parser().parse_args()

    if args.interactive:
        interactive_loop(top_n=args.top, compare=args.compare, verbose=args.verbose)
        return

    query = args.query or _prompt_query()
    if not query:
        print("  Запрос не введён. Выход.")
        sys.exit(0)

    parsed, results, explanations, comparison = _run_agent(
        query,
        top_n=args.top,
        compare=args.compare,
        verbose=args.verbose,
    )
    print_results(results, explanations, query, parsed, comparison)


if __name__ == "__main__":
    main()
