"""The ONLY place that talks to a language model. This project uses Mistral when a key is provided.

With no key `available` is False and callers use the labelled data-only fallback built from real database queries.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from app.core.config import get_settings

SYSTEM_PROMPT = (
    "You are the GPPSL business assistant for a Nigerian oil and gas services company. "
    "Answer ONLY from the tool results and document excerpts you are given. "
    'If the data needed is missing or a tool says it is not permitted, say "I couldn\'t find that" (or that the role '
    "is not allowed) and do not guess. Never invent figures, names, dates or sources. "
    "Amounts are in Nigerian Naira (₦). Dates are DD/MM/YYYY. Keep answers short and plain."
)

MAX_ROUNDS = 4


def available() -> bool:
    return bool(get_settings().mistral_api_key)


def provider_name() -> str:
    return "mistral" if available() else "unavailable"


def _model():
    from langchain_mistralai import (
        ChatMistralAI,
    )  # imported lazily: not needed in mock mode

    s = get_settings()
    return ChatMistralAI(
        model=s.mistral_model, api_key=s.mistral_api_key, temperature=0
    )


async def chat_with_tools(
    question: str,
    history: list[dict[str, str]],
    tool_specs: list[dict[str, Any]],
    run_tool: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    context: str = "",
) -> str:
    """Tool-calling loop. `run_tool(name, args)` executes against the real database (role-filtered by the caller)."""
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    llm = _model().bind_tools(tool_specs)
    msgs: list[Any] = [
        SystemMessage(
            content=SYSTEM_PROMPT
            + (f"\n\nDocument excerpts:\n{context}" if context else "")
        )
    ]
    for h in history[-6:]:
        msgs.append(
            HumanMessage(content=h["content"])
            if h["role"] == "user"
            else AIMessage(content=h["content"])
        )
    msgs.append(HumanMessage(content=question))
    for _ in range(MAX_ROUNDS):
        resp = await llm.ainvoke(msgs)
        calls = getattr(resp, "tool_calls", None) or []
        if not calls:
            return _text(resp.content)
        msgs.append(resp)
        for c in calls:
            result = await run_tool(c["name"], c.get("args") or {})
            msgs.append(
                ToolMessage(
                    content=json.dumps(result.get("data", result), default=str)[:12000],
                    tool_call_id=c["id"],
                )
            )
    return "I couldn't find that."


async def rewrite(instruction: str, facts: str) -> str:
    """One-shot: turn verified facts into short prose. The facts are the only allowed source."""
    from langchain_core.messages import HumanMessage, SystemMessage

    resp = await _model().ainvoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"{instruction}\n\nFACTS:\n{facts}"),
        ]
    )
    return _text(resp.content)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    return "".join(
        p.get("text", "") if isinstance(p, dict) else str(p) for p in content
    ).strip()
