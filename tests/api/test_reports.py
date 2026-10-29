import uuid

from app.core.db import get_db


def report(world, **kw):
    b = {"id": str(uuid.uuid4()), "project_id": world["project"]["_id"], "progress": 45, "headcount": 12,
         "issues": None, "photos": [], "gps": {"lat": 4.8, "lng": 7.0, "accuracy": 12}}
    b.update(kw)
    return b


async def test_report_is_idempotent_exactly_once(client, auth, world):
    body = report(world, created_offline=True)
    first = await client.post("/reports", json=body, headers=auth("supervisor"))
    assert first.status_code == 201 and first.json()["duplicate"] is False
    again = await client.post("/reports", json=body, headers=auth("supervisor"))
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert await get_db().daily_reports.count_documents({"project_id": world["project"]["_id"]}) == 1
    audits = (await client.get("/audit", headers=auth("md"), params={"entity": "report"})).json()
    assert audits["total"] == 1 and "synced from offline" in audits["items"][0]["summary"]


async def test_report_updates_project_progress_and_summary(client, auth, world):
    await client.post("/reports", json=report(world, progress=55, date="2026-10-20"), headers=auth("supervisor"))
    await client.post("/reports", json=report(world, progress=50, date="2026-10-10"), headers=auth("supervisor"))  # older: must not lower it
    p = (await client.get(f"/projects/{world['project']['_id']}", headers=auth("md"))).json()
    assert p["progress"] == 55
    s = (await client.get(f"/projects/{world['project']['_id']}/summary", headers=auth("md"))).json()
    assert "costs" in s and "last_7_days" in s


async def test_supervisor_summary_has_no_money(client, auth, world):
    s = (await client.get(f"/projects/{world['project']['_id']}/summary", headers=auth("supervisor"))).json()
    assert "costs" not in s and "budget" not in s["project"] and "cost" not in s["project"]


async def test_high_incident_notifies_md_once(client, auth, world):
    body = {"id": str(uuid.uuid4()), "project_id": world["project"]["_id"], "severity": "high", "description": "Hose burst, no injuries"}
    assert (await client.post("/incidents", json=body, headers=auth("supervisor"))).status_code == 201
    assert (await client.post("/incidents", json=body, headers=auth("supervisor"))).status_code == 200
    notes = (await client.get("/notifications", headers=auth("md"))).json()
    assert sum(1 for n in notes["items"] if n["title"] == "HIGH severity incident") == 1
    low = {**body, "id": str(uuid.uuid4()), "severity": "low"}
    await client.post("/incidents", json=low, headers=auth("supervisor"))
    notes = (await client.get("/notifications", headers=auth("md"))).json()
    assert sum(1 for n in notes["items"] if "incident" in n["title"].lower()) == 1


async def test_report_roles_and_validation(client, auth, world):
    assert (await client.post("/reports", json=report(world), headers=auth("storekeeper"))).status_code == 403
    assert (await client.post("/reports", json=report(world, progress=150), headers=auth("supervisor"))).status_code == 422
    assert (await client.post("/reports", json=report(world, project_id="nope"), headers=auth("supervisor"))).status_code == 422
