"""聊天助手（小讯）：SSE 流式对话 + 图片上传 + 语音输入/播报。

流程：记忆检索(Viking per-user) → RAG(播客同款检索) → LLM 流式(工具循环)
→ 回答完成后异步写记忆。SSE 事件：meta / delta / tool / done / error。
"""

import base64
import json

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.core.redis_client import redis_client
from app.services.chat import memory as memory_svc
from app.services.chat import rag as rag_svc
from app.services.chat import tools as tools_svc
from app.services.llm import chat_client

router = APIRouter(prefix="/chat", tags=["chat"])

CHAT_HOURLY_LIMIT = 20
MAX_CONTEXT_MESSAGES = 60
MAX_TOOL_ROUNDS = 3

SYSTEM_PROMPT = """你是「小讯」，一个国内新闻助手，语气亲切、回答简洁有条理。回答规则：
1. 优先根据【新闻资料】回答，引用时注明来源标题；资料与问题不符时不要硬凑。
2. 用户想看最新/今日新闻时，调用 list_today_news 查询（每页 10 条，用户说"还有吗"就翻下一页；
   想看某类新闻时先用 match_similar_tags 匹配标签再联动查询）。列表数据展示后，文字只做简短总结，
   不要逐条复述标题。
3. 新闻库明显没有相关内容、且问题需要实时或更广的信息时，调用 web_search_news 联网搜索；
   网络结果要标注「来源：网络搜索」，不要把网络内容伪装成新闻资料。
4. 没有相关资料、联网也没有有效结果时，诚实说明"暂无相关资料"，不要编造新闻事实。
5. 用户发送了图片时（system 会告知 image_id），调用 analyze_image 工具查看并分析图片内容，
   不要凭空猜测。
6. 如提供了【用户记忆】，自然地利用它个性化回答（如用户关注的领域），不要生硬罗列。
"""


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    image_id: str | None = Field(default=None, max_length=32)


def _quota_key(user_id: int) -> str:
    import time as _time

    return f"chat:quota:{user_id}:{int(_time.time()) // 3600}"


def _quota_check(user_id: int) -> None:
    current = redis_client.get(_quota_key(user_id))
    if current is not None and int(current) >= CHAT_HOURLY_LIMIT:
        raise HTTPException(status_code=429, detail="聊天次数已达上限（每小时 20 次）")


def _quota_incr(user_id: int) -> None:
    key = _quota_key(user_id)
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 3600)
    pipe.execute()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("")
def chat(body: ChatRequest, user: CurrentUser) -> StreamingResponse:
    """SSE 流式对话。事件：meta(记忆+RAG来源+used_query) → delta → tool → done/error。"""
    _quota_check(user.id)
    if user.viking_user_id is None:
        user.viking_user_id = f"news_u_{user.id}"

    history = [m.model_dump() for m in body.messages[:-1]]
    user_msg = body.messages[-1].content

    async def event_stream():
        try:
            _quota_incr(user.id)
            # ① query 重写（指代消解）——重写结果同时用于 RAG 与记忆检索
            used_query = rag_svc.rewrite_query(history, user_msg)

            # ② 记忆检索 + RAG（并行无依赖但顺序执行，两者互不阻断）
            memories = memory_svc.safe_search(used_query, user.viking_user_id)
            sources = rag_svc.retrieve(used_query)

            # ③ 拼 system prompt
            blocks = [SYSTEM_PROMPT]
            if body.image_id and tools_svc.get_image(body.image_id):
                blocks.append(
                    f"【当前用户上传了一张图片】image_id: {body.image_id}。"
                    "请使用 analyze_image 工具来查看并分析图片内容。"
                )
            mem_block = memory_svc.build_memory_block(memories)
            if mem_block:
                blocks.append(mem_block)
            rag_block = rag_svc.build_rag_block(sources)
            if rag_block:
                blocks.append(rag_block)
            system = "\n\n".join(blocks)

            # ④ 消息序列（截最近 60 条）
            msgs = [{"role": "system", "content": system}]
            msgs += history[-MAX_CONTEXT_MESSAGES:]
            msgs.append({"role": "user", "content": user_msg})

            yield _sse({
                "type": "meta",
                "used_query": used_query,
                "memories": [m["summary"] for m in memories],
                "rag_sources": [
                    {"title": s["title"], "url": s["url"], "score": s["rerank_score"]}
                    for s in sources
                ],
            })

            # ⑤ LLM 流式 + 工具循环
            answer = ""
            usage = {}
            for _round in range(MAX_TOOL_ROUNDS + 1):
                stream = chat_client.stream_chat(
                    msgs, tools=tools_svc.TOOLS_SCHEMA
                )
                pending_calls = {}
                for chunk in stream:
                    if chunk.usage:
                        usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens or 0,
                            "completion_tokens": chunk.usage.completion_tokens or 0,
                        }
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if delta and delta.content:
                        answer += delta.content
                        yield _sse({"type": "delta", "content": delta.content})
                    if delta and delta.tool_calls:
                        for tc in delta.tool_calls:
                            slot = pending_calls.setdefault(
                                tc.index, {"id": "", "name": "", "args": ""}
                            )
                            if tc.id:
                                slot["id"] = tc.id
                            if tc.function and tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                slot["args"] += tc.function.arguments

                if not pending_calls:
                    break
                # 执行工具并回填
                msgs.append({
                    "role": "assistant",
                    "content": answer or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c["args"]},
                        }
                        for c in pending_calls.values()
                    ],
                })
                for c in pending_calls.values():
                    try:
                        args = json.loads(c["args"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = tools_svc.execute_tool(c["name"], args, image_id=body.image_id)
                    yield _sse({"type": "tool", "name": c["name"], "result": result})
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": c["id"],
                        "content": json.dumps(result, ensure_ascii=False)[:6000],
                    })
                answer = ""

            # ⑥ 写记忆（下一轮可召回）
            if answer or msgs:
                memory_svc.safe_add(
                    [
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": answer},
                    ],
                    user.viking_user_id,
                )
            yield _sse({"type": "done", "usage": usage, "answer_length": len(answer)})
        except Exception as exc:  # noqa: BLE001
            logger.opt(exception=True).error("chat stream error: {}", str(exc)[:120])
            yield _sse({"type": "error", "message": str(exc)[:300]})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------- 图片上传 ----------

