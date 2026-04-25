from typing import Callable

from .config import TOP_N
from .constants.prompts import (
    AGENTIC_SYSTEM_PROMPT,
    AGENTIC_TOOL_SCHEMAS,
    BROADEN_QUERY_SYSTEM_PROMPT,
    BROADEN_QUERY_USER_TEMPLATE,
)
from .llm_client import (
    LLMError,
    agentic_completion,
    chat_completion,
    llm_available,
    llm_mode_label,
)
from .models import RankedJob, UserQuery
from .tools import fetch_jobs as _fetch_jobs_module
from .tools.compare_jobs    import compare_jobs
from .tools.explain_job     import explain_top_jobs
from .tools.fetch_jobs      import fetch_jobs
from .tools.filter_and_rank import filter_and_rank_jobs
from .tools.parse_query     import merge_query_context, parse_query, parse_query_fallback


TOOLS: dict[str, Callable] = {
    "parse_query":          parse_query,
    "fetch_jobs":           fetch_jobs,
    "broaden_query":        None,          # type: ignore[dict-item]  # заполняется ниже
    "filter_and_rank_jobs": filter_and_rank_jobs,
    "explain_top_jobs":     explain_top_jobs,
    "compare_jobs":         compare_jobs,
}

_BROADEN_THRESHOLD = 4


def dispatch(tool_name: str, **kwargs):
    """Вызывает зарегистрированный инструмент по имени."""
    if tool_name not in TOOLS:
        raise ValueError(f"Unknown tool '{tool_name}'. Available: {list(TOOLS)}")
    fn = TOOLS[tool_name]
    if fn is None:
        raise ValueError(f"Tool '{tool_name}' is not initialised.")
    return fn(**kwargs)


def _broaden_query(query: UserQuery, result_count: int) -> str:
    """
    Предлагает более широкий поисковый запрос, если live-результатов слишком мало.

    При доступном Groq новый запрос генерирует LLM; без него fallback убирает
    префикс уровня и оставляет до двух навыков.
    """
    if llm_available():
        try:
            content = chat_completion(
                [
                    {
                        "role": "system",
                        "content": BROADEN_QUERY_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": BROADEN_QUERY_USER_TEMPLATE.format(
                            source_query=query.source_query,
                            result_count=result_count,
                            raw_query=query.raw,
                            keywords=", ".join(query.keywords) or "—",
                        ),
                    },
                ],
                temperature=0.3,
                max_tokens=40,
            )
            broader = content.strip().strip("«»\"'")
            if broader and broader.lower() != query.source_query.lower():
                return broader
        except LLMError as exc:
            print(f"  [Groq] broaden_query ошибка: {exc}. Fallback.")

    parts = list(dict.fromkeys(query.keywords[:2]))
    return " ".join(parts) if parts else query.raw


TOOLS["broaden_query"] = _broaden_query


def _run_pipeline(
    raw_query: str,
    top_n: int,
    compare: bool,
    history: list[dict] | None,
    context: UserQuery | None = None,
) -> tuple[UserQuery, list[RankedJob], list[str], str | None]:
    """
    Детерминированный четырёхшаговый пайплайн, который используется без LLM.

    Порядок шагов жёстко задан в коде; адаптивных решений между шагами нет.
    `broaden_query` вызывается как необязательный шаг 2b, если live-результатов мало.
    """
    llm_mode = llm_mode_label()

    print(f"  [агент] Шаг 1 → parse_query ({llm_mode})")
    query: UserQuery = merge_query_context(
        dispatch("parse_query", raw=raw_query, history=history),
        context,
    )
    print(f"          ключевые слова: {query.keywords or '—'}")
    print(f"          занятость: {query.preferred_type or 'любая'}, "
          f"место: {query.preferred_location or 'любое'}, "
          f"уровень: {query.seniority or 'любой'}")
    print(f"          запрос для источника: «{query.source_query}»")

    print("  [агент] Шаг 2 → fetch_jobs (API «Работа России»)")
    jobs = dispatch("fetch_jobs", query=query.source_query or query.raw)
    print(f"          получено вакансий: {len(jobs)}")

    live_count    = _fetch_jobs_module.get_last_live_count()
    broaden_count = live_count if live_count is not None else len(jobs)
    if broaden_count < _BROADEN_THRESHOLD and query.keywords:
        print(f"  [агент] Шаг 2b → broaden_query ({llm_mode}) "
              f"[мало live-результатов: {broaden_count} < {_BROADEN_THRESHOLD}]")
        broader = dispatch("broaden_query", query=query, result_count=len(jobs))
        if broader and broader.lower() != query.source_query.lower():
            print(f"          расширенный запрос: «{broader}»")
            extra    = dispatch("fetch_jobs", query=broader)
            seen_ids = {j.id for j in jobs}
            new_jobs = [j for j in extra if j.id not in seen_ids]
            jobs.extend(new_jobs)
            print(f"          вакансий после расширения: {len(jobs)} (+{len(new_jobs)})")

    print("  [агент] Шаг 3 → filter_and_rank_jobs")
    ranked: list[RankedJob] = dispatch("filter_and_rank_jobs", jobs=jobs, query=query)
    results = ranked[:top_n]
    print(f"          отобрано: {len(results)}")

    explanations: list[str] = []
    if results:
        print(f"  [агент] Шаг 4 → explain_top_jobs ({llm_mode})")
        explanations = dispatch("explain_top_jobs", ranked_jobs=results, query=query)

    comparison: str | None = None
    if compare and results:
        comparison = dispatch("compare_jobs", ranked_jobs=results)

    return query, results, explanations, comparison


