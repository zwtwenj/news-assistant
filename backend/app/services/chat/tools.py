"""聊天工具集 v3（2026-09 重构）：全部读 articles_v3，封闭类目替代标签。

工具一览：
- list_news_v3：最新新闻分页 + 类目过滤（替代旧 list_today_news + match_similar_tags 两步联动）
- search_news_v3：hybrid 语义检索（dense+BM25 加权融合 → rerank，替代旧 search_news_library）
- web_search_news：博查联网搜索（不变）
- analyze_image：Qwen-VL 看图（不变）
"""

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

def list_news_v3(page: int = 1, category: str = "") -> dict:
    """最新新闻分页（读 articles_v3），可选类目过滤（主类 or 副类命中）。

    时间窗自适应：不足 3 条自动放宽 24h → 72h，把实际窗口返回给 LLM 如实描述。
    """
    page = max(1, page)
    cat_filter = ""
    params_extra: dict[str, Any] = {}
    if category:
        cat_filter = "AND (category = :cat OR aux_categories @> CAST(:cat_arr AS jsonb))"
        params_extra = {"cat": category, "cat_arr": f'["{category}"]'}
    sql = text(
        f"""
        SELECT id, title, url, source, category, publish_time
        FROM articles_v3
        WHERE deleted_at IS NULL AND fetch_status = 'succeeded'
          AND (content_quality IS NULL OR content_quality <> 'bad')
          AND publish_time >= :since {cat_filter}
        ORDER BY publish_time DESC, id DESC
        LIMIT :limit OFFSET :offset
        """
    )
    count_sql = text(
        f"""
        SELECT count(*) FROM articles_v3
        WHERE deleted_at IS NULL AND fetch_status = 'succeeded'
          AND (content_quality IS NULL OR content_quality <> 'bad')
          AND publish_time >= :since {cat_filter}
        """
    )
    total, window_hours = 0, 24
    for window_hours in (24, 72):
        params: dict[str, Any] = {
            "since": datetime.now(UTC) - timedelta(hours=window_hours),
            "limit": PAGE_SIZE,
            "offset": (page - 1) * PAGE_SIZE,
            **params_extra,
        }
        with SessionLocal() as db:
            total = db.execute(count_sql, params).scalar() or 0
            if total >= 3 or window_hours == 72:
                rows = db.execute(sql, params).all()
                break

    from zoneinfo import ZoneInfo

    def _fmt(dt) -> str:
        if dt.tzinfo is None:
            from datetime import UTC as _UTC

            dt = dt.replace(tzinfo=_UTC)
        return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")

    items = [
        {
            "id": r.id,
            "title": r.title,
            "url": r.url,
            "source": r.source,
            "category": r.category or "未分类",
            "publish_time": _fmt(r.publish_time),
        }
        for r in rows
    ]
    has_more = page * PAGE_SIZE < total
    return {
        "total": total, "page": page, "window_hours": window_hours,
        "has_more": has_more, "items": items,
    }


def search_news_v3(query: str, top_k: int = 5) -> dict:
    """hybrid 语义检索（dense+BM25 加权融合 → rerank → 回表 articles_v3）。"""
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
                "category": s.get("category"),
                "material": s["material"],
                "score": s["rerank_score"],
            }
            for s in sources
        ],
    }


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
            s.dashscope_base_url.rstrip("/").removesuffix("/compatible-mode/v1")
            + "/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {s.dashscope_api_key}"},
            json={
                "model": "qwen-vl-plus",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {
                                "url": f"data:{item['mime']};base64,{item['b64']}"
                            }},
                            {"type": "text", "text": question},
                        ],
                    }
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
        return {"answer": answer}
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).warning("image analyze fail: {}", str(exc)[:80])
        return {"error": f"图片分析失败: {str(exc)[:60]}"}


# ---------- schema 与分发 ----------

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_news_v3",
            "description": (
                "查询最新新闻列表（24h 窗口，不足自动放宽到 72h，结果带 window_hours，"
                "表述时按实际窗口说'最近24/72小时'），每页 10 条，带类目标签。"
                "用户想看最新/今日新闻时使用；说'还有吗/继续'时传 page+1；"
                "想看某类新闻时传 category。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": "页码，从 1 开始", "default": 1},
                    "category": {
                        "type": "string",
                        "description": (
                            "可选，按封闭类目过滤。合法值：时政国内/国际/财经/科技/体育/"
                            "娱乐/社会/军事/法治/教育/文化/健康/汽车/就业社保/农业农村/"
                            "消费/气象灾害"
                        ),
                        "default": "",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news_v3",
            "description": (
                "在新闻库中按主题语义检索相关新闻（返回标题/正文节选/类目/来源链接）。"
                "用户询问某主题的相关报道、事件背景、新闻细节时使用。结果要注明来源标题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索主题，如'民营经济政策'"},
                },
                "required": ["query"],
            },
        },
    },
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
                        "type": "string",
                        "description": "想了解图片的什么，如'这是什么地方'",
                    },
                },
            },
        },
    },
]


def execute_tool(name: str, args: dict, image_id: str | None = None) -> dict:
    """统一分发。analyze_image 的 image_id 由请求注入（防并发串图）。"""
    if name == "list_news_v3":
        return list_news_v3(
            page=int(args.get("page", 1)), category=str(args.get("category", ""))
        )
    if name == "search_news_v3":
        return search_news_v3(str(args.get("query", "")))
    if name == "web_search_news":
        return web_search_news(str(args.get("query", "")))
    if name == "analyze_image":
        return analyze_image(image_id or "", str(args.get("question", "")))
    return {"error": f"未知工具: {name}"}
