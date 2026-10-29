from app.core.db import get_db


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_login_success_and_me(client, users):
    r = await client.post("/auth/login", json={"email": "md@test.ng", "password": "Demo@1234"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "md"
    assert "password_hash" not in body["user"]
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "md@test.ng"


async def test_login_wrong_password(client, users):
    r = await client.post("/auth/login", json={"email": "md@test.ng", "password": "nope"})
    assert r.status_code == 401


async def test_login_rate_limited_after_five(client, users):
    codes = []
    for _ in range(7):
        r = await client.post("/auth/login", json={"email": "md@test.ng", "password": "bad"})
        codes.append(r.status_code)
    assert codes[:5] == [401] * 5
    assert 429 in codes[5:]


async def test_refresh_flow(client, users):
    login = (await client.post("/auth/login", json={"email": "md@test.ng", "password": "Demo@1234"})).json()
    r = await client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["access_token"]
    # an access token must not work as a refresh token
    bad = await client.post("/auth/refresh", json={"refresh_token": login["access_token"]})
    assert bad.status_code == 401


async def test_protected_route_needs_token(client):
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/audit")).status_code == 401


async def test_audit_is_md_admin_only(client, auth):
    assert (await client.get("/audit", headers=auth("md"))).status_code == 200
    assert (await client.get("/audit", headers=auth("admin"))).status_code == 200
    for role in ("finance", "supervisor", "storekeeper", "hr"):
        assert (await client.get("/audit", headers=auth(role))).status_code == 403


async def test_login_is_audited(client, users, auth):
    await client.post("/auth/login", json={"email": "finance@test.ng", "password": "Demo@1234"})
    r = await client.get("/audit", headers=auth("md"), params={"action": "login"})
    assert r.status_code == 200
    assert any("signed in" in i["summary"] for i in r.json()["items"])


async def test_audit_has_no_write_endpoints(client, auth):
    for method in ("post", "put", "patch", "delete"):
        r = await getattr(client, method)("/audit", headers=auth("md"))
        assert r.status_code in (404, 405)


async def test_demo_login_gives_each_role(client, users):
    r = await client.post("/auth/demo-login", json={"role": "supervisor"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "supervisor"
    accounts = (await client.get("/auth/demo-accounts")).json()
    assert {a["role"] for a in accounts} == {"md", "admin", "finance", "supervisor", "storekeeper", "hr"}


async def test_user_admin_rules(client, auth):
    body = {"email": "new@test.ng", "name": "New Person", "role": "hr", "password": "Str0ngPass!", "phone": "0803 123 4567"}
    assert (await client.post("/users", json=body, headers=auth("supervisor"))).status_code == 403
    ok = await client.post("/users", json=body, headers=auth("admin"))
    assert ok.status_code == 201 and "password_hash" not in ok.json()
    dup = await client.post("/users", json=body, headers=auth("admin"))
    assert dup.status_code == 409
    bad = await client.post("/users", json={**body, "email": "x@test.ng", "phone": "12345"}, headers=auth("admin"))
    assert bad.status_code == 422
