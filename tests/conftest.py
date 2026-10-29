"""Shared pytest fixtures. Runs against an in-memory fake MongoDB (mongomock-motor), no server needed."""
import os

os.environ["MONGO_URL"] = "mongomock://"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["DEMO_MODE"] = "true"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["UPLOAD_DIR"] = "/tmp/gppsl_test_uploads"
os.environ["CLOUDINARY_URL"] = ""
os.environ["MISTRAL_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.common import new_id
from app.core.db import get_db, reset_db
from app.core.security import create_access_token, hash_password

ROLES = ["md", "admin", "finance", "supervisor", "storekeeper", "hr"]


@pytest_asyncio.fixture
async def client():
    reset_db()
    from app.modules.auth.service import reset_rate_limits

    reset_rate_limits()
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def users(client):
    """One user per role. Returns {role: user_doc}."""
    db = get_db()
    out = {}
    pw = hash_password("Demo@1234")
    for role in ROLES:
        doc = {"_id": new_id(), "email": f"{role}@test.ng", "name": f"Test {role.title()}", "role": role,
               "branch": "Port Harcourt HQ", "active": True, "demo": True, "password_hash": pw}
        await db.users.insert_one(doc)
        out[role] = doc
    return out


@pytest.fixture
def auth(users):
    """auth('finance') -> Authorization header for that role."""
    def _auth(role: str) -> dict:
        u = users[role]
        return {"Authorization": f"Bearer {create_access_token(u['_id'], u['role'])}"}
    return _auth


# ---- data helpers ------------------------------------------------------------------------------
from datetime import date, timedelta


@pytest_asyncio.fixture
async def world(client):
    """A client, a project and three pieces of equipment (ok, expired certificate, service overdue)."""
    db = get_db()
    today = date.today()
    cl = {"_id": new_id(), "name": "Demo Client A", "payment_terms_days": 90}
    await db.clients.insert_one(cl)
    pr = {"_id": new_id(), "client_id": cl["_id"], "name": "Demo Project X", "location": "Port Harcourt",
          "branch": "Port Harcourt HQ", "budget": 10_000_000, "status": "active", "progress": 30,
          "start": (today - timedelta(days=30)).isoformat(), "end": (today + timedelta(days=60)).isoformat()}
    await db.projects.insert_one(pr)

    def eq(name, serial, **kw):
        base = {"_id": new_id(), "name": name, "category": "Flooding pump", "serial": serial,
                "branch": "Port Harcourt HQ", "status": "available", "purchase_cost": 5_000_000, "photos": [],
                "run_hours": 100, "service_interval_hours": 500, "last_service_hours": 0, "certificates": [],
                "current_job_id": None, "current_rental_id": None}
        base.update(kw)
        return base

    ok = eq("Pump OK", "SN-OK")
    expired = eq("Pump Expired Cert", "SN-EXP",
                 certificates=[{"name": "Pressure inspection", "expiry_date": (today - timedelta(days=5)).isoformat()}])
    overdue = eq("Pump Service Overdue", "SN-OVD", run_hours=700)
    for e in (ok, expired, overdue):
        await db.equipment.insert_one(e)
    return {"client": cl, "project": pr, "ok": ok, "expired": expired, "overdue": overdue}


# ---- attendance helpers ------------------------------------------------------------------------
import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz

PH_SITE = {"name": "PH Yard", "branch": "Port Harcourt HQ", "lat": 4.8156, "lng": 7.0498, "radius_m": 250}


def descriptor(base=0.0):
    return [base + (i % 7) * 0.001 for i in range(128)]


@pytest_asyncio.fixture
async def crew(client, users):
    """Staff profiles for the supervisor (face registered + approved) and storekeeper (no face), one site."""
    db = get_db()
    await db.sites.insert_one({"_id": new_id(), **PH_SITE})
    sup = {"_id": new_id(), "user_id": users["supervisor"]["_id"], "name": "Emeka Okafor", "position": "Site Supervisor",
           "branch": "Port Harcourt HQ", "daily_rate": 20000, "face_template": [descriptor(0.0), descriptor(0.01), descriptor(0.02)],
           "face_status": "approved", "face_consent": {"given": True}, "certifications": [{"type": "H2S", "expiry": "2030-01-01"}]}
    store = {"_id": new_id(), "user_id": users["storekeeper"]["_id"], "name": "Ibrahim Danladi", "position": "Storekeeper",
             "branch": "Port Harcourt HQ", "daily_rate": 15000, "face_template": [], "face_status": "none", "face_consent": {"given": False},
             "certifications": [{"type": "H2S", "expiry": "2020-01-01"}]}
    await db.staff.insert_many([sup, store])
    return {"sup": sup, "store": store}


def clock_body(**kw):
    b = {"id": str(_uuid.uuid4()), "descriptor": descriptor(0.005), "selfie_url": "http://x/selfie.jpg", "lat": 4.8157, "lng": 7.0499,
         "accuracy": 10, "phone_time": _dt.now(_tz.utc).isoformat(), "liveness": True, "offline": False}
    b.update(kw)
    return b
