"""Company settings (approval limits, FX rate, branches ...) stored as one document."""
from typing import Any

from .db import get_db

DEFAULTS: dict[str, Any] = {
    "approval_limits": {"finance_max": 500_000},
    "usd_rate": 1500.0,
    "branches": ["Port Harcourt HQ", "Warri", "Abuja"],
    "notification_schedule": {"daily_summary": "19:00", "scans": "07:00"},
    "shift_start_hour": 8,
    "late_grace_minutes": 15,
    "payroll_monthly": 12_000_000,
    "daily_rate_default": 15_000,
    "equipment_categories": [
        "Flooding pump",
        "Lifting pump",
        "Nitrogen unit",
        "Jetting unit",
        "Hose",
        "Flange",
        "Air loader",
        "Chemical injection unit",
        "Compressor",
        "Torque wrench",
    ],
    "expense_categories": [
        "Diesel",
        "Transport",
        "Feeding",
        "PPE",
        "Consumables",
        "Tools",
        "Accomodation",
        "Medical",
        "Site allowance",
    ],
    "service_categories": [
        "Nitrogen Pumping",
        "Hydrotesting",
        "Wellhead Maintenance",
        "Equipment Rental",
        "Manpower Supply",
        "Pipeline Pigging & Inspection",
        "Chemical Cleaning",
        "Flange Management",
    ],
    "certificate_types": [
        {"name": "BOSIET", "target": "staff", "validity_months": 48, "description": "Basic Offshore Safety Induction and Emergency Training"},
        {"name": "HUET", "target": "staff", "validity_months": 24, "description": "Helicopter Underwater Escape Training"},
        {"name": "H2S", "target": "staff", "validity_months": 24, "description": "Hydrogen Sulfide Awareness and Safety"},
        {"name": "First aid", "target": "staff", "validity_months": 24, "description": "Certified Workplace First Aid & CPR"},
        {"name": "Medical Fitness (OGUK)", "target": "staff", "validity_months": 12, "description": "Offshore Medical Fitness Certificate"},
        {"name": "Equipment licence", "target": "staff", "validity_months": 24, "description": "Heavy Equipment & Unit Operator Certification"},
        {"name": "Pressure test", "target": "equipment", "validity_months": 12, "description": "Hydrostatic Pressure Test & Relief Valve Certificate"},
        {"name": "Lifting inspection (LOLER)", "target": "equipment", "validity_months": 12, "description": "Lifting Equipment & Rigging Safety Inspection"},
        {"name": "Calibration certificate", "target": "equipment", "validity_months": 12, "description": "Instrument & Gauge Calibration Verification"},
        {"name": "NDT inspection", "target": "equipment", "validity_months": 12, "description": "Non-Destructive Testing Flaw Certification"},
    ],
}


async def get_settings_doc() -> dict[str, Any]:
    doc = await get_db().settings.find_one({"_id": "main"}) or {}
    merged = {**DEFAULTS, **{k: v for k, v in doc.items() if k != "_id"}}
    merged["approval_limits"] = {**DEFAULTS["approval_limits"], **(doc.get("approval_limits") or {})}
    return merged


async def update_settings_doc(patch: dict[str, Any]) -> dict[str, Any]:
    await get_db().settings.update_one({"_id": "main"}, {"$set": patch}, upsert=True)
    return await get_settings_doc()
