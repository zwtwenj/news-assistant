"""业务错误码（后端统一错误信封 {"code": N, "detail": "..."}，成功响应不带 code）。

前端按 code 分类处理：40101 静默续期重放、40100/40102/40103 登出、其余展示 detail。
网络不可达无后端响应，由前端 fetch 异常本地判定（不走本码表）。
"""

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# 成功
OK = 0

# 4xxxx 客户端
UNAUTHED = 40100  # 未登录（无凭证）
TOKEN_EXPIRED = 40101  # access 过期/无效（前端应静默 refresh 后重放）
REFRESH_INVALID = 40102  # refresh 失效（需重新登录）
ACCOUNT_UNUSABLE = 40103  # 账号不可用（封禁/删除）
VALIDATION = 42200  # 参数校验失败
RATE_LIMITED = 42900  # 限频

# 5xxxx 服务端
INTERNAL = 50000

# 未显式给 code 的 HTTPException 按状态码兜底映射
_STATUS_DEFAULT = {
    401: TOKEN_EXPIRED, 403: 40300, 404: 40400, 409: 40900,
    422: VALIDATION, 429: RATE_LIMITED,
}


class ApiError(HTTPException):
    """带业务码的业务异常：响应体输出 {"code": <code>, "detail": <message>}。"""

    def __init__(self, status_code: int, code: int, message: str):
        super().__init__(status_code=status_code, detail=message)
        self.code = code


async def api_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """统一错误信封：显式 ApiError 用其 code；普通 HTTPException 按状态码兜底。"""
    code = getattr(exc, "code", None) or _STATUS_DEFAULT.get(exc.status_code, INTERNAL)
    return JSONResponse(status_code=exc.status_code, content={"code": code, "detail": exc.detail})


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI 参数校验错误（默认 detail 为数组）也纳入信封。"""
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(
        status_code=422, content={"code": VALIDATION, "detail": jsonable_encoder(exc.errors())}
    )
