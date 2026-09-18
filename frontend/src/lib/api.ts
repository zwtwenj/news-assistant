// 统一 API 封装：走 Next rewrites 代理（/api/* → 后端 8000），同域自动带 cookie
//
// 错误分类（对应后端 core/errcode.py 码表）：
//   - 网络不可达（后端重启/断网）：fetch 本地抛异常 → NETWORK，页面提示「服务不可用」，不清登录态
//   - 401 + code 40101（access 过期）：静默调 /auth/refresh 换新 token 并重放原请求（单飞锁防并发刷新）
//   - 401 + 40100/40102/40103（未登录/refresh 失效/封禁）：抛给 AuthProvider 登出

export class ApiError extends Error {
  status: number;
  code: number; // 业务码；-1 = 网络不可达（无后端响应）

  constructor(message: string, status: number, code = -1) {
    super(message);
    this.status = status;
    this.code = code;
  }

  get isNetworkError(): boolean {
    return this.code === -1;
  }
}

// 后端业务码（与 backend/app/core/errcode.py 保持一致）
export const CODE = {
  UNAUTHED: 40100,
  TOKEN_EXPIRED: 40101,
  REFRESH_INVALID: 40102,
  ACCOUNT_UNUSABLE: 40103,
} as const;

const NETWORK_MESSAGE = "服务暂不可用，请稍后重试";

let refreshInFlight: Promise<boolean> | null = null;

// ============ 客户端接口耗时采集（接口分析标准的客户端侧） ============
// 同源 /api/* 请求可读完整 Resource Timing 分段；按响应头 x-request-id 关联
// 服务器日志行，sendBeacon 攒批上报。全程 try/catch，绝不影响业务请求。

interface ClientTiming {
  request_id: string;
  dns_ms: number | null;
  tcp_ms: number | null;
  tls_ms: number | null;
  ttfb_ms: number | null;
  download_ms: number | null;
  total_ms: number | null;
}

const TIMING_BATCH = 5;
const TIMING_FLUSH_MS = 30_000;
const TIMING_LOOKUP_DELAY_MS = 500;
const timingBuffer: ClientTiming[] = [];
let timingTimer: ReturnType<typeof setTimeout> | null = null;

// Resource Timing 条目在响应体消费完之后才异步提交进缓冲区，响应刚返回就
// 同步查 getEntriesByName 会拿到空——用 PerformanceObserver 常驻接收条目，
// 上报时延迟一拍再从 Map 里取
const timingEntries = new Map<string, PerformanceResourceTiming>();
try {
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      timingEntries.set(entry.name, entry as PerformanceResourceTiming);
    }
  }).observe({ type: "resource", buffered: true });
} catch {
  // 老浏览器无 PerformanceObserver：放弃采集，不影响业务
}

function flushClientTiming() {
  timingTimer = null;
  if (!timingBuffer.length) return;
  const batch = timingBuffer.splice(0, 20);
  try {
    const blob = new Blob([JSON.stringify({ items: batch })], { type: "application/json" });
    navigator.sendBeacon("/api/v1/metrics/client-timing", blob);
  } catch {
    // 上报失败静默丢弃——监控绝不干扰业务
  }
}

function collectClientTiming(path: string, resp: Response) {
  try {
    if (path.startsWith("/metrics/")) return; // 不采集关于采集的请求
    const requestId = resp.headers.get("x-request-id");
    if (!requestId) return;
    const url = `${location.origin}/api/v1${path}`;
    setTimeout(() => {
      try {
        const entry = timingEntries.get(url);
        if (!entry || !entry.responseStart) return;
        timingEntries.delete(url);
        const r = (v: number) => (Number.isFinite(v) && v > 0 ? Math.round(v) : null);
        timingBuffer.push({
          request_id: requestId,
          dns_ms: r(entry.domainLookupEnd - entry.domainLookupStart),
          tcp_ms: r(entry.connectEnd - entry.connectStart),
          tls_ms:
            entry.secureConnectionStart > 0
              ? r(entry.connectEnd - entry.secureConnectionStart)
              : null,
          ttfb_ms: r(entry.responseStart - entry.startTime),
          download_ms: r(entry.responseEnd - entry.responseStart),
          total_ms: r(entry.responseEnd - entry.startTime),
        });
        if (timingBuffer.length >= TIMING_BATCH) {
          flushClientTiming();
        } else if (!timingTimer) {
          timingTimer = setTimeout(flushClientTiming, TIMING_FLUSH_MS);
        }
      } catch {
        // 采集失败静默
      }
    }, TIMING_LOOKUP_DELAY_MS);
  } catch {
    // 采集失败静默
  }
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        // 原生 fetch 绕过 api() 自身的 401 拦截（防死循环）
        const resp = await fetch("/api/v1/auth/refresh", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        return resp.ok; // 401=refresh 失效；网络异常同样视为失败
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

interface ErrorEnvelope {
  code?: number;
  detail?: string;
}

async function parseError(resp: Response): Promise<ApiError> {
  let detail = `请求失败（HTTP ${resp.status}）`;
  let code = -1;
  try {
    const body = (await resp.json()) as ErrorEnvelope;
    if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    if (typeof body?.code === "number") code = body.code;
  } catch {
    // 非 JSON 响应体，保留默认消息
  }
  return new ApiError(detail, resp.status, code);
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  // FormData（文件上传）不能设 Content-Type——由浏览器自动生成带 boundary 的 multipart 头
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData;
  const baseHeaders = isFormData
    ? options?.headers
    : { "Content-Type": "application/json", ...options?.headers };
  const doFetch = () =>
    fetch(`/api/v1${path}`, {
      credentials: "include",
      headers: baseHeaders,
      ...options,
    });

  let resp: Response;
  try {
    resp = await doFetch();
  } catch {
    // 后端不可达/断网：不是登录问题，绝不能触发登出
    throw new ApiError(NETWORK_MESSAGE, -1);
  }

  // 反向代理下后端不可达的两种形态都按网络不可达处理（不登出）：
  // ① 502/503/504（nginx 网关错误）② 500 且响应体非 JSON（Next dev 代理错误页）
  if ([502, 503, 504].includes(resp.status)) {
    throw new ApiError(NETWORK_MESSAGE, -1);
  }
  if (resp.status === 500) {
    const text = await resp.text();
    try {
      JSON.parse(text);
    } catch {
      throw new ApiError(NETWORK_MESSAGE, -1);
    }
    throw new ApiError("服务器开小差了，请稍后重试", 500, 50000);
  }
  // access 过期：静默续期一次后重放（40101 与旧后端无 code 的 401 都走这里）
  if (resp.status === 401 && !path.startsWith("/auth/")) {
    const body = (await resp.clone().json().catch(() => ({}))) as ErrorEnvelope;
    const code = typeof body.code === "number" ? body.code : CODE.TOKEN_EXPIRED;
    if (code === CODE.TOKEN_EXPIRED) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        try {
          resp = await doFetch();
        } catch {
          throw new ApiError(NETWORK_MESSAGE, -1);
        }
      }
    }
  }

  // 采集点：此处 resp 已是最终响应（含 401 续期重放后），ok 与业务错误都要计时
  collectClientTiming(path, resp);

  if (!resp.ok) throw await parseError(resp);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
