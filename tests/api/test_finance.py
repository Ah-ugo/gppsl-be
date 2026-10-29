from datetime import date, timedelta

from app.core.common import new_id
from app.core.db import get_db


async def raise_expense(client, auth, role, amount, vendor="Vendor A", **kw):
    body = {"category": "materials", "amount": amount, "vendor": vendor, "date": "2026-10-20", **kw}
    return await client.post("/expenses", json=body, headers=auth(role))


async def test_below_limit_routes_to_finance_above_to_md(client, auth):
    low = (await raise_expense(client, auth, "supervisor", 100_000)).json()
    high = (await raise_expense(client, auth, "supervisor", 2_000_000, vendor="Vendor B")).json()
    assert low["required_approver"] == "finance"
    assert high["required_approver"] == "md"


async def test_limit_is_configurable_in_settings(client, auth):
    await client.patch("/settings", json={"approval_limits": {"finance_max": 50_000}}, headers=auth("md"))
    e = (await raise_expense(client, auth, "supervisor", 100_000)).json()
    assert e["required_approver"] == "md"


async def test_md_approves_high_value_and_audit_records_it(client, auth, users):
    e = (await raise_expense(client, auth, "supervisor", 2_000_000)).json()
    # finance cannot decide an MD-level expense
    wrong = await client.post(f"/expenses/{e['id']}/approve", json={}, headers=auth("finance"))
    assert wrong.status_code == 403
    ok = await client.post(f"/expenses/{e['id']}/approve", json={"comment": "Go ahead"}, headers=auth("md"))
    assert ok.status_code == 200
    body = ok.json()
    assert body["status"] == "approved"
    assert body["approval_trail"][0]["role"] == "md" and body["approval_trail"][0]["comment"] == "Go ahead"
    audit = (await client.get("/audit", headers=auth("md"), params={"action": "approve", "entity": "expense"})).json()
    assert audit["total"] == 1 and "Approved expense" in audit["items"][0]["summary"]
    # requester is notified
    notes = (await client.get("/notifications", headers=auth("supervisor"))).json()
    assert any(n["title"] == "Expense approved" for n in notes["items"])


async def test_cannot_decide_twice_or_own_expense(client, auth):
    e = (await raise_expense(client, auth, "finance", 10_000)).json()
    assert (await client.post(f"/expenses/{e['id']}/approve", json={}, headers=auth("finance"))).status_code == 403  # own
    e2 = (await raise_expense(client, auth, "supervisor", 10_000, vendor="Z")).json()
    assert (await client.post(f"/expenses/{e2['id']}/approve", json={}, headers=auth("finance"))).status_code == 200
    assert (await client.post(f"/expenses/{e2['id']}/approve", json={}, headers=auth("finance"))).status_code == 409


async def test_reject_requires_reason(client, auth):
    e = (await raise_expense(client, auth, "supervisor", 10_000)).json()
    assert (await client.post(f"/expenses/{e['id']}/reject", json={}, headers=auth("finance"))).status_code == 422
    r = await client.post(f"/expenses/{e['id']}/reject", json={"comment": "No receipt"}, headers=auth("finance"))
    assert r.status_code == 200 and r.json()["status"] == "rejected"


async def test_supervisor_cannot_approve_or_see_inbox(client, auth):
    e = (await raise_expense(client, auth, "storekeeper", 10_000)).json()
    assert (await client.post(f"/expenses/{e['id']}/approve", json={}, headers=auth("supervisor"))).status_code == 403
    assert (await client.get("/expenses/pending", headers=auth("supervisor"))).status_code == 403


async def test_duplicate_and_unusually_high_flags(client, auth):
    await raise_expense(client, auth, "supervisor", 20_000, vendor="Shell Depot")
    dup = (await raise_expense(client, auth, "storekeeper", 20_000, vendor="shell depot")).json()
    assert "possible duplicate" in dup["flags"]
    await raise_expense(client, auth, "supervisor", 20_000, vendor="Other", date="2026-10-21")
    high = (await raise_expense(client, auth, "supervisor", 100_000, vendor="Pricey", date="2026-10-22")).json()
    assert "unusually high" in high["flags"]


