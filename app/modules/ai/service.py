"""AI assistant service.

1. Greetings / thanks / platform FAQs are answered instantly (free, deterministic).
2. With an LLM key: an agent decides which role-filtered live tools to call, chains them, and analyses the results.
   Provider priority: Mistral → Gemini fallback (handled inside llm.run_agent).
3. Without any key (or if all providers fail): the regex router + verified-data fallback.
"""

import logging
from typing import Any, Optional

from app.core.common import today
from app.core.db import get_db
from app.core.settings_store import get_settings_doc
from app.logic.ai_router import analyse_prompt
from app.modules.dashboard import service as dash
from app.modules.documents import service as docs

from . import llm, tools

log = logging.getLogger(__name__)

NOT_FOUND = "I couldn't find specific database records or documents matching your query."
MOCK_NOTE = "GPPSL Verified Operations Intelligence (deterministic verified database layer)."
DEGRADED_NOTE = "The AI model is temporarily unavailable, so this answer shows verified data only."


def _greeting_response(user: dict[str, Any]) -> str:
    name = (user.get("name") or "there").split()[0]
    role = (user.get("role") or "staff").upper()
    return (
        f"Hello {name}! 👋 I am your GPPSL Operations & Executive AI Assistant.\n\n"
        f"You are logged in as **{role}**. I monitor our Nigerian operations across Port Harcourt HQ, Warri Base, Lagos, and offshore rigs:\n\n"
        "• 📊 **Executive & Financial Pulse**: Cash position, receivables ageing, unpaid invoices, VAT/WHT tracking, and revenue forecasts.\n"
        "• 🏗️ **Project & Field Delivery**: Progress, scheduled vs actual milestones, budget utilization, and reported delay alerts.\n"
        "• 👥 **Personnel & Site Attendance**: Live attendance across branches, who is clocked in at Warri or Port Harcourt, and face-verified records.\n"
        "• 🚜 **Fleet & Equipment Readiness**: Nitrogen pumping units, hydrotest spreads, air loaders, pumps deployed vs available, and maintenance schedules.\n"
        "• 🛡️ **HSE & Compliance**: Live incident reporting, lost time injury frequency, toolbox talks, and expiring certifications (BOSIET, HUET).\n\n"
        "**Quick prompts you can try:**\n"
        "• *\"Give me an executive operations summary for the MD\"*\n"
        "• *\"What is our cash and receivables position today?\"*\n"
        "• *\"Who is currently on site at Warri base?\"*\n"
        "• *\"Show all active client projects and reported delays\"*\n"
        "• *\"Which equipment units are deployed on client projects?\"*"
    )


async def _context(user: dict) -> tuple[list[str], list[str]]:
    db = get_db()
    projects = [p["name"] for p in await db.projects.find({}, {"name": 1}).to_list(500)]
    settings = await get_settings_doc()
    branches = settings.get("branches") or ["Port Harcourt HQ", "Warri", "Lagos"]
    return projects, branches


def _reply(answer: str, analysis: dict, **extra: Any) -> dict[str, Any]:
    out = {
        "answer": answer,
        "sources": [],
        "table": None,
        "chart": None,
        "mode": "gppsl-assistant",
        "note": None,
        "analysis": analysis,
    }
    out.update(extra)
    return out


async def chat(
    question: str, history: list[dict[str, str]], user: dict[str, Any]
) -> dict[str, Any]:
    q = question.strip()
    projects, branches = await _context(user)
    analysis = analyse_prompt(q, today(), projects, branches, user)

    # Instant, free answers
    if analysis.get("is_greeting"):
        return _reply(_greeting_response(user), analysis)
    if analysis.get("conversational_reply"):
        return _reply(analysis["conversational_reply"], analysis)

    # Smart path: LLM agent decides what to look up (Mistral → Gemini fallback handled in llm)
    if llm.available():
        try:
            return await _agent_answer(q, history, user, projects, branches, analysis)
        except Exception:
            log.exception("All LLM providers failed; falling back to data-only mode")
            return await _data_answer(q, user, analysis, degraded=True)

    return await _data_answer(q, user, analysis)


