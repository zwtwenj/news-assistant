// 统一 API 封装：走 Next rewrites 代理（/api/* → 后端 8000），同域自动带 cookie
//
// 401 自动续期：任意请求 401（access 过期）时，静默调一次 /auth/refresh 换新
// token 并重放原请求；refresh 也失败则按未登录处理。单飞锁防止并发 401 触发多次刷新。
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        // 注意：这里用原生 fetch，绕过 api() 自身的 401 拦截（防死循环）
        const resp = await fetch("/api/v1/auth/refresh", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        return resp.ok;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const doFetch = () =>
    fetch(`/api/v1${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...options?.headers },
      ...options,
    });

  let resp = await doFetch();

  // 401 且非刷新接口本身：尝试一次静默续期后重放（只重放一次）
  if (resp.status === 401 && !path.startsWith("/auth/refresh")) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      resp = await doFetch();
    }
  }

  if (!resp.ok) {
    let detail = `请求失败（HTTP ${resp.status}）`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // 非 JSON 响应体，保留默认消息
    }
    throw new ApiError(detail, resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
