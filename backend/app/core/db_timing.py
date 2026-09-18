"""请求内 SQL 耗时采集：游标事件把每条 SQL 耗时累加进请求持有的列表。

为什么是 ContextVar 持有 list 而不是直接存 int：FastAPI 同步端点在线程池
执行时上下文会被拷贝，int 的 set() 只改线程副本，中间件看不到；list 是
共享对象引用，append 的改动对中间件始终可见。
"""

import time
from contextvars import ContextVar

from sqlalchemy import event

from app.db.session import engine

# 每请求一个 list[float]（单位秒），由 request_logging 中间件创建并清理
db_spans: ContextVar[list[float] | None] = ContextVar("db_spans", default=None)


@event.listens_for(engine, "before_cursor_execute")
def _sql_start(conn, cursor, stmt, params, context, executemany):  # noqa: ANN001
    context._news_sql_t0 = time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _sql_end(conn, cursor, stmt, params, context, executemany):  # noqa: ANN001
    spans = db_spans.get()
    if spans is not None:
        started = getattr(context, "_news_sql_t0", None)
        if started is not None:
            spans.append(time.perf_counter() - started)
