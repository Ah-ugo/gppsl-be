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


async def test_multi_role_user_provisioning_and_access(client, auth):
    # Admin creates a user with multiple roles: field staff + finance (accounts)
    body = {
        "email": "accounts.field@test.ng",
        "name": "Babatunde Lawal",
        "roles": ["staff", "finance"],
        "password": "Password@123",
        "phone": "0803 456 7890",
        "branch": "Port Harcourt HQ",
    }
    create_res = await client.post("/users", json=body, headers=auth("admin"))
    assert create_res.status_code == 201
    user_data = create_res.json()
    assert user_data["roles"] == ["staff", "finance"]
    assert user_data["role"] == "staff"

    # User logs in and tokens are issued
    login_res = await client.post("/auth/login", json={"email": "accounts.field@test.ng", "password": "Password@123"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    user_header = {"Authorization": f"Bearer {token}"}

    # /auth/me reflects both roles
    me_res = await client.get("/auth/me", headers=user_header)
    assert me_res.status_code == 200
    assert "finance" in me_res.json()["roles"]
    assert "staff" in me_res.json()["roles"]

    # Since user has "finance" role, they can access finance endpoints
    fin_res = await client.get("/finance/overview", headers=user_header)
    assert fin_res.status_code == 200

    # And since they have a linked staff profile, /staff/me returns their profile for attendance
    staff_me = await client.get("/staff/me", headers=user_header)
    assert staff_me.status_code == 200
    assert staff_me.json()["name"] == "Babatunde Lawal"


async def test_staff_account_provisioning_endpoint(client, auth):
    # Create staff profile without login account initially
    staff_payload = {
        "name": "Kelechi Danjuma",
        "position": "Pump Operator",
        "branch": "Warri",
        "branch_access": ["all"],
        "department": "Operations",
        "employment_type": "contract",
        "phone": "0805 111 2233",
        "daily_rate": 18000,
    }
    s_res = await client.post("/staff", json=staff_payload, headers=auth("hr"))
    assert s_res.status_code == 201
    staff_id = s_res.json()["id"]

    # HR provisions login account with roles ["staff", "supervisor"] for attendance
    acc_payload = {
        "email": "kelechi.d@test.ng",
        "password": "Temporary@1234",
        "roles": ["staff", "supervisor"],
    }
    acc_res = await client.post(f"/staff/{staff_id}/account", json=acc_payload, headers=auth("hr"))
    assert acc_res.status_code == 200
    acc_data = acc_res.json()
    assert acc_data["has_login"] is True
    assert acc_data["login_email"] == "kelechi.d@test.ng"
    assert "staff" in acc_data["roles"]
    assert "supervisor" in acc_data["roles"]

    # The field staff can now log in
    staff_login = await client.post("/auth/login", json={"email": "kelechi.d@test.ng", "password": "Temporary@1234"})
    assert staff_login.status_code == 200
    staff_token = staff_login.json()["access_token"]

    # Field staff can access /staff/me and attendance
    st_header = {"Authorization": f"Bearer {staff_token}"}
    my_st = await client.get("/staff/me", headers=st_header)
    assert my_st.status_code == 200
    assert my_st.json()["name"] == "Kelechi Danjuma"