_ALLOWED_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


@router.post("/upload-image")
def upload_image(user: CurrentUser, file: UploadFile) -> dict:
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(status_code=422, detail="仅支持 jpg/png/webp")
    data = file.file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="图片不能超过 5MB")
    import secrets

    image_id = secrets.token_hex(8)
    tools_svc.store_image(image_id, base64.b64encode(data).decode(), file.content_type)
    return {"image_id": image_id, "expires_in": 300}


# ---------- 语音输入（ASR：百炼 qwen-audio-3.0-asr-flash，对齐 blog demo） ----------

_ASR_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc"
    "/multimodal-generation/generation"
)
_ASR_MODEL = "qwen-audio-3.0-asr-flash"
_MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 约 1 分钟压缩录音；防绕过前端投递长音频烧钱
# 浏览器 MIME → DashScope format 参数
_ASR_FORMAT = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/ogg": "ogg",
}


@router.post("/voice-input")
def voice_input(user: CurrentUser, file: UploadFile) -> dict:
    """语音转文字：录音 → base64 内联 → Qwen-Audio-3.0-ASR-Flash → {"text"}。

    静音/噪音返回空 text（前端静默不填入）；上游失败抛 502 带原因。
    """
    import httpx

    from app.core.config import get_settings

    data = file.file.read()
    if len(data) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=422, detail="音频过大（上限 2MB，约 1 分钟）")
    if len(data) < 100:
        raise HTTPException(status_code=422, detail="音频过短（可能是误触）")

    mime = file.content_type or "audio/webm"
    fmt = _ASR_FORMAT.get(mime, "wav")
    b64 = base64.b64encode(data).decode()
    s = get_settings()
    try:
        resp = httpx.post(
            _ASR_URL,
            headers={"Authorization": f"Bearer {s.dashscope_api_key}"},
            json={
                "model": _ASR_MODEL,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {"data": f"data:{mime};base64,{b64}"},
                                }
                            ],
                        }
                    ]
                },
                "parameters": {"format": fmt, "language_hints": ["zh"]},
            },
            timeout=30,
        )
        body = resp.json()
        if "NO_WORDS" in str(body.get("message", "")):  # 无语音内容（安静/噪音）
            return {"text": ""}
        if resp.status_code != 200 or body.get("code", "") not in (0, "", None):
            raise HTTPException(
                status_code=502,
                detail=f"语音识别失败: {body.get('message', resp.text[:150])}",
            )
        return {"text": (body.get("output") or {}).get("text", "").strip()}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"语音转写异常: {str(exc)[:150]}"
        ) from exc


# ---------- 语音输出（MiniMax TTS，复用播客 tts 参数） ----------


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/voice-output")
def voice_output(body: TTSIn, user: CurrentUser) -> Response:
    import httpx

    from app.core.config import get_settings

    s = get_settings()
    resp = httpx.post(
        s.minimax_base_url.rstrip("/").removesuffix("/v1") + "/v1/t2a_v2",
        headers={"Authorization": f"Bearer {s.minimax_api_key}"},
        json={
            "model": "speech-02-turbo",
            "text": body.text[:2000],
            "stream": False,
            "voice_setting": {"voice_id": "female-shaonv", "speed": 1, "vol": 1, "pitch": 0},
            "audio_setting": {
                "sample_rate": 24000, "bitrate": 128000, "format": "wav", "channel": 1,
            },
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="语音合成失败")
    data = resp.json()
    audio_hex = (data.get("data") or {}).get("audio", "")
    if not audio_hex:
        raise HTTPException(status_code=502, detail="语音合成无音频")
    return Response(content=bytes.fromhex(audio_hex), media_type="audio/wav")