async def _agent_answer(
    q: str,
    history: list[dict[str, str]],
    user: dict[str, Any],
    projects: list[str],
    branches: list[str],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    used: list[dict[str, Any]] = []

    async def run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        used.append({"tool": name, "args": args})
        return await tools.run(name, args, user)

    specs = [s for s in tools.TOOL_SPECS if tools.allowed(s["name"], user)]
    system = llm.build_system_prompt(user, today().isoformat(), branches, projects)
    answer, results = await llm.run_agent(q, history, specs, run_tool, system)

    live = [r for r in results if not r.get("denied")]
    sources: list[dict[str, Any]] = []
    for r in live:
        sources += r.get("sources", [])

    analysis = {
        **analysis,
        "intent": "ai_agent",
        "intent_label": "AI Agent (live data tools)",
        "understanding": f"{llm.provider_name().title()} analysed the question and queried {len(used)} live source(s).",
        "allocated_source": f"{llm.provider_name().title()} agent + role-filtered live tools",
        "target_store": ", ".join(u["tool"] for u in used) or "no data lookup needed",
        "reasoning": "The model chose and chained tools itself based on the question and your role.",
        "tool_calls": used,
    }
    return {
        "answer": answer,
        "sources": _dedupe(sources)[:14],
        "table": next((r["table"] for r in live if r.get("table")), None),
        "chart": next((r["chart"] for r in live if r.get("chart")), None),
        "mode": llm.provider_name(),
        "note": None,
        "analysis": analysis,
    }


async def _data_answer(
    q: str, user: dict[str, Any], analysis: dict[str, Any], degraded: bool = False
) -> dict[str, Any]:
    """No-LLM fallback: regex-routed tools + verified document excerpts."""
    note = DEGRADED_NOTE if degraded else MOCK_NOTE

    if analysis.get("is_md_monitoring"):
        summary_text = await dash.daily_summary()
        return {
            "answer": (
                "### 🏢 GPPSL Executive Remote Operations Briefing\n\n"
                f"{summary_text}\n\n"
                "*You can drill into any project, branch location, invoice, or equipment unit for deeper real-time telemetry.*"
            ),
            "sources": [{"type": "system", "id": "dashboard", "label": "Live GPPSL Operations Database"}],
            "table": None,
            "chart": None,
            "mode": "data",
            "note": note,
            "analysis": analysis,
        }

    calls = analysis.get("tool_calls", [])
    results = [await tools.run(c["tool"], c["args"], user) for c in calls]

    excerpts: list[dict[str, Any]] = []
    if (analysis.get("requires_docs") or not calls) and len(q.split()) >= 2:
        excerpts = await docs.search_chunks(q, user, k=4)

    sources: list[dict[str, Any]] = []
    for r in results:
        sources += r.get("sources", [])
    for e in excerpts:
        sources.append({"type": "document", "id": e["document_id"], "label": e["name"]})

    denied = [r for r in results if r.get("denied")]
    live = [r for r in results if not r.get("denied")]
    if denied and not live:
        return {
            "answer": denied[0]["text"],
            "sources": [],
            "table": None,
            "chart": None,
            "mode": "data",
            "note": note,
            "analysis": analysis,
        }

    if live:
        answer = "\n\n".join(r["text"] for r in live)
    elif excerpts:
        answer = "From verified company documents:\n" + "\n".join(
            f"- **{e['name']}**: {e['text'][:350].strip()}" for e in excerpts
        )
    else:
        answer = (
            f"I looked across our live operational database but didn't find specific records matching **\"{q}\"**.\n\n"
            "**Here are quick questions you can ask me right now:**\n"
            "• 📊 *\"List my expenditures\"* or *\"What is our cash balance and overdue receivables?\"*\n"
            "• 🚜 *\"Where is the nitrogen unit?\"* or *\"Show equipment in maintenance\"*\n"
            "• 👥 *\"Who is clocked in at Warri base today?\"* or *\"Who is my best staff?\"*\n"
            "• 🏗️ *\"Give me an executive operations summary for the MD\"*"
        )
        sources = []

    return {
        "answer": answer,
        "sources": _dedupe(sources)[:14],
        "table": next((r["table"] for r in live if r.get("table")), None),
        "chart": next((r["chart"] for r in live if r.get("chart")), None),
        "mode": "data",
        "note": note,
        "analysis": analysis,
    }


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for i in items:
        k = (i.get("type"), i.get("id"))
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


async def ai_daily_summary(branch: Optional[str] = None) -> Optional[str]:
    """AI-phrased daily summary built only from the deterministic summary. None when no key is set."""
    facts = await dash.daily_summary(branch)
    if not llm.available():
        return None
    try:
        return await llm.rewrite(
            "Write a sharp morning briefing for the MD: one-line headline, key figures kept exactly, "
            "then the top 3 risks or actions needing attention.",
            facts,
        )
    except Exception:
        return None


async def daily(branch: Optional[str] = None) -> dict[str, str]:
    ai = await ai_daily_summary(branch)
    if ai:
        return {"text": ai, "source": "ai"}
    return {"text": await dash.daily_summary(branch), "source": "data"}


async def project_summary(project_id: str, user: dict[str, Any]) -> Optional[dict[str, Any]]:
    p = await get_db().projects.find_one({"_id": project_id})
    if not p:
        return None
    r = await tools.get_project_summary(user, p["name"])
    text, source = r["text"], "data"
    if llm.available():
        try:
            text, source = (
                await llm.rewrite(
                    "Summarise this project for a manager in 3 sentences, keep every figure exactly, "
                    "and end with the single biggest risk or next action.",
                    r["text"],
                ),
                "ai",
            )
        except Exception:
            pass
    return {"text": text, "source": source, "sources": r["sources"]}