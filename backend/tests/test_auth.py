"""认证模块测试：JWT 单测 + captcha 单测 + 全流程集成（Fake SMS + 本地 Redis/PG）。"""

import pytest
from fastapi.testclient import TestClient

from app.core.redis_client import redis_client
from app.main import app
from app.services.auth import captcha as captcha_svc
from app.services.auth.jwt import create_access_token, decode_access_token

TEST_PHONE = "13800001111"


class FakeSmsProvider:
    """可控的假短信：13800001111 的有效码固定为 123456。"""

    valid_codes = {TEST_PHONE: "123456"}

    def send_code(self, phone: str) -> bool:
        return True

    def verify_code(self, phone: str, code: str) -> bool:
        return self.valid_codes.get(phone) == code


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.auth.service.get_sms_provider", lambda: FakeSmsProvider()
    )
    # 清理防刷计数（冷却/日限/IP），隔离上一次测试运行留下的状态
    for key in redis_client.scan_iter("sms:*"):
        redis_client.delete(key)
    yield TestClient(app)


# ---------- JWT ----------

def test_jwt_roundtrip() -> None:
    token, ttl = create_access_token(42)
    assert ttl == 120 * 60
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_jwt_tampered() -> None:
    token, _ = create_access_token(42)
    assert decode_access_token(token + "x") is None
    assert decode_access_token("not.a.jwt") is None


def test_jwt_type_confusion() -> None:
    """伪造 type!=access 的 token 不能当 access 用（用错误 type 重新签也不行——decode 校验）。"""
    import jwt as pyjwt

    from app.core.config import get_settings

    forged = pyjwt.encode(
        {"sub": "1", "type": "refresh", "exp": 9999999999},
        get_settings().secret_key,
        algorithm="HS256",
    )
    assert decode_access_token(forged) is None


# ---------- captcha ----------

def test_captcha_check() -> None:
    captcha_id, data_url = captcha_svc.generate_captcha()
    assert data_url.startswith("data:image/png;base64,")
    stored = redis_client.get(f"captcha:{captcha_id}")
    assert stored is not None
    # 正确码：通过且一次一用
    assert captcha_svc.check_captcha(captcha_id, str(stored).lower()) is True
    assert captcha_svc.check_captcha(captcha_id, str(stored)) is False  # 已作废


# ---------- 手机号校验 ----------

def test_login_invalid_phone(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/login", json={"phone": "12345", "code": "123456"})
    assert resp.status_code == 422


def test_send_invalid_phone(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/sms/send",
        json={"phone": "12345", "captcha_id": "x", "captcha_code": "x"},
    )
    assert resp.status_code == 422


# ---------- 全流程 ----------

def _get_valid_captcha(client: TestClient) -> dict:
    resp = client.get("/api/v1/auth/captcha")
    data = resp.json()
    stored = redis_client.get(f"captcha:{data['captcha_id']}")
    return {"captcha_id": data["captcha_id"], "captcha_code": stored}


def test_full_flow_login_and_me(client: TestClient) -> None:
    # 发码（图形验证码从 redis 取，模拟用户输入正确）
    resp = client.post(
        "/api/v1/auth/sms/send", json={"phone": TEST_PHONE, **_get_valid_captcha(client)}
    )
    assert resp.status_code == 204

    # 错误短信码 → 401
    resp = client.post("/api/v1/auth/login", json={"phone": TEST_PHONE, "code": "000000"})
    assert resp.status_code == 401

    # 正确码 → 登录成功（自动注册），cookie 已下发
    resp = client.post("/api/v1/auth/login", json={"phone": TEST_PHONE, "code": "123456"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["phone"] == TEST_PHONE
    assert "access_token" in body
    assert ACCESS_COOKIE in resp.cookies

    # me（带 cookie）
    resp = client.get("/api/v1/users/me")
    assert resp.status_code == 200
    assert resp.json()["phone"] == TEST_PHONE


ACCESS_COOKIE = "access_token"


def test_me_unauthorized(client: TestClient) -> None:
    resp = client.get("/api/v1/users/me")
    assert resp.status_code == 401


def test_refresh_rotation_and_replay(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"phone": TEST_PHONE, "code": "123456"})
    old_refresh = client.cookies.get("refresh_token")
    assert old_refresh

    # 轮换成功，拿到新 refresh
    resp = client.post("/api/v1/auth/refresh", json={})
    assert resp.status_code == 200
    new_refresh = client.cookies.get("refresh_token")
    assert new_refresh and new_refresh != old_refresh

    # 重放旧 refresh → 401，且新 refresh 也被连坐吊销
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 401
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert resp.status_code == 401


def test_logout(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"phone": TEST_PHONE, "code": "123456"})
    refresh = client.cookies.get("refresh_token")
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    # logout 后 refresh 不可再用
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


def test_send_captcha_wrong(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/captcha")
    captcha_id = resp.json()["captcha_id"]
    resp = client.post(
        "/api/v1/auth/sms/send",
        json={"phone": "13900002222", "captcha_id": captcha_id, "captcha_code": "ZZZZ"},
    )
    assert resp.status_code == 401  # 图形码错误被拒


def test_send_cooldown(client: TestClient) -> None:
    # 同号 60s 内第二次发送被拒
    phone = "13700003333"
    resp = client.post(
        "/api/v1/auth/sms/send", json={"phone": phone, **_get_valid_captcha(client)}
    )
    assert resp.status_code == 204
    resp = client.post(
        "/api/v1/auth/sms/send", json={"phone": phone, **_get_valid_captcha(client)}
    )
    assert resp.status_code == 429
    redis_client.delete(f"sms:cd:{phone}")  # 清理，避免影响其他测试
