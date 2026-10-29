from datetime import datetime, timedelta, timezone

from app.core.db import get_db
from tests.conftest import clock_body, descriptor


async def test_matched_selfie_inside_radius_clocks_in_verified(client, auth, crew):
    r = await client.post("/attendance/clock-in", json=clock_body(), headers=auth("supervisor"))
    assert r.status_code == 201
    j = r.json()
    assert j["status"] == "verified" and j["flags"] == []
    assert "Emeka Okafor" in j["greeting"] and j["site_name"] == "PH Yard" and j["time"]
    assert j["match_score"] is not None and j["match_score"] < 0.6


async def test_outside_radius_is_flagged_not_rejected(client, auth, crew):
    r = await client.post("/attendance/clock-in", json=clock_body(lat=4.90, lng=7.20), headers=auth("supervisor"))
    assert r.status_code == 201
    assert r.json()["status"] == "flagged" and "outside_site" in r.json()["flags"]
    flagged = (await client.get("/attendance/flagged", headers=auth("supervisor"))).json()
    assert len(flagged) == 1


async def test_face_mismatch_flagged_never_auto_penalised(client, auth, crew):
    r = await client.post("/attendance/clock-in", json=clock_body(descriptor=[5.0] * 128), headers=auth("supervisor"))
    assert r.json()["status"] == "flagged" and "face_mismatch" in r.json()["flags"]
    rec = await get_db().attendance.find_one({})
    assert rec["status"] == "flagged"  # waits for a human, not rejected


async def test_poor_gps_and_time_drift_flags(client, auth, crew):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    r = await client.post("/attendance/clock-in", json=clock_body(accuracy=900, phone_time=old), headers=auth("supervisor"))
    assert {"suspicious_gps", "time_drift"} <= set(r.json()["flags"])


async def test_duplicate_clock_in_blocked_but_same_uuid_is_idempotent(client, auth, crew):
    body = clock_body()
    first = await client.post("/attendance/clock-in", json=body, headers=auth("supervisor"))
    again = await client.post("/attendance/clock-in", json=body, headers=auth("supervisor"))  # offline retry
    assert first.status_code == 201 and again.status_code == 200 and again.json()["duplicate"] is True
    other = await client.post("/attendance/clock-in", json=clock_body(), headers=auth("supervisor"))
    assert other.status_code == 409
    assert await get_db().attendance.count_documents({}) == 1


async def test_offline_clock_in_syncs_once_without_drift_flag(client, auth, crew):
    phone = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    body = clock_body(phone_time=phone, offline=True)
    r1 = await client.post("/attendance/clock-in", json=body, headers=auth("supervisor"))
    r2 = await client.post("/attendance/clock-in", json=body, headers=auth("supervisor"))
    assert "time_drift" not in r1.json()["flags"] and r2.json()["duplicate"] is True
    assert await get_db().attendance.count_documents({}) == 1
    rec = await get_db().attendance.find_one({})
    assert rec["clock_in"]["offline"] is True and rec["clock_in"]["server_time"] != rec["clock_in"]["time"]


async def test_no_face_registered_goes_to_review(client, auth, crew):
    r = await client.post("/attendance/clock-in", json=clock_body(), headers=auth("storekeeper"))
    assert r.json()["status"] == "flagged" and "no_face_template" in r.json()["flags"]


async def test_clock_out_and_supervisor_review(client, auth, crew):
    await client.post("/attendance/clock-in", json=clock_body(lat=4.9, lng=7.2), headers=auth("storekeeper"))
    rec = await get_db().attendance.find_one({})
    assert (await client.post(f"/attendance/{rec['_id']}/review", json={"decision": "reject"}, headers=auth("supervisor"))).status_code == 422
    ok = await client.post(f"/attendance/{rec['_id']}/review", json={"decision": "approve", "comment": "Was at client office"}, headers=auth("supervisor"))
    assert ok.status_code == 200 and ok.json()["status"] == "verified"
    out = await client.post("/attendance/clock-out", json=clock_body(), headers=auth("storekeeper"))
    assert out.status_code == 201
    assert (await client.post("/attendance/clock-out", json=clock_body(), headers=auth("storekeeper"))).status_code == 409