async def test_usd_expense_converted_with_rate(client, auth):
    await client.patch("/settings", json={"usd_rate": 1600}, headers=auth("md"))
    e = (await raise_expense(client, auth, "supervisor", 100, currency="USD")).json()
    assert e["amount_ngn"] == 160_000


async def test_expense_visibility(client, auth):
    await raise_expense(client, auth, "supervisor", 10_000)
    assert len((await client.get("/expenses", headers=auth("storekeeper"))).json()) == 0  # only own
    assert len((await client.get("/expenses", headers=auth("finance"))).json()) == 1


async def test_scan_is_labelled_mock_without_key(client, auth):
    r = await client.post("/expenses/scan", files={"file": ("r.jpg", b"fakeimage", "image/jpeg")}, headers=auth("storekeeper"))
    assert r.status_code == 200 and r.json()["source"] == "MOCK" and "MOCK" in r.json()["note"]


async def _inv(client_doc, days_old, amount, **kw):
    issue = date.today() - timedelta(days=days_old)
    d = {"_id": new_id(), "client_id": client_doc["_id"], "number": f"I{days_old}", "amount": amount, "paid_amount": 0,
         "issue_date": issue.isoformat(), "due_date": (issue + timedelta(days=30)).isoformat(), "status": "sent", "reminders": []}
    d.update(kw)
    await get_db().invoices.insert_one(d)
    return d


async def test_ageing_forecast_and_finance_only(client, auth, world):
    for age, amt in [(10, 100), (45, 200), (75, 300), (120, 400)]:
        await _inv(world["client"], age, amt)
    ag = (await client.get("/finance/ageing", headers=auth("finance"))).json()
    assert ag == {"0-30": 100, "31-60": 200, "61-90": 300, "90+": 400}
    fc = (await client.get("/finance/forecast", params={"weeks": 8}, headers=auth("md"))).json()
    assert len(fc) == 8
    # Acceptance 9: supervisor blocked from finance and MD-only endpoints
    for url in ("/finance/ageing", "/finance/forecast", "/finance/overview", "/invoices", "/payables", "/audit", "/expenses/pending"):
        assert (await client.get(url, headers=auth("supervisor"))).status_code == 403, url


async def test_reminder_is_sent_and_logged(client, auth, world):
    await get_db().clients.update_one({"_id": world["client"]["_id"]}, {"$set": {"email": "ap@client-a.example", "contact_name": "Ada"}})
    inv = await _inv(world["client"], 100, 500_000)
    draft = (await client.get(f"/invoices/{inv['_id']}/reminder-draft", headers=auth("finance"))).json()
    assert draft["to"] == "ap@client-a.example" and "100 days" in draft["body"]
    r = await client.post(f"/invoices/{inv['_id']}/remind", json={}, headers=auth("finance"))
    assert r.status_code == 200 and r.json()["status"] == "demo-logged"
    saved = await get_db().invoices.find_one({"_id": inv["_id"]})
    assert len(saved["reminders"]) == 1
    audit = (await client.get("/audit", headers=auth("md"), params={"action": "remind"})).json()
    assert audit["total"] == 1


async def test_pay_invoice_moves_it_out_of_ageing(client, auth, world):
    inv = await _inv(world["client"], 100, 1000)
    await client.post(f"/invoices/{inv['_id']}/pay", json={"amount": 400}, headers=auth("finance"))
    assert (await client.get("/finance/ageing", headers=auth("finance"))).json()["90+"] == 600
    await client.post(f"/invoices/{inv['_id']}/pay", json={}, headers=auth("finance"))
    assert (await client.get("/finance/ageing", headers=auth("finance"))).json()["90+"] == 0
