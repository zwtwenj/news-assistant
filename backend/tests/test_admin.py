"""后管模块测试：登录（密码/限频）+ JWT scope 双向隔离 + 主机 CRUD。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.admin_user import AdminUser
from app.services.auth.jwt import create_access_token
from app.services.auth.password import hash_password

TEST_USERNAME = "admin_test"
TEST_PASSWORD = "test-password-123"


@pytest.fixture
def client():
    from app.core.redis_client import redis_client

    # 清理登录限频计数，隔离状态
    for key in redis_client.scan_iter("quota:admin:*"):
        redis_client.delete(key)
    yield TestClient(app)


@pytest.fixture
def admin_user():
    from app.db.session import SessionLocal

    db = SessionLocal()
    admin = db.query(AdminUser).filter(AdminUser.username == TEST_USERNAME).first()
    if admin is None:
        admin = AdminUser(
            username=TEST_USERNAME,
            password_hash=hash_password(TEST_PASSWORD),
            display_name="测试管理员",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
    db.close()
    return admin


def _login(client: TestClient, username=TEST_USERNAME, password=TEST_PASSWORD):
    return client.post(
        "/api/v1/admin/auth/login", json={"username": username, "password": password}
    )


# ---------- 认证 ----------


def test_login_ok(client, admin_user):
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.json()["username"] == TEST_USERNAME
    assert "admin_token" in resp.cookies


def test_login_wrong_password(client, admin_user):
    resp = _login(client, password="wrong")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"


def test_login_rate_limited(client, admin_user):
    for _ in range(5):
        _login(client, password="wrong")
    resp = _login(client)  # 第 6 次（即使密码正确）也被限
    assert resp.status_code == 429


def test_me_requires_admin_cookie(client):
    assert client.get("/api/v1/admin/auth/me").status_code == 401


def test_me_ok(client, admin_user):
    _login(client)
    resp = client.get("/api/v1/admin/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == TEST_USERNAME


def test_user_token_cannot_access_admin(client, admin_user):
    # C 端用户 token（scope=user）访问后管 → 401
    from app.db.session import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    user = db.query(User).first()
    db.close()
    if user is None:
        pytest.skip("无 C 端用户")
    token, _ = create_access_token(user.id, scope="user")
    resp = client.get("/api/v1/admin/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_admin_token_cannot_act_as_user(client, admin_user):
    # admin token 访问 C 端接口 → 401（双向隔离）
    token, _ = create_access_token(admin_user.id, scope="admin")
    resp = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ---------- 主播 CRUD ----------


def test_hosts_crud(client, admin_user):
    _login(client)
    # 建
    resp = client.post(
        "/api/v1/admin/hosts",
        json={
            "name": "测试主播",
            "voice_id": "presenter_male",
            "gender": "male",
            "persona": "测试人设",
            "description": "单测",
        },
    )
    assert resp.status_code == 201
    hid = resp.json()["id"]

    # 改
    resp = client.put(f"/api/v1/admin/hosts/{hid}", json={
        "name": "测试主播2", "voice_id": "presenter_female", "gender": "female",
        "persona": "改后的人设", "description": None, "enabled": False, "sort_order": 9,
    })
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # 删
    assert client.delete(f"/api/v1/admin/hosts/{hid}").status_code == 200
    assert client.delete(f"/api/v1/admin/hosts/{hid}").status_code == 404


def test_hosts_require_auth(client):
    assert client.get("/api/v1/admin/hosts").status_code == 401
