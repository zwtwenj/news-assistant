"""后管账号管理测试：建号（重复/短密码）+ 改密（改后可登录）+ 停用护栏（防自锁）。"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.admin_user import AdminUser
from app.services.auth.password import hash_password

TEST_USERNAME = "admin_test"
TEST_PASSWORD = "test-password-123"


@pytest.fixture
def client():
    from app.core.redis_client import redis_client

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


def _cleanup(*usernames: str):
    db = SessionLocal()
    db.query(AdminUser).filter(AdminUser.username.in_(usernames)).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


# ---------- 建号 ----------


def test_create_account_ok(client, admin_user):
    _login(client)
    resp = client.post(
        "/api/v1/admin/users",
        json={"username": "tmp_admin", "password": "abcd12345", "display_name": "临时"},
    )
    assert resp.status_code == 201
    assert resp.json()["username"] == "tmp_admin"
    _cleanup("tmp_admin")


def test_create_duplicate_username(client, admin_user):
    _login(client)
    resp = client.post(
        "/api/v1/admin/users", json={"username": TEST_USERNAME, "password": "abcd12345"}
    )
    assert resp.status_code == 409


def test_create_short_password(client, admin_user):
    _login(client)
    resp = client.post("/api/v1/admin/users", json={"username": "tmp_admin", "password": "123"})
    assert resp.status_code == 422


# ---------- 改密 ----------


def test_reset_password_then_login(client, admin_user):
    _login(client)
    resp = client.put(
        f"/api/v1/admin/users/{admin_user.id}", json={"password": "new-password-456"}
    )
    assert resp.status_code == 200
    # 旧密码失败、新密码成功
    assert _login(client).status_code == 401
    assert _login(client, password="new-password-456").status_code == 200
    # 还原，避免影响其他用例
    client.put(f"/api/v1/admin/users/{admin_user.id}", json={"password": TEST_PASSWORD})


# ---------- 停用护栏 ----------


def test_cannot_ban_self(client, admin_user):
    _login(client)
    resp = client.put(f"/api/v1/admin/users/{admin_user.id}", json={"status": "banned"})
    assert resp.status_code == 400
    assert "不能停用当前登录" in resp.json()["detail"]


def test_ban_and_unban_other(client, admin_user):
    # 建临时号 → 停用 → 被停号登录 401 → 恢复 → 可登录
    _login(client)
    created = client.post(
        "/api/v1/admin/users", json={"username": "tmp_admin", "password": "abcd12345"}
    ).json()
    resp = client.put(f"/api/v1/admin/users/{created['id']}", json={"status": "banned"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "banned"
    assert _login(client, username="tmp_admin", password="abcd12345").status_code == 401
    resp = client.put(f"/api/v1/admin/users/{created['id']}", json={"status": "active"})
    assert resp.json()["status"] == "active"
    assert _login(client, username="tmp_admin", password="abcd12345").status_code == 200
    _cleanup("tmp_admin")
