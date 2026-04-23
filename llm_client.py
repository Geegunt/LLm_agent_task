"""Тонкая обёртка над API Groq Chat Completions."""

from __future__ import annotations

import json

from config import GROQ_API_KEY, GROQ_MODEL, GROQ_TIMEOUT


class LLMError(RuntimeError):
    """Выбрасывается, когда запрос к Groq завершился ошибкой или дал непригодный ответ."""


def llm_available() -> bool:
    return bool(GROQ_API_KEY)


def llm_mode_label() -> str:
    return f"Groq/{GROQ_MODEL}" if llm_available() else "rule-based fallback"


def _get_client():
    if not GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set")
    try:
        from groq import Groq
    except ImportError as exc:
        raise LLMError(
            "package 'groq' is not installed; run: pip install -r requirements.txt"
        ) from exc
    return Groq(api_key=GROQ_API_KEY, timeout=GROQ_TIMEOUT)


def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 700,
    json_mode: bool = False,
) -> str:
    """Отправляет chat-запрос и возвращает текст ответа ассистента."""
    client = _get_client()
    kwargs: dict = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
    except Exception as exc:
        raise LLMError(str(exc)) from exc

    if not isinstance(content, str) or not content.strip():
        raise LLMError("Groq response content is empty")
    return content.strip()


def tool_call_completion(
    messages: list[dict[str, str]],
    tool_schema: dict,
    *,
    temperature: float = 0.1,
    max_tokens: int = 400,
) -> dict:
    """
    Отправляет запрос с одним принудительным tool call и возвращает распарсенные аргументы.

    Использует нативный Groq Function Calling: модель явно вызывает функцию, а
    не возвращает свободный JSON-текст, поэтому результат валидируется схемой.
    """
    client = _get_client()
    fn_name = tool_schema["function"]["name"]

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=[tool_schema],
            tool_choice={"type": "function", "function": {"name": fn_name}},
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise LLMError(str(exc)) from exc

    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        raise LLMError(f"Groq did not return tool_calls for '{fn_name}'")

    try:
        return json.loads(tool_calls[0].function.arguments)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise LLMError(f"Failed to parse tool call arguments: {exc}") from exc


def agentic_completion(
    messages: list[dict],
    tools: list[dict],
    *,
    temperature: float = 0.1,
    max_tokens: int = 400,
    require_tool: bool = True,
) -> tuple[dict, list[tuple[str, str, dict]]]:
    """
    Выполняет один шаг агентного цикла.

    Возвращает словарь сообщения ассистента, готовый к добавлению в `messages`,
    и список кортежей `(tool_name, call_id, args_dict)` для каждого вызова
    инструмента. Пустой список означает, что модель решила не вызывать ни один
    инструмент и завершить цикл.
    """
    client = _get_client()

    def _sanitize(s: str) -> str:
        # В некоторых терминалах stdin использует surrogateescape; заменяем
        # одиночные суррогаты до отправки в Groq, потому что сервис отвергает
        # не-UTF-8 полезную нагрузку.
        return s.encode("utf-8", errors="replace").decode("utf-8") if isinstance(s, str) else s

    safe_messages = [
        {k: _sanitize(v) if isinstance(v, str) else v for k, v in m.items()}
        for m in messages
    ]

    kwargs: dict = {
        "model": GROQ_MODEL,
        "messages": safe_messages,
        "tools": tools,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if require_tool:
        kwargs["tool_choice"] = "required"

    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:
        raise LLMError(str(exc)) from exc

    msg = response.choices[0].message
    calls_raw = getattr(msg, "tool_calls", None) or []

    assistant_dict: dict = {"role": "assistant", "content": msg.content or ""}
    if calls_raw:
        assistant_dict["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in calls_raw
        ]

    parsed_calls: list[tuple[str, str, dict]] = []
    for tc in calls_raw:
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            args = {}
        parsed_calls.append((tc.function.name, tc.id, args))

    return assistant_dict, parsed_calls


def chat_completion_stream(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.25,
    max_tokens: int = 900,
    prefix: str = "     ",
) -> str:
    """
    Стримит токены в stdout по мере поступления и возвращает собранный текст.

    Перенос по словам на 64 символах делает вывод читаемым в узких терминалах
    без буферизации всего ответа перед показом.
    """
    client = _get_client()

    try:
        stream = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
    except Exception as exc:
        raise LLMError(str(exc)) from exc

    print(prefix, end="", flush=True)
    collected: list[str] = []
    col = len(prefix)

    for chunk in stream:
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None)
        if not token:
            continue
        collected.append(token)
        for char in token:
            if char == "\n":
                print(f"\n{prefix}", end="", flush=True)
                col = len(prefix)
            else:
                print(char, end="", flush=True)
                col += 1
                if col >= 64 and char == " ":
                    print(f"\n{prefix}", end="", flush=True)
                    col = len(prefix)

    print()
    return "".join(collected).strip()
