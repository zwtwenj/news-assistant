// 后管 API 封装：独立于 C 端 api()（不走 /auth/refresh 续期，401 直接回后管登录页）
export class AdminApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function adminApi<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`/api/v1${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (resp.status === 401 && typeof window !== "undefined") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    // 非 hook 上下文（lib 层）拿不到 useRouter，整页跳转登出全部本地态
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `/admin/login?next=${next}`;
    return new Promise(() => {}); // 挂起，等待跳转
  }
  if (!resp.ok) {
    let detail = `请求失败（HTTP ${resp.status}）`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // 非 JSON 响应体，保留默认消息
    }
    throw new AdminApiError(detail, resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
