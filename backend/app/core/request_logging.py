"""HTTP 请求日志中间件（纯 ASGI 实现，SSE 流式安全）。

每个到达后端的 /api 请求记一条 request_logs：
- user_id 由 access_token JWT 无状态解码（payload.sub），不查库
- 请求头白名单落库；请求体截断 4KB 且敏感键值脱敏
- 出参仅捕获 application/json 且 <16KB 的响应；SSE（text/event-stream）只记状态与耗时
- 落库在响应完成后进行，失败只记 warning 绝不影响业务响应
"""

import json
import time
from typing import Any

from loguru import logger
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.db.session import SessionLocal
from app.models.request_log import RequestLog
from app.services.auth.jwt import decode_access_token

# 非业务路径不记（探针/静态/公开 RSS/文档）
_SKIP_PREFIXES = ("/healthz", "/media/", "/feed/", "/docs", "/openapi.json")
# 请求头白名单：凭证类头（authorization/cookie）一律不落库
_HEADER_ALLOWLIST = ("content-type", "user-agent", "origin", "referer", "accept-language")
# 请求体中这些键的值替换为 ***（短信验证码/密码/各类 token）
_REDACT_KEYS = {
    "password", "passwd", "code", "sms_code", "captcha_code",
    "token", "access_token", "refresh_token", "secret",
}
_BODY_MAX = 4096
_RESP_MAX = 16384


def _redact_body(body: bytes, content_type: str) -> str | None:
    """请求体截断 + 敏感键脱敏；JSON 解析失败时保留截断原文。"""
    if not body:
        return None
    if "multipart" in content_type:
        return "[multipart 未记录]"
    text = body.decode("utf-8", errors="replace")[:_BODY_MAX]
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict):
        for key in list(data):
            if key.lower() in _REDACT_KEYS:
                data[key] = "***"
    return json.dumps(data, ensure_ascii=False)[:_BODY_MAX]


def _user_id_from_scope(scope: Scope) -> int | None:
    """从 cookie 或 Authorization 头解码 JWT 取 user_id（无状态，不查库）。"""
    for key, value in scope.get("headers", []):
        name = key.decode("latin-1").lower()
        raw = value.decode("latin-1")
        token = None
        if name == "cookie":
            for part in raw.split(";"):
                part = part.strip()
                if part.startswith("access_token="):
                    token = part.split("=", 1)[1]
                    break
        elif name == "authorization" and raw.startswith("Bearer "):
            token = raw[7:]
        if token:
            payload = decode_access_token(token)
            if payload and payload.get("sub"):
                return int(payload["sub"])
    return None


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if scope.get("method") == "OPTIONS" or any(path.startswith(p) for p in _SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        # 请求体读入并截断存储副本（完整体原样转发给下游）
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body", False):
                break

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        content_type = headers.get("content-type", "")
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        state: dict[str, Any] = {"status": 0, "capture": False, "chunks": []}

        async def send_wrapper(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                state["status"] = msg["status"]
                for key, value in msg.get("headers", []):
                    if key.decode("latin-1").lower() == "content-type":
                        state["capture"] = value.decode("latin-1").startswith("application/json")
            elif msg["type"] == "http.response.body" and state["capture"]:
                if sum(len(c) for c in state["chunks"]) < _RESP_MAX:
                    state["chunks"].append(msg.get("body", b""))
            await send(msg)

        started = time.perf_counter()
        try:
            await self.app(scope, replay_receive, send_wrapper)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            try:
                resp_body = b"".join(state["chunks"]).decode("utf-8", errors="replace")
                ip = headers.get("x-forwarded-for", "").split(",")[0].strip() or (
                    (scope.get("client") or (None,))[0]
                )
                with SessionLocal() as db:
                    db.add(RequestLog(
                        method=scope.get("method", ""),
                        path=path[:256],
                        query=(scope.get("query_string") or b"").decode("latin-1")[:512] or None,
                        status=state["status"],
                        duration_ms=duration_ms,
                        user_id=_user_id_from_scope(scope),
                        ip=ip[:64] if ip else None,
                        request_headers={
                            k: v for k, v in headers.items() if k in _HEADER_ALLOWLIST
                        } or None,
                        request_body=_redact_body(body, content_type),
                        response_body=resp_body[:_RESP_MAX] if resp_body else None,
                        error=resp_body[:1000] if state["status"] >= 400 else None,
                    ))
                    db.commit()
            except Exception:
                logger.opt(exception=True).warning("request log 写入失败 path={}", path)
