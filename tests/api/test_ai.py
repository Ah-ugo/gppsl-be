"""AI assistant API tests. No GOOGLE_API_KEY in tests, so these exercise the data-only path (the facts are the same)."""
from datetime import date, timedelta

from app.core.common import new_id
from app.core.db import get_db


async def _invoice(client_id, number, amount, age, paid=0.0, status="sent"):
    await get_db().invoices.insert_one({
        "_id": new_id(), "client_id": client_id, "number": number, "amount": amount, "paid_amount": paid,
        "issue_date": (date.today() - timedelta(days=age)).isoformat(), "status": status})


async def _two_clients(world):
    db = get_db()
    other = {"_id": new_id(), "name": "Other Client B", "payment_terms_days": 30}
    await db.clients.insert_one(other)
    await _invoice(world["client"]["_id"], "INV-1", 1_000_000, 75)            # over 60
    await _invoice(world["client"]["_id"], "INV-2", 500_000, 61, paid=100_000)  # over 60, part paid
    await _invoice(world["client"]["_id"], "INV-3", 900_000, 40)              # not over 60
    await _invoice(other["_id"], "INV-4", 2_000_000, 120)                     # over 60
    await _invoice(other["_id"], "INV-5", 700_000, 200, paid=700_000, status="paid")  # paid: excluded
    return other


async def test_who_owes_over_60_days_matches_data_with_sources(client, auth, world):
    other = await _two_clients(world)
    r = await client.post("/ai/chat", json={"question": "Which clients owe us over 60 days?"}, headers=auth("md"))
    assert r.status_code == 200
    body = r.json()
    rows = {row[0]: row for row in body["table"]["rows"]}
    assert set(rows) == {"Demo Client A", "Other Client B"}
    assert rows["Demo Client A"][2] == "₦1,400,000"   # 1,000,000 + (500,000 - 100,000)
    assert rows["Other Client B"][2] == "₦2,000,000"
    assert "₦3,400,000" in body["answer"]
    labels = {s["label"] for s in body["sources"]}
    assert {"Demo Client A", "Other Client B"} <= labels
    assert any(s["type"] == "invoice" for s in body["sources"])
    assert not any("INV-3" in s["label"] or "INV-5" in s["label"] for s in body["sources"])
    assert body["mode"] == "data" and body["note"]


async def test_unknown_question_says_not_found(client, auth, world):
    r = (await client.post("/ai/chat", json={"question": "What is the meaning of purple?"}, headers=auth("md"))).json()
    assert "couldn't find" in r["answer"].lower()
    assert r["sources"] == []


async def test_role_cannot_ask_for_money_data(client, auth, world):
    await _two_clients(world)
    r = (await client.post("/ai/chat", json={"question": "Which clients owe us over 60 days?"}, headers=auth("supervisor"))).json()
    assert "not allowed" in r["answer"]
    assert r["table"] is None and r["sources"] == []
    assert "₦" not in r["answer"]


async def test_equipment_question_lists_status(client, auth, world):
    r = (await client.post("/ai/chat", json={"question": "Where is Pump OK?"}, headers=auth("md"))).json()
    assert "Pump OK" in r["answer"]
    assert any(s["type"] == "equipment" for s in r["sources"])


async def test_project_summary_hides_cost_from_supervisor(client, auth, world):
    pid = world["project"]["_id"]
    md = (await client.get(f"/ai/summary/project/{pid}", headers=auth("md"))).json()
    sup = (await client.get(f"/ai/summary/project/{pid}", headers=auth("supervisor"))).json()
    assert "budget" in md["text"] and "budget" not in sup["text"]
    assert (await client.get(f"/ai/summary/project/{pid}", headers=auth("hr"))).status_code == 403


async def test_daily_summary_md_only(client, auth, world):
    r = (await client.get("/ai/summary/daily", headers=auth("md"))).json()
    assert r["source"] == "data" and "Equipment:" in r["text"]
    assert (await client.get("/ai/summary/daily", headers=auth("supervisor"))).status_code == 403


async def test_requires_login(client):
    assert (await client.post("/ai/chat", json={"question": "hello there"})).status_code in (401, 403)