_MAX_AGENT_STEPS = 8


def _execute_agentic_tool(
    tool_name: str,
    args: dict,
    state: dict,
    top_n: int,
    raw_query: str,
    history: list[dict] | None = None,
    context: UserQuery | None = None,
) -> str:
    """
    Выполняет один вызов инструмента внутри агентного цикла и обновляет `state`.

    Возвращает текстовый результат, который добавляется в историю сообщений LLM
    как сообщение с ролью `tool`.
    """
    if tool_name == "parse_query":
        q = merge_query_context(
            dispatch("parse_query", raw=args.get("raw_query", raw_query), history=history),
            context,
        )
        state["query"] = q
        print("  [агент] LLM → parse_query")
        print(f"          ключевые слова: {q.keywords or '—'}")
        print(f"          занятость: {q.preferred_type or 'любая'}, "
              f"место: {q.preferred_location or 'любое'}, "
              f"уровень: {q.seniority or 'любой'}")
        print(f"          source_query: «{q.source_query}»")
        return (
            f"Запрос разобран:\n"
            f"  keywords: {q.keywords}\n"
            f"  preferred_type: {q.preferred_type or 'null'}\n"
            f"  preferred_location: {q.preferred_location or 'null'}\n"
            f"  seniority: {q.seniority or 'null'}\n"
            f"  source_query: «{q.source_query}»"
        )

    elif tool_name == "fetch_jobs":
        search_q = args.get("search_query", "")
        if search_q in state["search_queries_used"]:
            return f"Запрос «{search_q}» уже использовался — попробуй другой."
        state["search_queries_used"].append(search_q)

        new_jobs_raw = fetch_jobs(query=search_q)
        live         = _fetch_jobs_module.get_last_live_count()
        live_str     = str(live) if live is not None else "—"
        state["live_count_last"] = live if live is not None else 0

        seen     = {j.id for j in state["jobs"]}
        new_jobs = [j for j in new_jobs_raw if j.id not in seen]
        state["jobs"].extend(new_jobs)

        hint = (
            "Мало live-результатов — рассмотри повторный fetch_jobs с более широким запросом."
            if state["live_count_last"] < _BROADEN_THRESHOLD else
            "Достаточно вакансий для ранжирования."
        )
        print(f"  [агент] LLM → fetch_jobs(«{search_q}»)")
        print(f"          API: {live_str} live, +{len(new_jobs)} новых, итого в очереди: {len(state['jobs'])}")
        return (
            f"Запрос «{search_q}»: API вернул {live_str} вакансий (live).\n"
            f"Новых добавлено: {len(new_jobs)}. Итого в очереди: {len(state['jobs'])}.\n"
            f"{hint}"
        )

    elif tool_name == "filter_and_rank_jobs":
        if not state["jobs"] or state["query"] is None:
            return "Ошибка: сначала получи вакансии через fetch_jobs."
        top_n_arg = int(args.get("top_n", top_n))
        ranked    = dispatch("filter_and_rank_jobs", jobs=state["jobs"], query=state["query"])
        state["ranked"] = ranked
        top   = ranked[:top_n_arg]
        lines = [f"Ранжировано {len(ranked)} вакансий, топ-{top_n_arg}:"]
        for i, r in enumerate(top):
            lines.append(f"  #{i + 1}. score={r.score:.2f} | {r.job.title} — {r.job.company}")
        print(f"  [агент] LLM → filter_and_rank_jobs(top_n={top_n_arg})")
        print(f"          ранжировано: {len(ranked)}, отобрано: {len(top)}")
        return "\n".join(lines)

    elif tool_name == "explain_top_jobs":
        if not state["ranked"] or state["query"] is None:
            return "Ошибка: сначала ранжируй вакансии через filter_and_rank_jobs."
        top = state["ranked"][:top_n]
        print("  [агент] LLM → explain_top_jobs()")
        explanations = dispatch("explain_top_jobs", ranked_jobs=top, query=state["query"])
        state["explanations"] = explanations
        return f"Объяснения готовы для {len(explanations)} вакансий."

    elif tool_name == "finish":
        summary = args.get("summary", "")
        state["finished"] = True
        print("  [агент] LLM → finish")
        print(f"          {summary}")
        return f"Поиск завершён. {summary}"

    return f"Неизвестный инструмент: {tool_name}."


