from app.core.db import get_db


def checkout_body(world, **kw):
    b = {"client_id": world["client"]["_id"], "project_id": world["project"]["_id"], "rate_type": "daily",
         "rate": 50_000, "receiver_name": "Emeka Okafor", "condition": {"hoses": True},
         "handover_photos": ["http://x/1.jpg"], "signature_url": "http://x/sig.png"}
    b.update(kw)
    return b


async def test_expired_certificate_blocks_checkout_with_reason(client, auth, world):
    r = await client.post(f"/equipment/{world['expired']['_id']}/checkout", json=checkout_body(world), headers=auth("storekeeper"))
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert any("Pressure inspection" in x and "expired" in x for x in detail["reasons"])
    eq = await get_db().equipment.find_one({"_id": world["expired"]["_id"]})
    assert eq["status"] == "available"  # nothing changed


async def test_service_overdue_blocks_checkout(client, auth, world):
    r = await client.post(f"/equipment/{world['overdue']['_id']}/checkout", json=checkout_body(world), headers=auth("storekeeper"))
    assert r.status_code == 409
    assert any("Service overdue" in x for x in r.json()["detail"]["reasons"])


async def test_readiness_endpoint_green_and_red(client, auth, world):
    ok = (await client.get(f"/equipment/{world['ok']['_id']}/readiness", headers=auth("storekeeper"))).json()
    assert ok["ok"] is True and ok["reasons"] == []
    bad = (await client.get(f"/equipment/{world['overdue']['_id']}/readiness", headers=auth("storekeeper"))).json()
    assert bad["ok"] is False and bad["reasons"]


async def test_checkout_success_deploys_creates_rental_and_audits(client, auth, world):
    eid = world["ok"]["_id"]
    r = await client.post(f"/equipment/{eid}/checkout", json=checkout_body(world), headers=auth("storekeeper"))
    assert r.status_code == 201
    assert r.json()["receiver_name"] == "Emeka Okafor"
    eq = (await client.get(f"/equipment/{eid}", headers=auth("md"))).json()
    assert eq["status"] == "deployed"
    assert eq["current_project_name"] == "Demo Project X"
    audit = (await client.get("/audit", headers=auth("md"), params={"action": "check-out"})).json()
    assert audit["total"] == 1
    # the MD is told
    notes = (await client.get("/notifications", headers=auth("md"))).json()
    assert any("deployed" in n["title"].lower() for n in notes["items"])


async def test_cannot_checkout_twice(client, auth, world):
    eid = world["ok"]["_id"]
    await client.post(f"/equipment/{eid}/checkout", json=checkout_body(world), headers=auth("storekeeper"))
    again = await client.post(f"/equipment/{eid}/checkout", json=checkout_body(world), headers=auth("storekeeper"))
    assert again.status_code == 409
    assert any("already deployed" in x for x in again.json()["detail"]["reasons"])


async def test_supervisor_can_read_but_not_checkout(client, auth, world):
    eid = world["ok"]["_id"]
    assert (await client.get(f"/equipment/{eid}", headers=auth("supervisor"))).status_code == 200
    r = await client.post(f"/equipment/{eid}/checkout", json=checkout_body(world), headers=auth("supervisor"))
    assert r.status_code == 403


async def test_finance_cannot_read_equipment(client, auth, world):
    assert (await client.get("/equipment", headers=auth("finance"))).status_code == 403


async def test_checkin_updates_hours_status_and_income(client, auth, world):
    eid = world["ok"]["_id"]
    await client.post(f"/equipment/{eid}/checkout", json=checkout_body(world, start_date="2026-01-01"), headers=auth("storekeeper"))
    r = await client.post(f"/equipment/{eid}/checkin", json={"return_hours": 180, "condition": {"ok": True}}, headers=auth("storekeeper"))
    assert r.status_code == 200
    body = r.json()
    assert body["new_status"] == "available"
    assert body["rental"]["income"] > 0
    eq = (await client.get(f"/equipment/{eid}", headers=auth("md"))).json()
    assert eq["run_hours"] == 180 and eq["status"] == "available" and eq["total_rental_income"] > 0


async def test_checkin_flagged_goes_to_maintenance_and_rejects_lower_hours(client, auth, world):
    eid = world["ok"]["_id"]
    await client.post(f"/equipment/{eid}/checkout", json=checkout_body(world), headers=auth("storekeeper"))
    bad = await client.post(f"/equipment/{eid}/checkin", json={"return_hours": 50}, headers=auth("storekeeper"))
    assert bad.status_code == 422
    r = await client.post(f"/equipment/{eid}/checkin", json={"return_hours": 120, "flag_for_maintenance": True}, headers=auth("storekeeper"))
    assert r.json()["new_status"] == "maintenance"


async def test_maintenance_complete_resets_service_counter(client, auth, world):
    eid = world["overdue"]["_id"]
    m = (await client.post("/maintenance", json={"equipment_id": eid, "type": "service", "start_now": True}, headers=auth("storekeeper"))).json()
    assert (await client.get(f"/equipment/{eid}", headers=auth("md"))).json()["status"] == "maintenance"
    done = await client.patch(f"/maintenance/{m['id']}/complete", json={"notes": "oil change"}, headers=auth("storekeeper"))
    assert done.status_code == 200
    eq = (await client.get(f"/equipment/{eid}", headers=auth("md"))).json()
    assert eq["last_service_hours"] == 700 and eq["status"] == "available" and eq["service_overdue"] is False
    # now deployable
    assert (await client.get(f"/equipment/{eid}/readiness", headers=auth("md"))).json()["ok"] is True


async def test_qr_png_contains_id_endpoint(client, auth, world):
    r = await client.get(f"/equipment/{world['ok']['_id']}/qr", headers=auth("storekeeper"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"


async def test_availability_marks_booked_items(client, auth, world):
    eid = world["ok"]["_id"]
    await client.post(f"/equipment/{eid}/checkout", json=checkout_body(world, start_date="2026-11-01", expected_return="2026-11-10"), headers=auth("storekeeper"))
    rows = (await client.get("/equipment/availability", params={"from": "2026-11-05", "to": "2026-11-06"}, headers=auth("md"))).json()
    item = next(x for x in rows if x["id"] == eid)
    assert item["free"] is False and item["bookings"]


async def test_duplicate_serial_rejected_and_fuel_log(client, auth, world):
    body = {"name": "Dup", "category": "Hose", "serial": "SN-OK", "branch": "Warri"}
    assert (await client.post("/equipment", json=body, headers=auth("storekeeper"))).status_code == 409
    eid = world["ok"]["_id"]
    f = await client.post("/fuel-logs", json={"equipment_id": eid, "project_id": world["project"]["_id"], "litres": 100, "cost": 150000}, headers=auth("supervisor"))
    assert f.status_code == 201
    totals = (await client.get("/fuel-logs", headers=auth("md"), params={"project_id": world["project"]["_id"]})).json()
    assert totals["total_cost"] == 150000
