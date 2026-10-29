"""Acceptance test 9: a supervisor cannot reach finance or MD-only endpoints. Also settings rules."""
import pytest

FINANCE_OR_MD_ONLY = [
    ("GET", "/dashboard"), ("GET", "/dashboard/summary"), ("GET", "/finance/overview"), ("GET", "/invoices"), ("GET", "/payables"),
    ("GET", "/audit"), ("GET", "/users"), ("GET", "/ai/summary/daily"), ("PATCH", "/settings"),
]


@pytest.mark.parametrize("method,path", FINANCE_OR_MD_ONLY)
@pytest.mark.parametrize("role", ["supervisor", "storekeeper"])
async def test_field_roles_blocked(client, auth, method, path, role):
    r = await client.request(method, path, headers=auth(role), json={} if method == "PATCH" else None)
    assert r.status_code == 403, f"{role} reached {method} {path}"


async def test_md_can_change_limit_and_it_is_audited(client, auth):
    r = await client.patch("/settings", json={"approval_limits": {"finance_max": 250000}}, headers=auth("md"))
    assert r.status_code == 200 and r.json()["approval_limits"]["finance_max"] == 250000
    audit = (await client.get("/audit", headers=auth("md"))).json()
    assert any(a["entity"] == "settings" for a in audit["items"])


async def test_finance_cannot_change_settings(client, auth):
    assert (await client.patch("/settings", json={"usd_rate": 1}, headers=auth("finance"))).status_code == 403