async def test_manual_clock_in_records_supervisor_name(client, auth, crew):
    r = await client.post("/attendance/manual", json={"staff_id": crew["store"]["_id"], "note": "Phone broke on site"}, headers=auth("supervisor"))
    assert r.status_code == 201
    ci = r.json()["clock_in"]
    assert ci["source"] == "manual" and ci["manual_by"] == "Test Supervisor" and r.json()["status"] == "verified"
    assert (await client.post("/attendance/manual", json={"staff_id": crew["store"]["_id"], "note": "again"}, headers=auth("supervisor"))).status_code == 409
    assert (await client.post("/attendance/manual", json={"staff_id": crew["sup"]["_id"], "note": "x y z"}, headers=auth("storekeeper"))).status_code == 403


async def test_assignment_refused_for_expired_h2s(client, auth, crew, world):
    body = {"staff_id": crew["store"]["_id"], "project_id": world["project"]["_id"], "required_certs": ["H2S"]}
    r = await client.post("/assignments", json=body, headers=auth("supervisor"))
    assert r.status_code == 409 and any("H2S" in x and "expired" in x for x in r.json()["detail"]["reasons"])
    ok = await client.post("/assignments", json={**body, "staff_id": crew["sup"]["_id"]}, headers=auth("supervisor"))
    assert ok.status_code == 201
    assert await get_db().assignments.count_documents({}) == 1


async def test_payroll_counts_verified_days_only(client, auth, crew):
    sid = crew["sup"]["_id"]
    ci = {"time": "x", "flags": []}
    await get_db().attendance.insert_many([
        {"_id": "a1", "staff_id": sid, "date": "2026-09-01", "status": "verified", "clock_in": ci},
        {"_id": "a2", "staff_id": sid, "date": "2026-09-02", "status": "verified", "clock_in": ci},
        {"_id": "a3", "staff_id": sid, "date": "2026-09-03", "status": "flagged", "clock_in": ci},
        {"_id": "a4", "staff_id": sid, "date": "2026-09-04", "status": "rejected", "clock_in": ci}])
    p = (await client.get("/payroll/summary", params={"month": "2026-09"}, headers=auth("finance"))).json()
    row = next(r for r in p["rows"] if r["staff_id"] == sid)
    assert row["days_present"] == 2 and row["gross"] == 40000 and row["unverified_days_excluded"] == 2
    assert (await client.get("/payroll/summary", params={"month": "2026-09"}, headers=auth("supervisor"))).status_code == 403


async def test_face_registration_consent_approval_and_privacy(client, auth, users):
    db = get_db()
    await db.staff.insert_one({"_id": "s1", "user_id": users["hr"]["_id"], "name": "Hr Person", "branch": "Port Harcourt HQ", "face_template": [], "face_status": "none", "certifications": []})
    d = [descriptor(0.1), descriptor(0.11), descriptor(0.12)]
    assert (await client.post("/staff/me/face", json={"consent": False, "descriptors": d}, headers=auth("hr"))).status_code == 422
    assert (await client.post("/staff/me/face", json={"consent": True, "descriptors": d[:2]}, headers=auth("hr"))).status_code == 422
    assert (await client.post("/staff/me/face", json={"consent": True, "descriptors": d}, headers=auth("hr"))).status_code == 200
    assert (await client.post("/staff/s1/face/decision", json={"decision": "approve"}, headers=auth("supervisor"))).status_code == 403
    assert (await client.post("/staff/s1/face/decision", json={"decision": "approve"}, headers=auth("hr"))).status_code == 200
    listing = (await client.get("/staff", headers=auth("md"))).json()
    assert "face_template" not in listing[0] and listing[0]["face_registered"] is True  # descriptors never leave the server
    assert (await client.delete("/staff/me/face", headers=auth("hr"))).status_code == 200
    assert (await db.staff.find_one({"_id": "s1"}))["face_template"] == []


async def test_live_board_and_certificate_matrix(client, auth, crew):
    await client.post("/attendance/clock-in", json=clock_body(), headers=auth("supervisor"))
    live = (await client.get("/attendance/today", headers=auth("supervisor"))).json()
    assert live["summary"]["in_total"] == 1 and live["summary"]["absent"] == 1
    m = (await client.get("/staff/certifications", headers=auth("hr"))).json()
    store = next(r for r in m if r["name"] == "Ibrahim Danladi")
    assert store["certs"]["H2S"]["status"] == "red" and store["certs"]["BOSIET"]["status"] == "none"
    assert (await client.get("/staff/certifications", headers=auth("finance"))).status_code == 403
