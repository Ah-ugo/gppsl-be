"""AI assistant service. Order of work:
1. Handle greetings / capability queries warmly and role-specifically.
2. Handle executive / MD remote business monitoring queries directly from live operational data.
3. Route domain questions to role-filtered database queries.
4. Add high-confidence document excerpts (RAG) only if genuinely relevant.
5. If an LLM key exists, let the model synthesize the answer from verified data; otherwise return structured data.
"""

import re
from typing import Any, Optional

from app.core.common import today
from app.core.db import get_db
from app.core.settings_store import get_settings_doc
from app.logic.ai_router import analyse_prompt, route
from app.modules.dashboard import service as dash
from app.modules.documents import service as docs

from . import llm, tools

NOT_FOUND = "I couldn't find specific database records or documents matching your query."
MOCK_NOTE = "GPPSL Verified Operations Intelligence (deterministic verified database layer)."



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


async def chat(
    question: str, history: list[dict[str, str]], user: dict[str, Any]
) -> dict[str, Any]:
    cleaned_q = question.strip()
    projects, branches = await _context(user)

    # STEP 1: Deep analysis and understanding of prompt before deciding source allocation
    analysis = analyse_prompt(cleaned_q, today(), projects, branches, user)

    # 1. Conversational greeting
    if analysis.get("is_greeting"):
        return {
            "answer": _greeting_response(user),
            "sources": [],
            "table": None,
            "chart": None,
            "mode": "gppsl-assistant",
            "note": None,
            "analysis": analysis,
        }

    # 1b. Conversational reply (Gratitude, Acknowledgment, Farewell, Platform FAQs)
    if analysis.get("conversational_reply"):
        return {
            "answer": analysis["conversational_reply"],
            "sources": [],
            "table": None,
            "chart": None,
            "mode": "gppsl-assistant",
            "note": None,
            "analysis": analysis,
        }

    # 2. Executive / MD remote operations telemetry
    if analysis.get("is_md_monitoring"):
        summary_text = await dash.daily_summary()
        return {
            "answer": (
                f"### 🏢 GPPSL Executive Remote Operations Briefing\n\n"
                f"{summary_text}\n\n"
                "*You can drill into any project, branch location, invoice, or equipment unit for deeper real-time telemetry.*"
            ),
            "sources": [
                {
                    "type": "system",
                    "id": "dashboard",
                    "label": "Live GPPSL Operations Database",
                }
            ],
            "table": None,
            "chart": None,
            "mode": "gppsl-assistant",
            "note": None,
            "analysis": analysis,
        }

    # STEP 2: Execute allocated retrieval based on understanding
    calls = analysis.get("tool_calls", [])
    results: list[dict[str, Any]] = []
    for c in calls:
        results.append(await tools.run(c["tool"], c["args"], user))

    excerpts = []
    # If the analysis identified technical/SOP/manuals or no direct DB calls matched, query verified document chunks
    if (analysis.get("requires_docs") or not calls) and len(cleaned_q.split()) >= 2:
        excerpts = await docs.search_chunks(question, user, k=4)

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
            "mode": "data" if not llm.available() else llm.provider_name(),
            "note": MOCK_NOTE if not llm.available() else None,
            "analysis": analysis,
        }

    table = next((r["table"] for r in live if r.get("table")), None)
    chart = next((r["chart"] for r in live if r.get("chart")), None)

    if llm.available():
        answer = await _mistral_answer(question, history, user, live, excerpts)
        note = None
        mode = llm.provider_name()
    else:
        mode = "data"
        if live:
            answer = "\n\n".join(r["text"] for r in live)
        elif excerpts:
            answer = "From verified company documents:\n" + "\n".join(
                f"- **{e['name']}**: {e['text'][:350].strip()}" for e in excerpts
            )
        else:
            answer = (
                f"I looked across our live operational database (projects, equipment, staff, finances, attendance, and technical manuals), "
                f"but didn't find specific records matching **\"{cleaned_q}\"**.\n\n"
                "**Here are quick questions you can ask me right now:**\n"
                "• 📊 *\"List my expenditures\"* or *\"What is our cash balance and overdue receivables?\"*\n"
                "• 🚜 *\"Where is the nitrogen unit?\"* or *\"Show equipment in maintenance\"*\n"
                "• 👥 *\"Who is clocked in at Warri base today?\"* or *\"Who is my best staff?\"*\n"
                "• 🏗️ *\"Give me an executive operations summary for the MD\"*\n"
                "• ❓ *\"How to clock in\"* or *\"Update project progress\"*"
            )
            sources = []  # Do not attach random sources if nothing matched
        note = MOCK_NOTE

    return {
        "answer": answer,
        "sources": _dedupe(sources)[:14],
        "table": table,
        "chart": chart,
        "mode": mode,
        "note": note,
        "analysis": analysis,
    }


async def _mistral_answer(
    question: str,
    history: list[dict[str, str]],
    user: dict,
    live: list[dict],
    excerpts: list[dict],
) -> str:
    """Uses Mistral to synthesize an authoritative, smart answer from verified live database facts."""
    pre = "\n\n".join(r["text"] for r in live if r.get("text"))
    doc_context = "\n\n".join(f"[{e['name']}]\n{e['text']}" for e in excerpts)

    combined_facts = ""
    if pre:
        combined_facts += f"Verified Operational Data:\n{pre}\n\n"
    if doc_context:
        combined_facts += f"Verified Company Documents:\n{doc_context}\n\n"

    # If verified live data or document excerpts were already extracted:
    if combined_facts:
        try:
            instruction = (
                f"Answer the user's prompt '{question}' warmly and directly for a user with role '{user.get('role', 'staff')}'. "
                f"Synthesize the answer based strictly on the verified operational data provided below. "
                f"Be specific with names, branches, percentages, amounts, and dates. "
                f"Do not invent facts or mention tool calls."
            )
            return await llm.rewrite(instruction, combined_facts)
        except Exception:
            return pre or (f"From verified documents:\n{doc_context[:500]}") or NOT_FOUND

    # Otherwise, give Mistral access to live database tools to query directly
    async def run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return await tools.run(name, args, user)

    try:
        specs = [s for s in tools.TOOL_SPECS if tools.allowed(s["name"], user)]
        return await llm.chat_with_tools(question, history, specs, run_tool, "")
    except Exception:
        return NOT_FOUND



def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for i in items:
        k = (i["type"], i["id"])
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
            "Rewrite as a short, clear morning briefing for the MD. Keep every figure exactly.",
            facts,
        )
    except Exception:
        return None


async def daily(branch: Optional[str] = None) -> dict[str, str]:
    ai = await ai_daily_summary(branch)
    if ai:
        return {"text": ai, "source": "ai"}
    return {"text": await dash.daily_summary(branch), "source": "data"}


async def project_summary(
    project_id: str, user: dict[str, Any]
) -> Optional[dict[str, Any]]:
    p = await get_db().projects.find_one({"_id": project_id})
    if not p:
        return None
    r = await tools.get_project_summary(user, p["name"])
    text, source = r["text"], "data"
    if llm.available():
        try:
            text, source = (
                await llm.rewrite(
                    "Summarise this project for a manager in 3 sentences. Keep every figure exactly.",
                    r["text"],
                ),
                "ai",
            )
        except Exception:
            pass
    return {"text": text, "source": source, "sources": r["sources"]}