def _run_agentic_loop(
    raw_query: str,
    top_n: int,
    compare: bool,
    history: list[dict] | None,
    context: UserQuery | None = None,
) -> tuple[UserQuery, list[RankedJob], list[str], str | None]:
    """
    Агентный цикл под управлением LLM.

    На каждом шаге модель видит полную историю сообщений, включая результаты
    предыдущих вызовов инструментов, и сама решает, какой инструмент вызвать
    следующим. Это принципиально отличается от пайплайна: модель может повторно
    вызвать `fetch_jobs` с более широким запросом или пропустить шаг, исходя из
    наблюдаемого результата.

    При любой неустранимой ошибке LLM происходит fallback в `_run_pipeline`.
    """
    llm_mode = llm_mode_label()
    print(f"  [агент] Режим: LLM-driven agentic loop ({llm_mode})")

    state: dict = {
        "query":               None,
        "jobs":                [],
        "ranked":              [],
        "explanations":        [],
        "search_queries_used": [],
        "live_count_last":     0,
        "finished":            False,
    }

    messages: list[dict] = [{"role": "system", "content": AGENTIC_SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({
        "role": "user",
        "content": f"Запрос кандидата: «{raw_query}». Найди топ-{top_n} вакансий.",
    })

    try:
        for _step in range(_MAX_AGENT_STEPS):
            assistant_msg, tool_calls = agentic_completion(
                messages=messages,
                tools=AGENTIC_TOOL_SCHEMAS,
                temperature=0.1,
                max_tokens=300,
                require_tool=not state["finished"],
            )
            messages.append(assistant_msg)

            if not tool_calls:
                break

            for tool_name, call_id, args in tool_calls:
                result_text = _execute_agentic_tool(
                    tool_name, args, state, top_n, raw_query,
                    history=history,
                    context=context,
                )
                messages.append({
                    "role": "tool",
                    "content": result_text,
                    "tool_call_id": call_id,
                })

            if state["finished"]:
                break

    except LLMError as exc:
        print(f"  [агент] Agentic loop ошибка LLM: {exc}. Переключаюсь на pipeline.")
        return _run_pipeline(raw_query, top_n, compare, history, context=context)
    except Exception as exc:
        print(f"  [агент] Agentic loop непредвиденная ошибка: {exc}. Переключаюсь на pipeline.")
        return _run_pipeline(raw_query, top_n, compare, history, context=context)

    # Страховка: гарантируем результат каждого обязательного шага, даже если LLM
    # завершилась раньше времени или пропустила вызов инструмента.
    if state["query"] is None:
        state["query"] = merge_query_context(
            dispatch("parse_query", raw=raw_query, history=history),
            context,
        )
    if not state["jobs"]:
        q = state["query"]
        state["jobs"] = dispatch("fetch_jobs", query=q.source_query or q.raw)
    if not state["ranked"] and state["jobs"]:
        state["ranked"] = dispatch("filter_and_rank_jobs", jobs=state["jobs"], query=state["query"])
    if not state["explanations"] and state["ranked"]:
        state["explanations"] = dispatch(
            "explain_top_jobs",
            ranked_jobs=state["ranked"][:top_n],
            query=state["query"],
        )

    query        = state["query"] or parse_query_fallback(raw_query)
    results      = state["ranked"][:top_n]
    explanations = state["explanations"]

    # compare_jobs — это шаг форматирования, а не агентный инструмент, поэтому
    # вызываем его напрямую.
    comparison: str | None = None
    if compare and results:
        comparison = dispatch("compare_jobs", ranked_jobs=results)

    return query, results, explanations, comparison


def run(
    raw_query: str,
    top_n: int = TOP_N,
    compare: bool = False,
    history: list[dict] | None = None,
    context: UserQuery | None = None,
) -> tuple[UserQuery, list[RankedJob], list[str], str | None]:
    """
    Главная точка входа.

    Если задан `GROQ_API_KEY`, запускает агентный цикл с LLM, где модель сама
    решает, какие инструменты вызывать и в каком порядке. Без ключа использует
    детерминированный четырёхшаговый пайплайн с rule-based парсингом и
    шаблонными объяснениями.

    Возвращает `(UserQuery, ranked_jobs, explanations, comparison_table | None)`.
    """
    if llm_available():
        return _run_agentic_loop(raw_query, top_n, compare, history, context=context)
    return _run_pipeline(raw_query, top_n, compare, history, context=context)
