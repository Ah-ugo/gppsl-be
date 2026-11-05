"""Maps a plain-English question to data tool calls. Pure Python (standard library only).

Used as the FALLBACK when no Mistral key is set or Mistral fails, so the app still answers from REAL database queries.
Also provides instant answers for small talk and platform FAQs. With a key, Mistral picks the tools itself.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

STATUS_WORDS = {
    "available": "available",
    "free": "available",
    "deployed": "deployed",
    "out on": "deployed",
    "in transit": "in_transit",
    "maintenance": "maintenance",
    "under repair": "maintenance",
    "being serviced": "maintenance",
}
EQUIPMENT_WORDS = [
    "flooding", "lifting", "nitrogen", "jetting", "hose", "flange",
    "air loader", "loader", "pump", "unit",
]
CERT_WORDS = ["certificat", "expir", "bosiet", "huet", "h2s", "first aid", "medical", "licen"]
STOP = {
    "where", "is", "the", "a", "an", "are", "our", "we", "do", "does", "which", "what", "find",
    "show", "me", "locate", "of", "for", "in", "at", "on", "to", "my", "us", "how", "status",
    "project", "tell", "about", "give", "list", "all", "any", "please", "now", "currently", "today",
}


def _days_from(q: str, default: int) -> int:
    m = re.search(
        r"(?:over|more than|older than|above|beyond|past|within|next|in|last)\s+(\d{1,3})\s*(?:\+\s*)?days?", q
    ) or re.search(r"(\d{1,3})\s*\+?\s*days?", q)
    return int(m.group(1)) if m else default


def _branch(q: str, branches: list[str]) -> Optional[str]:
    from app.core.common import resolve_branch

    for b in branches:
        first = b.lower().split()[0]
        if first not in ("port", "all") and re.search(rf"\b{re.escape(first)}\b", q, re.I):
            return resolve_branch(b, branches)
        if re.search(rf"\b{re.escape(b.lower())}\b", q, re.I):
            return resolve_branch(b, branches)
    if re.search(r"\b(port\s*harcourt|ph|phc|portharcourt)\b", q, re.I):
        return resolve_branch("Port Harcourt", branches)
    if re.search(r"\bwarri\b", q, re.I):
        return resolve_branch("Warri", branches)
    if re.search(r"\babuja\b", q, re.I):
        return resolve_branch("Abuja", branches)
    return None


def _date_range(q: str, today: date) -> tuple[str, str]:
    if "yesterday" in q:
        d = today - timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if "today" in q:
        return today.isoformat(), today.isoformat()
    if "last month" in q or "30 days" in q:
        return (today - timedelta(days=30)).isoformat(), today.isoformat()
    if "last week" in q:
        end = today - timedelta(days=today.weekday() + 1)
        return (end - timedelta(days=6)).isoformat(), end.isoformat()
    if "this month" in q:
        return today.replace(day=1).isoformat(), today.isoformat()
    return (today - timedelta(days=6)).isoformat(), today.isoformat()


def _equipment_term(q: str) -> str:
    for phrase, status in STATUS_WORDS.items():
        if phrase in q:
            return status
    for w in EQUIPMENT_WORDS[:7]:
        if w in q:
            return w
    words = [w for w in re.findall(r"[a-z0-9\-]+", q) if w not in STOP]
    return " ".join(words) or "pump"


GREETING_PATTERNS = [
    r"^\s*(hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|greetings|howfar|how\s+are\s+you|what'?s\s+up)\b",
    r"^\s*(who\s+are\s+you|what\s+can\s+you\s+do|help|guide\s+me|how\s+does\s+this\s+work|what\s+are\s+your\s+capabilities)\b",
]
GRATITUDE_PATTERNS = [
    r"^\s*(thank\s*you|thanks|thanks\s+a\s+lot|appreciate\s+it|good\s+job|well\s+done|awesome|great\s+work|perfect)\b",
]
ACKNOWLEDGMENT_PATTERNS = [
    r"^\s*(ok|okay|alright|got\s+it|noted|understood|cool|fine|sure|sharp)\b",
]
FAREWELL_PATTERNS = [
    r"^\s*(bye|goodbye|see\s+you|have\s+a\s+good\s+day|good\s+night)\b",
]


def _is_smalltalk(q: str, patterns: list[str]) -> bool:
    """Only small talk if the message is basically just the pleasantry ('ok, show me cash' is NOT)."""
    for pat in patterns:
        m = re.search(pat, q)
        if m and len(q[m.end():].split()) <= 2:
            return True
    return False


FAQ_PATTERNS = {
    "attendance_clockin": (
        r"\b(how\s+to\s+clock\s*in|how\s+do\s+i\s+clock\s*in|attendance\s+guide|face\s+verification\s+attendance|roster\s+checkin|clocking\s+in)\b",
        "Attendance & Clock-in Guidance",
        (
            "### 🕒 Attendance & Clock-in Guide\n\n"
            "1. **Face Verification & Geofence (Smartphones)**:\n"
            "   • Navigate to **Attendance** from the sidebar.\n"
            "   • Allow camera and location permissions. The system verifies your face template against your profile and checks that your GPS is within the registered base radius (e.g., Port Harcourt HQ, Warri, Lagos, or rig sites).\n"
            "   • Click **Verify & Clock In**.\n\n"
            "2. **Worker Roster & Bulk Check-in (Cleaners, Drivers, Yard Hands)**:\n"
            "   • Supervisors, Branch Managers, HR, and Admins can switch to the **Worker Roster Check-in** tab.\n"
            "   • Check off workers present on shift (cleaners, yard laborers, security, contract techs).\n"
            "   • Click **Confirm Shift Attendance** to log verified presence without requiring them to own smartphones."
        ),
    ),
    "equipment_qr": (
        r"\b(how\s+to\s+add\s+equipment|scan\s+qr|equipment\s+qr|generate\s+qr|equipment\s+tag)\b",
        "Equipment QR Scanning & Asset Tagging",
        (
            "### 🚜 Equipment QR Scanning & Tracking\n\n"
            "• **Scan QR Tag**: On the Equipment page, click **Add Equipment** and use **📷 Scan / Import QR Code** to pre-fill serial number, model, category, and specifications from an existing unit tag.\n"
            "• **Generate & Print QR Tags**: On any equipment record, click the **QR Code** button to view, download as PNG, or print physical weatherproof asset tags for pumps, nitrogen units, and tools.\n"
            "• **Asset Status**: Track readiness across *Available*, *Deployed*, *In Transit*, and *Maintenance* with full location tracking."
        ),
    ),
    "invoice_receipt": (
        r"\b(how\s+to\s+create\s+invoice|raise\s+invoice|generate\s+receipt|share\s+invoice|billing\s+client)\b",
        "Client Invoicing & Receipts",
        (
            "### 💰 Invoicing & Receipts\n\n"
            "• Navigate to **Invoicing** from the sidebar.\n"
            "• Click **Create Invoice**, choose the client, enter service items, and specify VAT (7.5%) and WHT (5%).\n"
            "• Click **Export PDF** to generate an official branded PDF invoice or receipt with vector company seal and bank details.\n"
            "• You can also share the invoice directly via WhatsApp or Email."
        ),
    ),
    "document_signing": (
        r"\b(who\s+can\s+sign|how\s+to\s+sign|digital\s+signing|assigned\s+signers?|signature\s+workflow)\b",
        "Digital Document Signing Workflow",
        (
            "### ✍️ Digital Document Signing\n\n"
            "• Go to **Documents** in the sidebar.\n"
            "• Upload contracts, inspection certificates, or handover forms.\n"
            "• Assign designated signers in required order (e.g. Supervisor -> Branch Manager -> MD -> Client).\n"
            "• Designated signers see a highlighted **Sign Document** button, can draw their real signature or use biometric stamp, and click **Approve & Sign**.\n"
            "• All signed documents and uploaded files are stored securely on Cloudinary with tamper-evident digital timestamps."
        ),
    ),
    "gppsl_overview": (
        r"\b(what\s+is\s+gppsl|about\s+gppsl|tell\s+me\s+about\s+gppsl|company\s+overview)\b",
        "GPPSL Company & Operations Overview",
        (
            "### 🏢 About GPPSL Operations Platform\n\n"
            "GPPSL is an integrated operations and business management platform designed for Nigerian oilfield services, contractor logistics, and equipment rental companies.\n\n"
            "• **Port Harcourt HQ, Warri Base, Lagos & Offshore**: Unifies fleet management, multi-base staff attendance, client accounts, procurement, and HSE compliance.\n"
            "• **Role-Based Controls**: Secure tailored workspaces for MD, Branch Managers, Admins, Finance, HR, Supervisors, and Storekeepers."
        ),
    ),
}

MD_MONITORING_PATTERNS = [
    r"\b(md\s+monitoring|executive\s+summary|remote\s+monitoring|business\s+health|how\s+is\s+(the\s+)?business|operational?\s+overview|daily\s+summary|overall\s+status|command\s+center|pulse)\b",
    r"\b(monitor\s+business|remote\s+business|end\s+to\s+end\s+monitoring)\b",
]


def _base(**kw: Any) -> dict[str, Any]:
    """Common fields every analysis dict carries."""
    out: dict[str, Any] = {
        "entities": {},
        "is_greeting": False,
        "is_md_monitoring": False,
        "requires_docs": False,
        "tool_calls": [],
    }
    out.update(kw)
    return out


def _chat_reply(intent: str, label: str, understanding: str, reply: str, source: str, store: str, reasoning: str, entities: Optional[dict] = None) -> dict[str, Any]:
    return _base(
        intent=intent,
        intent_label=label,
        understanding=understanding,
        entities=entities or {},
        allocated_source=source,
        target_store=store,
        reasoning=reasoning,
        conversational_reply=reply,
    )


def analyse_prompt(
    question: str,
    today: date,
    projects: Optional[list[str]] = None,
    branches: Optional[list[str]] = None,
    user: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Analyses and understands the prompt before allocating where results should come from."""
    q = question.lower().strip()
    projects, branches = projects or [], branches or []
    branch = _branch(q, branches)

    # 1. Greeting / capability inquiry
    if _is_smalltalk(q, GREETING_PATTERNS):
        return _base(
            intent="conversational_greeting",
            intent_label="Conversational Greeting",
            understanding="User is greeting the assistant or inquiring about GPPSL operations assistant capabilities.",
            allocated_source="Conversational Executive Assistant Core",
            target_store="system.dialogue_engine",
            reasoning="Direct conversational greeting or capability guidance request.",
            is_greeting=True,
        )

    # 1b. Gratitude
    if _is_smalltalk(q, GRATITUDE_PATTERNS):
        return _chat_reply(
            "conversational_gratitude", "Gratitude & Courtesy", "User is expressing gratitude.",
            "You're very welcome! 😊 Let me know if you need any operational updates, equipment status, "
            "client accounts, or financial figures across our Nigerian operations.",
            "Conversational Executive Assistant Core", "system.dialogue_engine", "Courteous conversational closure.",
        )

    # 1c. Acknowledgment
    if _is_smalltalk(q, ACKNOWLEDGMENT_PATTERNS):
        return _chat_reply(
            "conversational_acknowledgment", "Acknowledgment", "User acknowledged the information.",
            "Understood! 👍 I'm here whenever you need to look up projects, verify attendance, check certificates, or monitor bases.",
            "Conversational Executive Assistant Core", "system.dialogue_engine", "Conversational confirmation.",
        )

    # 1d. Farewell
    if _is_smalltalk(q, FAREWELL_PATTERNS):
        return _chat_reply(
            "conversational_farewell", "Farewell", "User is saying goodbye.",
            "Goodbye! Have a safe and productive day. Stay safe on site! 👋",
            "Conversational Executive Assistant Core", "system.dialogue_engine", "Conversational farewell.",
        )

    # 1e. Platform FAQs
    for key, (pattern, label, reply) in FAQ_PATTERNS.items():
        if re.search(pattern, q):
            return _chat_reply(
                f"faq_{key}", label, f"User is asking for workflow guidance on {label}.", reply,
                "Platform Standard Operating Knowledge Base", "system.knowledge_base",
                f"Provided direct step-by-step guidance for {label}.", {"topic": key},
            )

    # 1f. Expenditures
    if re.search(r"\b(expenditures?|expenses?|claims?|spending|disbursements?)\b", q):
        scope = "mine" if re.search(r"\b(my|mine|me|i)\b", q) else "all"
        return _base(
            intent="financial_expenditures",
            intent_label="Expenditures & Expense Claims",
            understanding="User is querying their personal expenditures." if scope == "mine" else "User is querying company expenditures.",
            entities={"scope": scope, "category": "expenses"},
            allocated_source="Verified Finance Ledger (Expenses & Disbursements)",
            target_store="db.expenses",
            reasoning=f"Allocated to expense records with scope='{scope}'.",
            tool_calls=[{"tool": "get_expenses_summary", "args": {"scope": scope}}],
        )

    # 2. Executive / MD telemetry
    if any(re.search(pat, q) for pat in MD_MONITORING_PATTERNS):
        return _base(
            intent="md_executive_telemetry",
            intent_label="Executive Remote Operations Telemetry",
            understanding="User is requesting an end-to-end operational overview of bases, ongoing work, and fleet status.",
            entities={"scope": "all_bases"},
            allocated_source="Executive Operations Command Center",
            target_store="dashboard.daily_summary (cross-department aggregated pulse)",
            reasoning="Prompt requires aggregating operational metrics across all bases.",
            is_md_monitoring=True,
        )

    # 3. Known project
    proj = next((p for p in projects if p.lower() in q), None)
    if not proj:
        for p in projects:
            if sum(1 for w in re.findall(r"[a-z]{4,}", p.lower()) if w in q) >= 2:
                proj = p
                break
    if proj and not re.search(r"\b(update|change|set|mark)\b.*\b(progress|completion|percentage)\b", q):
        return _base(
            intent="project_operations",
            intent_label="Project Milestones & Deliverables",
            understanding=f"User is inquiring about the project '{proj}'.",
            entities={"project": proj},
            allocated_source="Projects & Work Orders Ledger",
            target_store="db.projects",
            reasoning=f"Matched company project '{proj}'.",
            tool_calls=[{"tool": "get_project_summary", "args": {"project": proj}}],
        )

    # 4. Overdue receivables
    if re.search(r"\b(owe|owes|owing|overdue|outstanding|unpaid|receivable|invoice|invoices|debt|debtors?)\b", q):
        days = _days_from(q, 0)
        return _base(
            intent="financial_receivables",
            intent_label="Overdue Receivables & Debtors",
            understanding=(
                f"User is querying client invoices with unpaid balances older than {days} days."
                if days > 0
                else "User is requesting all clients with outstanding invoice balances."
            ),
            entities={"days": days, "category": "invoices", "scope": "clients"},
            allocated_source="Verified Finance Ledger (Invoices & Client Accounts)",
            target_store="db.invoices + db.clients",
            reasoning=f"Allocated to client billing records to compute ageing balances ({days}+ days).",
            tool_calls=[{"tool": "get_overdue_invoices", "args": {"days": days}}],
        )

    # 5. Cash position
    if re.search(r"\b(cash|bank|balance|payables?|liquidity|money)\b", q):
        return _base(
            intent="financial_liquidity",
            intent_label="Treasury & Cash Position",
            understanding="User is inquiring about cash balance, bank accounts, and liquidity.",
            entities={"category": "treasury"},
            allocated_source="Finance Treasury & Cash Accounts",
            target_store="db.settings (cash balance) + db.payables",
            reasoning="Allocated to treasury ledger for cash and payables position.",
            tool_calls=[{"tool": "get_cash_position", "args": {}}],
        )

    # 6. Sales
    if re.search(
        r"\b(total sales|sales this month|sales for this month|monthly sales|revenue this month|this month's sales|how much sales|turnover this month|total revenue)\b",
        q,
    ):
        return _base(
            intent="financial_sales",
            intent_label="Monthly Revenue & Billing",
            understanding="User is requesting total revenue and sales for the current month.",
            entities={"period": "this_month", "category": "revenue"},
            allocated_source="Finance Invoicing Ledger",
            target_store="db.invoices (current month)",
            reasoning="Allocated to invoices issued within the current calendar month.",
            tool_calls=[{"tool": "get_sales_this_month", "args": {}}],
        )

    # 7. Certificates
    if any(w in q for w in CERT_WORDS):
        days = _days_from(q, 60)
        return _base(
            intent="compliance_certifications",
            intent_label="Expiring Safety Certifications",
            understanding=f"User is checking certifications expiring within {days} days (BOSIET, HUET, medicals).",
            entities={"days": days, "category": "certifications"},
            allocated_source="Compliance & Safety Registry",
            target_store="db.staff + db.equipment (certificates)",
            reasoning=f"Allocated to compliance documents expiring within {days} days.",
            tool_calls=[{"tool": "get_expiring_certificates", "args": {"days": days}}],
        )

    # 8. Staff headcount
    count_words = r"(how many|what is the total|total|count|headcount|number of|team size)"
    if re.search(rf"\b{count_words}\b.*\b(staffs?|employees?|people)\b|\b(staffs?|employees?|people)\b.*\b{count_words}\b", q):
        return _base(
            intent="workforce_headcount",
            intent_label="Staff Headcount",
            understanding="User is checking the total number of registered employees.",
            entities={"category": "staff"},
            allocated_source="HR & Personnel Database",
            target_store="db.staff",
            reasoning="Allocated to employee roster records.",
            tool_calls=[{"tool": "get_staff_count", "args": {}}],
        )

    # 8b. Best staff
    if re.search(
        r"\b(best|top|most\s+reliable|top\s+perform|most\s+punctual|hardest\s+work|most\s+dedicated|mvp|never\s+miss|never\s+absent|who\s+should\s+i\s+promote|star\s+performer|outstanding\s+staff|ranked?\s+staff|staff\s+rank)\b",
        q,
    ) and re.search(r"\b(staff|employee|worker|people|team)\b", q):
        if re.search(r"\b(punctual|late|on.time|never.late)\b", q):
            metric = "punctuality"
        elif re.search(r"\b(attend|present|show.up|never.miss|never.absent)\b", q):
            metric = "attendance"
        else:
            metric = "overall"
        return _base(
            intent="workforce_performance_ranking",
            intent_label="Top Staff Performance Ranking",
            understanding="User wants the best performing or most reliable staff by attendance and punctuality.",
            entities={"metric": metric, "branch": branch},
            allocated_source="HR Attendance & Performance Analytics",
            target_store="db.attendance + db.staff",
            reasoning=f"Ranking from attendance logs, metric='{metric}', branch='{branch or 'all'}'.",
            tool_calls=[{"tool": "get_best_staff", "args": {"metric": metric, "branch": branch, "top_n": 5}}],
        )

    # 9. Client count
    if re.search(
        r"\b(how many|what is the total|total|count|number of)\b.*\b(customers?|clients?)\b|\b(customers?|clients?)\b.*\b(how many|what is the total|total|count|number of)\b",
        q,
    ):
        return _base(
            intent="crm_client_roster",
            intent_label="Customer Roster",
            understanding="User is checking the total number of client accounts.",
            entities={"category": "clients"},
            allocated_source="CRM Client Database",
            target_store="db.clients",
            reasoning="Allocated to client account records.",
            tool_calls=[{"tool": "get_customer_count", "args": {}}],
        )

    # 9b. Update project progress (never guess a write)
    if re.search(r"\b(update|change|set|mark)\b.*\b(progress|completion|percentage)\b", q) or re.search(
        r"\bprogress\b.*\b(update|to\s+\d+)\b", q
    ):
        pct_match = re.search(r"(\d{1,3})\s*%", q) or re.search(r"\b(?:to|=)\s*(\d{1,3})\b", q)
        target_proj = next((p for p in projects if p.lower() in q), None)
        if not pct_match or not target_proj:
            return _chat_reply(
                "project_progress_update", "Update Project Progress",
                "User wants to update project progress but the project or percentage is unclear.",
                "Which project, and what percentage? For example: *\"Update Warri Hydrotest progress to 60%\"*.",
                "Project Delivery & Work Orders", "db.projects",
                "Refusing to guess a write: need explicit project and percentage.",
            )
        pct = int(pct_match.group(1))
        return _base(
            intent="project_progress_update",
            intent_label="Update Project Progress",
            understanding=f"User wants to update '{target_proj}' to {pct}%.",
            entities={"project": target_proj, "progress": pct},
            allocated_source="Project Delivery & Work Orders",
            target_store="db.projects",
            reasoning=f"Updating project progress to {pct}% in the live database.",
            tool_calls=[{"tool": "update_project_progress", "args": {"project": target_proj, "progress": pct}}],
        )

    # 10. Attendance
    if re.search(r"\b(attendance|present|absent|late|clocked|clock-in|clock in|turned up|on site today|who is in)\b", q):
        return _base(
            intent="workforce_attendance",
            intent_label="Workforce Biometric Attendance",
            understanding=f"User is checking staff attendance for {branch or 'all operational bases'} today.",
            entities={"branch": branch, "date": today.isoformat()},
            allocated_source="Biometric Attendance & Geofence System",
            target_store="db.attendance + db.sites",
            reasoning=f"Allocated to daily check-in logs for {branch or 'all locations'}.",
            tool_calls=[{"tool": "get_attendance_today", "args": {"branch": branch}}],
        )

    # 11. Equipment
    if re.search(
        r"\b(where|locate|find|equipment|pump|nitrogen|jetting|hose|flange|loader|deployed|available|maintenance|serviced)\b", q
    ) or any(w in q for w in EQUIPMENT_WORDS):
        term = _equipment_term(q)
        return _base(
            intent="equipment_telemetry",
            intent_label="Equipment Fleet Telemetry",
            understanding=f"User is querying equipment matching '{term}'.",
            entities={"search_term": term, "category": "equipment"},
            allocated_source="Equipment Fleet & Maintenance Database",
            target_store="db.equipment",
            reasoning=f"Allocated to the asset registry to locate units matching '{term}'.",
            tool_calls=[{"tool": "find_equipment", "args": {"name_or_status": term}}],
        )

    # 12. Live record search
    if re.search(
        r"\b(staffs?|employees?|customers?|clients?|people|project|equipment|asset|invoice|expense|cash|receivable|payable|attendance|report|incident|site|vendor)\b",
        q,
    ) and not re.search(r"\b(policy|guide|checklist|standard|manual|procedure|agreement|rules|forms?|document)\b", q):
        rules = [
            ("staff", r"\b(staffs?|employees?|people)\b"),
            ("clients", r"\b(customers?|clients?)\b"),
            ("projects", r"\bproject\b"),
            ("equipment", r"\b(equipment|asset|pump|hose|nitrogen|loader|unit|machine)\b"),
            ("invoices", r"\b(invoice|receivable|payable|cash|expense)\b"),
            ("attendance", r"\b(attendance|present|absent|late|clocked|clock-in|clock in)\b"),
            ("daily_reports", r"\b(report|incident|site|progress)\b"),
        ]
        collection = next((c for c, pat in rules if re.search(pat, q)), "clients")
        return _base(
            intent=f"live_{collection}_search",
            intent_label=f"{collection.title()} Record Search",
            understanding=f"User is searching for {collection} records matching the prompt.",
            entities={"collection": collection, "query": question},
            allocated_source=f"Live Database ({collection})",
            target_store=f"db.{collection}",
            reasoning=f"Allocated to {collection} collection to find matching records.",
            tool_calls=[{"tool": "search_live_records", "args": {"collection": collection, "query": question}}],
        )

    # 13. Field reports
    if re.search(r"\b(reports?|site updates?|progress|summari[sz]e|summary|what happened)\b", q):
        f, t = _date_range(q, today)
        return _base(
            intent="site_operations_reporting",
            intent_label="Daily Field Site Reports",
            understanding=f"User is requesting daily reports for {branch or 'all branches'} from {f} to {t}.",
            entities={"branch": branch, "from": f, "to": t},
            allocated_source="Field Site Operational Logs",
            target_store="db.daily_reports",
            reasoning=f"Allocated to field shift reports between {f} and {t}.",
            tool_calls=[{"tool": "get_reports", "args": {"branch": branch, "from": f, "to": t}}],
        )

    # 14. Technical manual / SOP
    if re.search(
        r"\b(procedure|manual|guide|standard|operating|hydrotest|nitrogen|pumping|flange|safety|incident|hazard|step|how\s+to|specs?)\b", q
    ):
        return _base(
            intent="technical_sop_document",
            intent_label="Technical SOP & Safety Manuals",
            understanding=f"User is asking about technical procedures or safety guidelines regarding '{question[:60]}'.",
            entities={"topic": question[:60]},
            allocated_source="Verified Corporate Engineering & HSE Knowledge Base",
            target_store="Vector Document Chunk Index (RAG)",
            reasoning="Allocated to indexed operational manuals and safety procedures.",
            requires_docs=True,
        )

    # 15. General
    return _base(
        intent="general_query",
        intent_label="General Inquiry",
        understanding=f"User asked a general operational question: '{question[:80]}'.",
        allocated_source="GPPSL Central Knowledge & Operations Index",
        target_store="System Index",
        reasoning="Scanning verified company records and documentation.",
        requires_docs=True,
    )


def route(
    question: str,
    today: date,
    projects: Optional[list[str]] = None,
    branches: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Returns [{tool, args}, ...]; an empty list means 'search the documents instead'."""
    return analyse_prompt(question, today, projects, branches)["tool_calls"]