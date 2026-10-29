from datetime import date, timedelta

from app.core.common import new_id
from app.core.db import get_db
from app.jobs.scheduler import daily_summary_job, morning_scan_job


async def test_dashboard_requires_management_role(client, auth):
    assert (await client.get("/dashboard", headers=auth("md"))).status_code == 200
    for role in ("supervisor", "storekeeper", "hr"):
        assert (await client.get("/dashboard", headers=auth(role))).status_code == 403


async def test_dashboard_reflects_checkout_immediately(client, auth, world):
    before = (await client.get("/dashboard", headers=auth("md"))).json()
    assert before["equipment_counts"]["deployed"] == 0
    r = await client.post(f"/equipment/{world['ok']['_id']}/checkout", headers=auth("storekeeper"),
                          json={"project_id": world["project"]["_id"], "client_id": world["client"]["_id"], "rate": 1000, "receiver_name": "X"})
    assert r.status_code == 201
    after = (await client.get("/dashboard", headers=auth("md"))).json()
    assert after["equipment_counts"]["deployed"] == 1
    assert after["utilisation_pct"] > 0
    assert any("check-out" == a["action"] for a in after["recent_activity"])


async def test_alerts_include_expired_cert_and_service_overdue(client, auth, world):
    d = (await client.get("/dashboard", headers=auth("md"))).json()
    types = {a["type"] for a in d["alerts"]}
    assert {"equipment_certificate", "service_overdue"} <= types
    assert d["alert_counts"]["high"] >= 2


async def test_pending_approval_shows_for_md_and_project_colour(client, auth, world):
    await client.post("/expenses", json={"category": "materials", "amount": 3_000_000, "vendor": "V"}, headers=auth("supervisor"))
    d = (await client.get("/dashboard", headers=auth("md"))).json()
    assert len(d["pending_approvals"]) == 1
    assert d["active_projects"][0]["colour"] in ("GREEN", "AMBER", "RED")


async def test_branch_filter(client, auth, world):
    d = (await client.get("/dashboard", params={"branch": "Warri"}, headers=auth("md"))).json()
    assert d["equipment_total"] == 0 and d["active_projects"] == []


async def test_scheduler_jobs_notify_md(client, auth, world):
    assert await daily_summary_job() == 1
    assert await morning_scan_job() >= 1
    notes = (await client.get("/notifications", headers=auth("md"))).json()
    assert {"Daily summary", "Morning scan"} <= {n["title"] for n in notes["items"]}


async def test_summary_endpoint_uses_real_numbers(client, auth, world):
    r = (await client.get("/dashboard/summary", headers=auth("md"))).json()
    assert "Equipment:" in r["text"] and "available" in r["text"]
