"""聊天工具集：今日新闻分页 / 标签向量匹配 / 博查联网搜索 / 图片分析。"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import requests
from loguru import logger
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal

PAGE_SIZE = 10

# ---------- 图片暂存（进程内，5 分钟 TTL） ----------

_IMAGE_TTL = 300
_image_store: dict[str, dict] = {}


def store_image(image_id: str, b64: str, mime: str) -> None:
    now = time.time()
    for k in [k for k, v in _image_store.items() if now - v["ts"] > _IMAGE_TTL]:
        _image_store.pop(k, None)
    _image_store[image_id] = {"b64": b64, "mime": mime, "ts": now}


def get_image(image_id: str) -> dict | None:
    item = _image_store.get(image_id)
    if item and time.time() - item["ts"] <= _IMAGE_TTL:
        return item
    return None


# ---------- 工具实现 ----------

def list_today_news(page: int = 1, tag: str = "") -> dict:
    """按日查 PG 新闻，分页 10 条/页。tag 可选精确过滤（jsonb 包含）。

    与标签匹配工具联动：LLM 先用 match_similar_tags 拿到相关标签，再以 tag 调本工具。
    """
    page = max(1, page)
    day_start = datetime.now(UTC) - timedelta(hours=24)
    params: dict[str, Any] = {
        "since": day_start, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE,
    }
    tag_filter = ""
    if tag:
        tag_filter = "AND tags @> CAST(:tag AS jsonb)"
        params["tag"] = f'["{tag}"]'
    sql = text(
        f"""
        SELECT id, title, url, source, tags, publish_time
        FROM articles
        WHERE deleted_at IS NULL AND fetch_status = 'succeeded'
          AND publish_time >= :since {tag_filter}
        ORDER BY publish_time DESC, id DESC
        LIMIT :limit OFFSET :offset
        """
    )
    count_sql = text(
        f"""
        SELECT count(*) FROM articles
        WHERE deleted_at IS NULL AND fetch_status = 'succeeded'
          AND publish_time >= :since {tag_filter}
        """
    )
    with SessionLocal() as db:
        total = db.execute(count_sql, params).scalar() or 0
        rows = db.execute(sql, params).all()
    items = [
        {
            "id": r[0],
            "title": r[1],
            "url": r[2],
            "source": r[3],
            "tags": r[4] or [],
            "publish_time": r[5].strftime("%m-%d %H:%M") if r[5] else "",
        }
        for r in rows
    ]
    has_more = page * PAGE_SIZE < total
    return {"page": page, "total": total, "has_more": has_more, "items": items}


def search_news_library(query: str, top_k: int = 5) -> dict:
    """新闻库语义检索（复用播客 RAG 链路：understand_topic→双路召回→rerank→回表）。"""
    from app.services.chat import rag as rag_svc

    sources = rag_svc.retrieve(query, top_k=top_k)
    if not sources:
        return {"found": False, "note": "新闻库中没有相关内容"}
    return {
        "found": True,
        "results": [
            {
                "title": s["title"],
                "url": s["url"],
                "material": s["material"],
                "score": s["rerank_score"],
            }
            for s in sources
        ],
    }


def match_similar_tags(query: str) -> dict:
    """标签向量匹配：query 与词表标签余弦 ≥ 阈值的相似标签（复用播客检索的匹配器）。"""
    from app.services.news.vocabulary import match_tags

    tags = match_tags(query)
    return {"query": query, "matched_tags": tags}


def web_search_news(query: str, count: int = 5) -> dict:
    """博查联网搜索（无 key 时返回不可用说明，LLM 会告知用户）。"""
    key = get_settings().bocha_key
    if not key:
        return {"available": False, "note": "联网搜索未配置"}
    try:
        resp = requests.post(
            "https://api.bochaai.com/v1/web-search",
            headers={"Authorization": f"Bearer {key}"},
            json={"query": query, "count": count, "summary": True},
            timeout=20,
        )
        data = resp.json()
        pages = (data.get("data") or {}).get("webPages") or {}
        results = [
            {
                "title": p.get("name", ""),
                "url": p.get("url", ""),
                "snippet": (p.get("summary") or p.get("snippet") or "")[:200],
            }
            for p in (pages.get("value") or [])
        ]
        return {"available": True, "results": results}
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).warning("bocha search fail: {}", str(exc)[:80])
        return {"available": False, "note": f"联网搜索失败: {str(exc)[:60]}"}


def analyze_image(image_id: str, question: str) -> dict:
    """Qwen-VL 看图问答（dashscope 兼容端点）。"""
    from app.core.config import get_settings

    item = get_image(image_id)
    if item is None:
        return {"error": "图片不存在或已过期（5 分钟 TTL），请重新上传"}
    s = get_settings()
    try:
        resp = httpx.post(
            f"{s.dashscope_base_url.rstrip('/').removesuffix('/compatible-mode/v1')}"
            "/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {s.dashscope_api_key}"},
            json={
                "model": "qwen-vl-plus",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{item['mime']};base64,{item['b64']}"
                                },
                            },
                            {"type": "text", "text": question or "描述这张图片的内容"},
                        ],
                    }
                ],
            },
            timeout=60,
        )
        data = resp.json()
        answer = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not answer:
            raise ValueError(f"VL 响应异常: {str(data)[:120]}")
        return {"answer": answer}
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).warning("analyze_image fail: {}", str(exc)[:80])
        return {"error": f"图片分析失败: {str(exc)[:80]}"}


# ---------- schema 与分发 ----------

SEARCH_NEWS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_news_library",
        "description": (
            "在新闻库中按主题语义检索相关新闻（返回标题/正文节选/来源链接）。"
            "用户询问某主题的相关报道、事件背景、新闻细节时使用；"
            "只是想看最新新闻列表时用 list_today_news。结果要注明来源标题。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索主题，如'民营经济政策'"},
            },
            "required": ["query"],
        },
    },
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_today_news",
            "description": (
                "查询新闻库中最近 24 小时的新闻列表，每页 10 条。"
                "用户想看最新/今日新闻时使用；用户说'还有吗/继续'时传 page+1；"
                "可以传 tag 只看某类新闻（需先用 match_similar_tags 获取合法标签）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": "页码，从 1 开始", "default": 1},
                    "tag": {
                        "type": "string",
                        "description": "可选，按标签精确过滤（如 '气象'）",
                        "default": "",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_similar_tags",
            "description": (
                "把用户的主题描述匹配成新闻库的标签（向量相似度）。"
                "用户问某类主题（如'自然灾害''体育赛事'）时，先用本工具拿到相关标签，"
                "再用 list_today_news(tag=...) 联动查询。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "主题描述，如'自然灾害'"}
                },
                "required": ["query"],
            },
        },
    },
    SEARCH_NEWS_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "web_search_news",
            "description": (
                "联网搜索最新资讯（新闻库没有相关内容时使用，结果要标注「来源：网络搜索」）"
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": (
                "分析用户上传的图片并回答关于图片的问题（system 会告知 image_id 时才可用）"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string", "description": "想了解图片的什么，如'这是什么地方'"
                    },
                },
            },
        },
    },
]


def execute_tool(name: str, args: dict, image_id: str | None = None) -> dict:
    """统一分发。analyze_image 的 image_id 由请求注入（防并发串图）。"""
    if name == "list_today_news":
        return list_today_news(page=int(args.get("page", 1)), tag=str(args.get("tag", "")))
    if name == "search_news_library":
        return search_news_library(str(args.get("query", "")))
    if name == "match_similar_tags":
        return match_similar_tags(str(args.get("query", "")))
    if name == "web_search_news":
        return web_search_news(str(args.get("query", "")))
    if name == "analyze_image":
        return analyze_image(image_id or "", str(args.get("question", "")))
    return {"error": f"未知工具: {name}"}
