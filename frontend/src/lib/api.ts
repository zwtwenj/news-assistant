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
  const doFetch = () =>
    fetch(`/api/v1${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...options?.headers },
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

  if (!resp.ok) throw await parseError(resp);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
