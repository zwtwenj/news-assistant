"""火山引擎 Viking 记忆库（per-user 画像）：检索注入 system / 对话后异步写入。

移植自 blog demo（同款 API：/api/memory/session/add + /api/memory/get_context，
事件记忆 event_v1）。per-user 隔离：每个用户独立 user_id（users.viking_user_id，
格式 news_u_{id}），同一 collection 内按 user_id 过滤。
所有调用失败静默（不阻断对话）。
"""

import time

import requests
from loguru import logger

from app.core.config import get_settings

USER_NAME = "新闻助手用户"
ASSISTANT_ID = "news_chat_agent"
ASSISTANT_NAME = "小讯"
CONTEXT_LIMIT = 10


class VikingMemoryError(Exception):
    """Viking 记忆库调用失败"""


def enabled() -> bool:
    return bool(get_settings().viking_memory_key)


def _post(path: str, body: dict, timeout: int = 30) -> dict:
    s = get_settings()
    resp = requests.post(
        f"{s.viking_memory_base.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {s.viking_memory_key}"},
        json=body,
        timeout=timeout,
    )
    data = resp.json() if resp.status_code == 200 else {}
    if resp.status_code != 200 or data.get("code") != 0:
        raise VikingMemoryError(f"{path} HTTP {resp.status_code}: {str(data)[:120]}")
    return data.get("data") or {}


def add_messages(messages: list[dict], user_id: str) -> str:
    """写入一轮对话（服务端异步抽取事件记忆，下一轮可召回）。返回 session_id。"""
    s = get_settings()
    data = _post(
        "/api/memory/session/add",
        {
            "collection_name": s.viking_collection,
            "project_name": s.viking_project,
            "messages": messages,
            "metadata": {
                "default_user_id": user_id,
                "default_user_name": USER_NAME,
                "default_assistant_id": ASSISTANT_ID,
                "default_assistant_name": ASSISTANT_NAME,
                "time": int(time.time() * 1000),
            },
        },
    )
    return data.get("session_id", "")


def search_events(query: str, user_id: str, limit: int = CONTEXT_LIMIT) -> list[dict]:
    """检索该用户的事件记忆：[{summary, time}]。"""
    s = get_settings()
    data = _post(
        "/api/memory/get_context",
        {
            "collection_name": s.viking_collection,
            "project_name": s.viking_project,
            "query": query,
            "event_search_config": {
                "filter": {"user_id": user_id, "memory_type": ["event_v1"]},
                "limit": limit,
            },
        },
    )
    events = []
    for part in (data.get("context_parts") or []):
        for ev in part.get("events") or []:
            info = ev.get("memory_info") or {}
            if info.get("summary"):
                events.append({"summary": info["summary"], "time": ev.get("time")})
    return events


def build_memory_block(events: list[dict]) -> str:
    """记忆块（注入 system prompt）。"""
    if not events:
        return ""
    lines = [f"{i}. {e['summary']}" for i, e in enumerate(events, 1)]
    return "以下是检索到的用户长期记忆（回答时可参考，用于个性化）：\n" + "\n".join(lines)


def safe_search(query: str, user_id: str) -> list[dict]:
    """失败静默版检索（对话主链路用）。"""
    if not enabled():
        return []
    try:
        return search_events(query, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).warning("viking search fail: {}", str(exc)[:80])
        return []


def safe_add(messages: list[dict], user_id: str) -> None:
    """失败静默版写入（回答完成后调用）。"""
    if not enabled():
        return
    try:
        add_messages(messages, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).warning("viking add fail: {}", str(exc)[:80])
