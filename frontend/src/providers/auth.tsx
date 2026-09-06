"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { isProtectedPath } from "@/lib/auth-guard";

export type User = {
  id: number;
  phone: string;
  status: string;
  created_at: string;
};

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  reload: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  reload: async () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false); // 后端不可达：不登出、不跳登录
  const router = useRouter();
  const pathname = usePathname();

  // 取当前用户：返回结果由调用方应用（供挂载 effect 与显式 reload 共用）
  const loadUser = useCallback(async (): Promise<
    { user: User } | { unauth: true } | { network: true }
  > => {
    // api() 内部已带「40101 → 静默 refresh → 重放」逻辑；
    // 走到这里仍 401 = 未登录/refresh 失效/封禁。
    // 网络不可达（ApiError 非 401）：不清登录态——后端短暂重启不应把用户踢下线。
    try {
      return { user: await api<User>("/users/me") };
    } catch (e) {
      if (e instanceof ApiError && e.status !== 401) return { network: true };
      return { unauth: true };
    }
  }, []);

  const applyResult = (r: Awaited<ReturnType<typeof loadUser>>) => {
    if ("user" in r) {
      setUser(r.user);
      setOffline(false);
    } else if ("network" in r) {
      setOffline(true); // 保留现有 user（SPA 内已有则继续可见）
    } else {
      setUser(null);
      setOffline(false);
    }
    setLoading(false);
  };

  const reload = useCallback(async () => {
    applyResult(await loadUser());
  }, [loadUser]);

  useEffect(() => {
    // setTimeout + clearTimeout：StrictMode 双挂载时第一个定时器被清掉，
    // /users/me 每次进入页面恰好发一次（alive 守卫只防状态应用，防不了请求本身）
    const timer = setTimeout(() => {
      void loadUser().then(applyResult);
    }, 0);
    return () => clearTimeout(timer);
  }, [loadUser]);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST", body: "{}" });
    } catch {
      // 后端不可达也照常清理本地态
    } finally {
      setUser(null);
      setOffline(false);
    }
  }, []);

  // 登录失效时：受保护页面跳登录页（离线时绝不跳——无法区分「未登录」和「连不上」）
  useEffect(() => {
    if (!loading && user === null && !offline && isProtectedPath(pathname)) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, user, offline, pathname, router]);

  // 初次加载即离线（硬刷新 + 后端不可达）：展示服务不可用提示而非踢到登录页
  if (!loading && offline && user === null) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-zinc-50 px-4 dark:bg-black">
        <p className="text-sm text-zinc-500">服务暂不可用，登录状态已保留，请稍后重试</p>
        <button
          type="button"
          onClick={() => void reload()}
          className="rounded-md bg-foreground px-5 py-2 text-sm font-medium text-background"
        >
          重试
        </button>
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, loading, reload, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
