"""Pure-Python demo data generator (standard library only, deterministic).

Everything is generated relative to `today`, so ageing buckets, expiries and overdue items
stay realistic whenever the seed is run. seed.py loads this into MongoDB.
All company and person names are placeholders, no real organisations.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from typing import Any

BRANCHES = ["Port Harcourt HQ", "Warri", "Abuja"]

# lat/lng are approximate city-centre points. Replace with real yard coordinates in Settings.
SITES = [
    {"name": "Port Harcourt Yard", "branch": "Port Harcourt HQ", "lat": 4.8156, "lng": 7.0498, "radius_m": 250},
    {"name": "Trans-Amadi Workshop", "branch": "Port Harcourt HQ", "lat": 4.8010, "lng": 7.0330, "radius_m": 200},
    {"name": "Warri Base", "branch": "Warri", "lat": 5.5160, "lng": 5.7500, "radius_m": 250},
    {"name": "Abuja Office", "branch": "Abuja", "lat": 9.0765, "lng": 7.3986, "radius_m": 150},
]

CERT_TYPES = ["BOSIET", "HUET", "H2S", "First aid", "Medical", "Equipment licence"]

CLIENT_NAMES = [
    "Placeholder Client A (Upstream)", "Placeholder Client B (Midstream)", "Placeholder Client C (Refinery)",
    "Placeholder Client D (Marine)", "Placeholder Client E (Power)", "Placeholder Client F (EPC)",
]

FIRST = ["Emeka", "Ngozi", "Tunde", "Amina", "Chinedu", "Funmi", "Ibrahim", "Blessing", "Segun", "Hauwa", "Ifeanyi",
         "Bola", "Yusuf", "Adaeze", "Femi", "Zainab", "Obinna", "Kemi", "Musa", "Ebere", "Tari", "Dayo", "Ada", "Kelechi",
         "Sani", "Titi", "Uche", "Gift", "Aliyu", "Nneka"]
LAST = ["Okafor", "Eze", "Adeyemi", "Bello", "Nwosu", "Balogun", "Abubakar", "Okoro", "Ogunleye", "Danjuma", "Obi",
        "Lawal", "Ibrahim", "Chukwu", "Afolabi", "Sule", "Nnamdi", "Akpan", "Garba", "Udoh", "Briggs", "Alabi", "Peters",
        "Onyeka", "Yakubu", "Coker", "Okeke", "Etim", "Bako", "Duru"]

EQUIPMENT_TYPES = [
    ("High-pressure flooding pump", "Flooding pump", 6, 8_500_000, 250_000),
    ("Lifting pump", "Lifting pump", 6, 5_200_000, 150_000),
    ("Nitrogen unit", "Nitrogen unit", 5, 38_000_000, 900_000),
    ("Jetting unit", "Jetting unit", 6, 14_500_000, 400_000),
    ("Hose assembly", "Hose", 7, 900_000, 20_000),
    ("Flange set", "Flange", 5, 650_000, 15_000),
    ("Air loader", "Air loader", 5, 3_800_000, 90_000),
]

NAME_SUFFIX = "ABCDEFGHJK"


def uid() -> str:
    return str(uuid.uuid4())


def iso(d: date) -> str:
    return d.isoformat()


def generate(today: date, seed: int = 42) -> dict[str, list[dict[str, Any]]]:
    rnd = random.Random(seed)
    data: dict[str, list[dict[str, Any]]] = {}

    # ---- Users and staff (30 staff; 9 of them have logins, the rest are field crew) ---------
    login_users = [
        ("md", "Chidi Okonkwo", "Port Harcourt HQ", True), ("admin", "Amaka Nwachukwu", "Port Harcourt HQ", True),
        ("finance", "Tolu Adebayo", "Port Harcourt HQ", True), ("supervisor", "Emeka Okafor", "Port Harcourt HQ", True),
        ("storekeeper", "Ibrahim Danladi", "Port Harcourt HQ", True), ("hr", "Ngozi Eze", "Port Harcourt HQ", True),
        ("supervisor", "Tamuno Briggs", "Warri", False), ("supervisor", "Hauwa Sule", "Abuja", False),
        ("storekeeper", "Segun Ajayi", "Warri", False),
    ]
    users, staff, used = [], [], set()
    roster: list[tuple[str, str, str, str | None]] = []  # (name, branch, position, user_id)
    for role, name, branch, demo in login_users:
        u = {"_id": uid(), "email": f"{role}@gppsl.demo" if demo else f"{name.split()[0].lower()}.{name.split()[1].lower()}@gppsl.demo",
             "name": name, "role": role, "branch": branch, "phone": f"0803{rnd.randint(1000000, 9999999)}", "active": True, "demo": demo}
        users.append(u)
        used.add(name)
        roster.append((name, branch, {"md": "Managing Director", "admin": "Administrator", "finance": "Finance Officer",
                                      "supervisor": "Site Supervisor", "storekeeper": "Storekeeper", "hr": "HR Officer"}[role], u["_id"]))
    crew_positions = ["Pump operator", "Rigger", "Technician", "Fitter", "Driver", "HSE officer", "Welder", "Jetting operator"]
    i = 0
    while len(roster) < 30:
        name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 7 + 3) % len(LAST)]}"
        i += 1
        if name in used:
            continue
        used.add(name)
        roster.append((name, BRANCHES[len(roster) % 3] if len(roster) % 5 else "Port Harcourt HQ", rnd.choice(crew_positions), None))

    site_by_branch = {s["branch"]: s for s in SITES}
    for idx, (name, branch, position, user_id) in enumerate(roster):
        certs = []
        for ctype in CERT_TYPES:
            if rnd.random() < 0.8 or ctype == "H2S":
                certs.append({"type": ctype, "expiry": iso(today + timedelta(days=rnd.randint(90, 700)))})
        staff.append({"_id": uid(), "user_id": user_id, "name": name, "position": position, "branch": branch,
                      "phone": f"080{rnd.choice([3, 5, 6, 8])}{rnd.randint(1000000, 9999999)}", "daily_rate": rnd.choice([12_000, 15_000, 18_000, 25_000]),
                      "face_template": [], "face_consent": {"given": False, "date": None}, "face_status": "none",
                      "certifications": certs, "home_site": site_by_branch[branch]["name"] if branch in site_by_branch else SITES[0]["name"]})
    # deliberate demo cases: expired / expiring certificates
    def cert(s, ctype, days):
        for c in s["certifications"]:
            if c["type"] == ctype:
                c["expiry"] = iso(today + timedelta(days=days))
                return
        s["certifications"].append({"type": ctype, "expiry": iso(today + timedelta(days=days))})
    cert(staff[10], "H2S", -20)       # expired H2S -> assignment must be refused
    cert(staff[11], "BOSIET", -3)
    cert(staff[12], "Medical", 25)    # amber
    cert(staff[13], "HUET", 45)       # amber
    cert(staff[14], "First aid", -60)
    # the demo supervisor (Emeka Okafor) holds all required certificates, valid
    for c in staff[3]["certifications"]:
        c["expiry"] = iso(today + timedelta(days=400))
    data["users"], data["staff"] = users, staff

    sites = [{"_id": uid(), **s} for s in SITES]
    data["sites"] = sites

    # ---- Clients ---------------------------------------------------------------------------
    clients = []
    for n, name in enumerate(CLIENT_NAMES):
        letter = NAME_SUFFIX[n]
        clients.append({"_id": uid(), "name": name, "contact_name": f"Accounts Payable ({letter})", "email": f"ap.client{letter.lower()}@example.com",
                        "phone": f"0809{rnd.randint(1000000, 9999999)}", "address": "Placeholder address, Nigeria",
                        "payment_terms_days": rnd.choice([60, 90, 120])})
    data["clients"] = clients

    # ---- Projects (8) with a deliberate GREEN / AMBER / RED mix ----------------------------
    pdefs = [
        # name, client idx, location, branch, budget, progress, start offset, end offset, target cost ratio
        ("Tank Cleaning Campaign", 0, "Bonny Terminal, Rivers", "Port Harcourt HQ", 45_000_000, 62, -75, 40, 0.55),
        ("Pipeline Hydrotest Package", 1, "Ughelli, Delta", "Warri", 60_000_000, 40, -60, 50, 0.92),     # amber: cost > 85%
        ("Nitrogen Purging Job", 2, "Port Harcourt Refinery Area", "Port Harcourt HQ", 28_000_000, 85, -50, 15, 0.48),
        ("Flowline Flushing", 3, "Escravos, Delta", "Warri", 35_000_000, 55, -90, -8, 0.80),             # red: past end, <100%
        ("Plant Turnaround Support", 4, "Abuja Power Plant", "Abuja", 22_000_000, 30, -40, 80, 0.30),
        ("Jetting and Hydro-blasting", 5, "Onne, Rivers", "Port Harcourt HQ", 18_000_000, 70, -45, 20, 1.08),  # red: over budget
        ("Subsea Hose Replacement", 0, "Brass, Bayelsa", "Warri", 26_000_000, 20, -20, 100, 0.18),
        ("Facilities Pressure Testing", 2, "Kaduna Depot", "Abuja", 15_000_000, 45, -35, 25, 0.35),       # amber: progress lag
    ]
    projects = []
    for name, ci, loc, branch, budget, progress, so, eo, ratio in pdefs:
        site = site_by_branch[branch]
        projects.append({"_id": uid(), "client_id": clients[ci]["_id"], "name": name, "location": loc,
                         "coordinates": {"lat": site["lat"] + rnd.uniform(-0.05, 0.05), "lng": site["lng"] + rnd.uniform(-0.05, 0.05)},
                         "branch": branch, "budget": float(budget), "status": "active", "progress": float(progress),
                         "start": iso(today + timedelta(days=so)), "end": iso(today + timedelta(days=eo)), "_ratio": ratio})
    data["projects"] = projects

    # ---- Equipment (40) --------------------------------------------------------------------
    equipment: list[dict[str, Any]] = []
    n = 0
    for label, category, count, cost, _rate in EQUIPMENT_TYPES:
        for k in range(count):
            n += 1
            interval = {"Flooding pump": 500, "Lifting pump": 400, "Nitrogen unit": 600, "Jetting unit": 450}.get(category, 1000)
            run = rnd.randint(50, interval + 150)
            last = max(0, run - rnd.randint(20, interval - 60))  # normally within interval
            branch = BRANCHES[(n + k) % 3]
            certs = []
            if category in ("Flooding pump", "Lifting pump", "Nitrogen unit", "Jetting unit", "Air loader"):
                certs.append({"name": "Pressure inspection", "expiry_date": iso(today + timedelta(days=rnd.randint(70, 330))), "file_url": None})
            if category in ("Nitrogen unit", "Jetting unit"):
                certs.append({"name": "Calibration certificate", "expiry_date": iso(today + timedelta(days=rnd.randint(75, 400))), "file_url": None})
            equipment.append({"_id": uid(), "name": f"{label} {NAME_SUFFIX[k % len(NAME_SUFFIX)]}{n:02d}", "category": category,
                              "serial": f"GPP-{category[:3].upper()}-{1000 + n}", "branch": branch, "status": "available",
                              "purchase_cost": float(cost), "photos": [], "run_hours": float(run), "service_interval_hours": float(interval),
                              "last_service_hours": float(last), "certificates": certs, "current_job_id": None, "current_rental_id": None,
                              "_rate": _rate})
    # deliberate blocking cases (storekeeper demo)
    flood = [e for e in equipment if e["category"] == "Flooding pump"]
    nitro = [e for e in equipment if e["category"] == "Nitrogen unit"]
    jet = [e for e in equipment if e["category"] == "Jetting unit"]
    lift = [e for e in equipment if e["category"] == "Lifting pump"]
    flood[0]["certificates"][0]["expiry_date"] = iso(today - timedelta(days=12))             # EXPIRED inspection
    flood[0]["name"] = "High-pressure flooding pump A01 (inspection expired)"
    nitro[1]["certificates"][0]["expiry_date"] = iso(today - timedelta(days=4))               # EXPIRED
    jet[0]["run_hours"], jet[0]["last_service_hours"] = jet[0]["service_interval_hours"] + 120, 0.0   # SERVICE OVERDUE
    lift[0]["run_hours"], lift[0]["last_service_hours"] = lift[0]["service_interval_hours"] + 35, 0.0
    flood[2]["certificates"][0]["expiry_date"] = iso(today + timedelta(days=21))              # expiring soon (amber)
    # clean OK pump for the happy-path demo
    flood[1]["name"] = "High-pressure flooding pump B02 (ready)"
    flood[1]["run_hours"], flood[1]["last_service_hours"] = 120.0, 0.0
    flood[1]["certificates"][0]["expiry_date"] = iso(today + timedelta(days=300))
    flood[1]["branch"] = "Port Harcourt HQ"
    data["equipment"] = equipment

    # ---- Rentals: open ones (deployed), a few overdue, plus history ------------------------
    rentals: list[dict[str, Any]] = []
    blocked_ids = {flood[0]["_id"], nitro[1]["_id"], jet[0]["_id"], lift[0]["_id"], flood[1]["_id"]}
    candidates = [e for e in equipment if e["_id"] not in blocked_ids]
    rnd.shuffle(candidates)
    deployed = candidates[:15]
    maint = candidates[15:18]
    transit = candidates[18:19]
    for e in maint:
        e["status"] = "maintenance"
    for e in transit:
        e["status"] = "in_transit"
    for j, e in enumerate(deployed):
        p = projects[j % len(projects)]
        start = today - timedelta(days=rnd.randint(5, 40))
        expected = today + timedelta(days=rnd.randint(5, 40)) if j not in (2, 7) else today - timedelta(days=rnd.randint(3, 9))  # two overdue returns
        r = {"_id": uid(), "equipment_id": e["_id"], "equipment_name": e["name"], "client_id": p["client_id"], "project_id": p["_id"],
             "rate_type": "daily", "rate": float(e["_rate"]), "start_date": iso(start), "expected_return": iso(expected), "actual_return": None,
             "income": 0.0, "receiver_name": rnd.choice(FIRST) + " " + rnd.choice(LAST), "condition_out": {"notes": "Good condition"},
             "handover_photos": [], "signature_url": None, "issued_by": {"id": users[4]["_id"], "name": users[4]["name"]},
             "created_at": start.isoformat() + "T08:00:00+00:00", "run_hours_out": e["run_hours"]}
        rentals.append(r)
        e["status"], e["current_job_id"], e["current_rental_id"] = "deployed", p["_id"], r["_id"]
    for e in rnd.sample(equipment, 22):  # closed rentals so income per item has history
        p = rnd.choice(projects)
        start = today - timedelta(days=rnd.randint(70, 240))
        days = rnd.randint(7, 45)
        ret = start + timedelta(days=days)
        rentals.append({"_id": uid(), "equipment_id": e["_id"], "equipment_name": e["name"], "client_id": p["client_id"], "project_id": p["_id"],
                        "rate_type": "daily", "rate": float(e["_rate"]), "start_date": iso(start), "expected_return": iso(ret), "actual_return": iso(ret),
                        "income": float(e["_rate"] * (days + 1)), "receiver_name": rnd.choice(FIRST) + " " + rnd.choice(LAST),
                        "condition_out": {}, "handover_photos": [], "signature_url": None,
                        "issued_by": {"id": users[4]["_id"], "name": users[4]["name"]}, "created_at": start.isoformat() + "T08:00:00+00:00"})
    data["rentals"] = rentals
    data["maintenance"] = [{"_id": uid(), "equipment_id": e["_id"], "equipment_name": e["name"], "type": "service", "description": "Scheduled service",
                            "scheduled_date": iso(today - timedelta(days=2)), "cost": 450_000.0, "status": "open", "created_by": users[4]["name"],
                            "created_at": today.isoformat() + "T08:00:00+00:00"} for e in maint]
    data["fuel_logs"] = []
    for e in deployed[:8]:
        for _ in range(rnd.randint(1, 3)):
            lit = rnd.randint(80, 400)
            data["fuel_logs"].append({"_id": uid(), "equipment_id": e["_id"], "equipment_name": e["name"], "project_id": e["current_job_id"], "litres": float(lit),
                                      "cost": float(lit * 1100), "date": iso(today - timedelta(days=rnd.randint(1, 25))), "station": "Placeholder Fuel Depot",
                                      "logged_by": users[3]["name"], "created_at": today.isoformat() + "T09:00:00+00:00"})

    # ---- Invoices (25) across ageing buckets -----------------------------------------------
    invoices: list[dict[str, Any]] = []
    ages = [5, 12, 20, 28, 33, 41, 49, 57, 64, 70, 78, 85, 92, 98, 105, 115, 130, 150, 18, 38, 72, 101, 200, 60, 90]
    for k, age in enumerate(ages):
        cl = clients[k % len(clients)]
        p = [x for x in projects if x["client_id"] == cl["_id"]]
        issue = today - timedelta(days=age)
        amount = float(rnd.choice([4_500_000, 8_200_000, 12_000_000, 18_500_000, 26_000_000, 35_000_000]))
        status, paid = "sent", 0.0
        if k in (3, 11, 19):
            status, paid = "paid", amount
        elif k in (7, 15):
            status, paid = "part_paid", round(amount * 0.4, 2)
        invoices.append({"_id": uid(), "client_id": cl["_id"], "project_id": p[0]["_id"] if p else None, "number": f"INV-{2026}{k + 1:03d}",
                         "amount": amount, "paid_amount": paid, "issue_date": iso(issue), "due_date": iso(issue + timedelta(days=cl["payment_terms_days"] // 2)),
                         "status": status, "vat_included": True, "reminders": [], "created_at": issue.isoformat() + "T09:00:00+00:00"})
    data["invoices"] = invoices
    data["payables"] = [{"_id": uid(), "vendor": v, "amount": float(a), "due_date": iso(today + timedelta(days=d)), "description": desc,
                         "status": "unpaid", "created_at": today.isoformat() + "T09:00:00+00:00"} for v, a, d, desc in [
        ("Placeholder Steel Supplies", 6_400_000, -10, "Flange stock"), ("Placeholder Fuel Depot", 3_900_000, 5, "Diesel"),
        ("Placeholder Logistics Ltd", 2_250_000, 12, "Haulage"), ("Placeholder Safety Gear", 1_700_000, 19, "PPE"),
        ("Placeholder Lubricants", 980_000, 26, "Oils and filters"), ("Placeholder Hose Makers", 8_100_000, 38, "Hose assemblies"),
        ("Placeholder Calibration Lab", 1_150_000, 45, "Calibration"), ("Placeholder Rent Agent", 4_800_000, 52, "Yard rent")]]

    # ---- Expenses in every approval state, with costs sized to hit each project's ratio ----
    expenses: list[dict[str, Any]] = []

    def exp(requester, project, category, amount, vendor, status, days_ago, approver="finance", flags=None, trail=None):
        expenses.append({"_id": uid(), "requester": {"id": requester["_id"], "name": requester["name"], "role": requester["role"]},
                         "project_id": project["_id"] if project else None, "category": category, "amount": float(amount), "currency": "NGN",
                         "amount_ngn": float(amount), "usd_rate": None, "vendor": vendor, "date": iso(today - timedelta(days=days_ago)),
                         "receipt_url": None, "notes": None, "status": status, "required_approver": approver, "approval_trail": trail or [],
                         "flags": flags or [], "created_at": (today - timedelta(days=days_ago)).isoformat() + "T10:00:00+00:00"})

    fin_u, md_u, sup_u, store_u = users[2], users[0], users[3], users[4]

    def trail(by, decision, comment=None):
        return [{"user_id": by["_id"], "name": by["name"], "role": by["role"], "decision": decision, "comment": comment,
                 "timestamp": today.isoformat() + "T12:00:00+00:00"}]

    for p in projects:  # approved spend giving the target cost ratio
        target = p["budget"] * p["_ratio"]
        chunks = 5
        for c in range(chunks):
            amt = round(target / chunks / 1000) * 1000
            big = amt > 500_000
            exp(sup_u, p, rnd.choice(["materials", "labour", "transport", "maintenance"]), amt, f"Placeholder Vendor {c + 1}", "approved",
                rnd.randint(3, 50), approver="md" if big else "finance", trail=trail(md_u if big else fin_u, "approved"))
    exp(sup_u, projects[0], "fuel", 185_000, "Placeholder Fuel Depot", "pending", 1)
    exp(store_u, projects[1], "transport", 240_000, "Placeholder Logistics Ltd", "pending", 1)
    exp(sup_u, projects[2], "equipment", 3_400_000, "Placeholder Compressor Hire", "pending", 1, approver="md")
    exp(sup_u, projects[3], "materials", 5_900_000, "Placeholder Steel Supplies", "pending", 2, approver="md")
    exp(store_u, projects[5], "meals", 95_000, "Placeholder Caterers", "rejected", 6, trail=trail(fin_u, "rejected", "No receipt attached"))
    exp(sup_u, projects[4], "fuel", 52_000, "Placeholder Fuel Depot", "pending", 0)
    exp(store_u, projects[4], "fuel", 52_000, "Placeholder Fuel Depot", "pending", 0, flags=["possible duplicate"])
    exp(sup_u, projects[0], "fuel", 980_000, "Placeholder Fuel Depot", "pending", 0, approver="md", flags=["unusually high"])
    data["expenses"] = expenses

    # ---- 60 days of daily field reports + a few incidents (Phase 6) ------------------------
    reports: list[dict[str, Any]] = []
    sup = users[3]
    issue_pool = ["Delay: waiting for client permit to work", "Hose leak on connection, replaced", "Heavy rain stopped work for 3 hours",
                  "Crane not available until afternoon", "Two crew members late due to transport", "Spare gasket shortage"]
    for p in projects:
        start = date.fromisoformat(p["start"])
        first = max(start, today - timedelta(days=59))
        days = (today - first).days + 1
        for k in range(days):
            d = first + timedelta(days=k)
            if d.weekday() == 6 and rnd.random() < 0.7:
                continue  # most Sundays off
            prog = round(p["progress"] * (k + 1) / days, 1)
            site = next(x for x in SITES if x["branch"] == p["branch"])
            reports.append({"_id": uid(), "project_id": p["_id"], "date": iso(d), "progress": prog, "headcount": rnd.randint(8, 34),
                            "equipment_used": [], "issues": rnd.choice(issue_pool) if rnd.random() < 0.12 else None, "notes": None, "photos": [],
                            "gps": {"lat": site["lat"] + rnd.uniform(-0.02, 0.02), "lng": site["lng"] + rnd.uniform(-0.02, 0.02), "accuracy": 15.0},
                            "created_offline": False, "author": {"id": sup["_id"], "name": sup["name"]}, "branch": p["branch"],
                            "received_at": d.isoformat() + "T17:00:00+00:00"})
        p["last_report_date"] = iso(today)
    data["daily_reports"] = reports
    data["incidents"] = [
        {"_id": uid(), "project_id": projects[3]["_id"], "severity": "high", "description": "Hose burst during pressure test, area cordoned, no injuries",
         "photos": [], "gps": None, "date": iso(today - timedelta(days=3)), "reporter": {"id": sup["_id"], "name": sup["name"]}, "received_at": today.isoformat() + "T08:00:00+00:00"},
        {"_id": uid(), "project_id": projects[0]["_id"], "severity": "low", "description": "Minor spill contained with absorbent pads",
         "photos": [], "gps": None, "date": iso(today - timedelta(days=11)), "reporter": {"id": sup["_id"], "name": sup["name"]}, "received_at": today.isoformat() + "T08:00:00+00:00"},
        {"_id": uid(), "project_id": projects[1]["_id"], "severity": "medium", "description": "Near miss: unsecured flange during lifting",
         "photos": [], "gps": None, "date": iso(today - timedelta(days=20)), "reporter": {"id": sup["_id"], "name": sup["name"]}, "received_at": today.isoformat() + "T08:00:00+00:00"},
    ]

    # ---- 60 days of attendance + assignments (Phase 7) --------------------------------------
    attendance: list[dict[str, Any]] = []
    site_for = {st["name"]: st for st in SITES}
    for st in staff:
        site = site_for.get(st["home_site"]) or SITES[0]
        for back in range(59, -1, -1):
            d = today - timedelta(days=back)
            if d.weekday() == 6:
                continue  # Sundays off
            roll = rnd.random()
            if back == 0:
                roll = rnd.random() * 0.97  # keep today's board lively: mostly present, a few absent
            if roll > 0.93:
                continue  # absent
            minute = rnd.randint(25, 85) if rnd.random() > 0.12 else rnd.randint(100, 150)  # ~12% late (after 08:15)
            hh, mm = divmod(6 * 60 + minute, 60)
            local = f"{d.isoformat()}T{hh:02d}:{mm:02d}:00"
            flags: list[str] = []
            status = "verified"
            if rnd.random() < 0.03:
                flags = [rnd.choice(["face_mismatch", "outside_site", "suspicious_gps"])]
                status = rnd.choice(["flagged", "verified", "verified", "rejected"]) if back > 0 else "flagged"
            ci = {"time": local + "+01:00", "local_time": local, "server_time": local + "+01:00", "lat": site["lat"] + rnd.uniform(-0.0008, 0.0008),
                  "lng": site["lng"] + rnd.uniform(-0.0008, 0.0008), "accuracy": float(rnd.randint(5, 30)), "selfie_url": None,
                  "match_score": round(rnd.uniform(0.25, 0.45), 3) if st["user_id"] else None, "flags": flags,
                  "source": "self" if st["user_id"] else "manual", "site_name": site["name"], "distance_m": float(rnd.randint(5, 120)), "client_id": uid(), "offline": False}
            if not st["user_id"]:
                ci["manual_by"] = sup["name"]
                ci["note"] = "Entered by supervisor (no phone login)"
            co = None
            if back > 0:
                co = {**ci, "time": f"{d.isoformat()}T17:{rnd.randint(0, 40):02d}:00+01:00", "local_time": f"{d.isoformat()}T17:{rnd.randint(0, 40):02d}:00", "client_id": uid(), "flags": []}
            attendance.append({"_id": uid(), "staff_id": st["_id"], "staff_name": st["name"], "branch": st["branch"], "date": iso(d), "clock_in": ci, "clock_out": co,
                               "status": status, "review": None, "created_at": local + "+01:00"})
    # make sure the supervisor's review queue is not empty today
    todays = [a for a in attendance if a["date"] == iso(today) and a["clock_in"]["source"] == "self" and a["status"] == "verified"]
    for a, fl in zip(todays[1:3], (["outside_site"], ["face_mismatch"])):
        a["status"], a["clock_in"]["flags"] = "flagged", fl
        if fl == ["outside_site"]:
            a["clock_in"]["distance_m"] = 1850.0
        else:
            a["clock_in"]["match_score"] = 0.83
    data["attendance"] = attendance
    # one registration waiting for HR approval (synthetic numbers, real ones are computed in the browser)
    staff[4]["face_template"] = [[round(rnd.uniform(-0.2, 0.2), 4) for _ in range(128)] for _ in range(3)]
    staff[4]["face_status"], staff[4]["face_consent"] = "pending", {"given": True, "date": today.isoformat() + "T08:00:00+00:00", "purpose": "Attendance verification only"}
    data["assignments"] = []
    for st in staff[6:20]:
        req_now = ["H2S"] if st["position"] in ("Pump operator", "Jetting operator", "Technician") else []
        held = {c["type"]: c["expiry"] for c in st["certifications"]}
        if any(held.get(r, "") < iso(today) for r in req_now):
            continue  # seed data must obey the same certificate rule the API enforces
        p = projects[(staff.index(st)) % len(projects)]
        data["assignments"].append({"_id": uid(), "staff_id": st["_id"], "staff_name": st["name"], "project_id": p["_id"], "project_name": p["name"], "role": st["position"],
                                    "required_certs": ["H2S"] if st["position"] in ("Pump operator", "Jetting operator", "Technician") else [],
                                    "start": p["start"], "end": None, "created_by": users[5]["name"], "created_at": today.isoformat() + "T08:00:00+00:00"})

    for p in projects:
        p.pop("_ratio")
    for e in equipment:
        e.pop("_rate")
    data["settings"] = [{"_id": "main", "approval_limits": {"finance_max": 500_000}, "usd_rate": 1500.0, "branches": BRANCHES,
                         "notification_schedule": {"daily_summary": "19:00", "scans": "07:00"}, "shift_start_hour": 8, "late_grace_minutes": 15,
                         "payroll_monthly": 12_000_000, "opening_cash": 85_000_000.0}]
    return data
