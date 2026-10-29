"""Wipe and reseed the database with demo data.   python seed.py

Demo password for every demo account: Demo@1234  (one-click login also available on the login page).
"""
import asyncio

from app.core.common import today
from app.core.db import get_db, init_indexes
from app.core.security import hash_password
from seed_data import generate

COLLECTIONS = ["users", "staff", "sites", "clients", "projects", "equipment", "rentals", "maintenance", "fuel_logs", "invoices",
               "payables", "expenses", "settings", "audit_log", "notifications", "daily_reports", "incidents", "attendance",
               "assignments", "documents", "document_chunks", "signature_requests"]

from seed_documents import seed_documents

EXTENSIONS: list = [seed_documents]  # extra seeders: async def f(db, data, today)


async def seed(wipe: bool = True) -> dict:
    db = get_db()
    if wipe:
        for name in COLLECTIONS:
            await db[name].delete_many({})
    await init_indexes()
    data = generate(today())
    pw = hash_password("Demo@1234")  # hashed once and shared, Argon2 is deliberately slow
    for u in data["users"]:
        u["password_hash"] = pw
    for name, docs in data.items():
        if docs:
            await db[name].insert_many(docs)
    for ext in EXTENSIONS:
        await ext(db, data, today())
    return {k: len(v) for k, v in data.items()}


if __name__ == "__main__":
    counts = asyncio.run(seed())
    print("Seeded:", counts)
    print("Demo logins (password Demo@1234): md@gppsl.demo admin@gppsl.demo finance@gppsl.demo supervisor@gppsl.demo storekeeper@gppsl.demo hr@gppsl.demo")
