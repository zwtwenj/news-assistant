"""飞书群机器人告警（webhook）。

告警是旁路：发送失败只记日志，绝不阻断业务。
内置同 key 去重防抖（默认 30 分钟内同 key 不重复发送），避免循环任务刷屏。
"""

import time

import httpx
from loguru import logger

from app.core.config import get_settings

# 同 key 防抖窗口：30 分钟内相同 key 只发第一条
_DEDUP_WINDOW = 30 * 60
_dedup_cache: dict[str, float] = {}
_dedup_last_clean = 0.0


def enabled() -> bool:
    return bool(get_settings().feishu_webhook_url)


def _clean_dedup(now: float) -> None:
    global _dedup_last_clean
    if now - _dedup_last_clean < 3600:
        return
    for k in [k for k, ts in _dedup_cache.items() if now - ts > _DEDUP_WINDOW * 2]:
        _dedup_cache.pop(k, None)
    _dedup_last_clean = now


def _should_send(dedup_key: str | None, now: float) -> bool:
    if not dedup_key:
        return True
    _clean_dedup(now)
    last = _dedup_cache.get(dedup_key)
    if last is not None and now - last < _DEDUP_WINDOW:
        return False
    _dedup_cache[dedup_key] = now
    return True


def send_alert(title: str, content: str, *, dedup_key: str | None = None) -> bool:
    """发送文本告警到飞书群。

    dedup_key：相同 key 在 30 分钟窗口内只发第一条（如 "rss_fail"），
    防止每分钟任务刷屏；None 则每次都发。
    返回是否成功发送（失败仅记日志）。
    """
    if not enabled():
        return False
    now = time.time()
    if not _should_send(dedup_key or title, now):
        return False
    try:
        resp = httpx.post(
            get_settings().feishu_webhook_url,
            json={
                "msg_type": "text",
                "content": {"text": f"【{title}】\n{content}"},
            },
            timeout=10,
        )
        ok = resp.status_code == 200 and resp.json().get("code") == 0
        if not ok:
            logger.warning("feishu alert rejected: {}", resp.text[:120])
        return ok
    except Exception as exc:  # noqa: BLE001  告警旁路，绝不阻断业务
        logger.opt(exception=True).warning("feishu alert fail: {}", str(exc)[:120])
        return False
