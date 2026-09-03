"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { api } from "@/lib/api";
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
  const router = useRouter();
  const pathname = usePathname();

  const reload = useCallback(async () => {
    // api() 内部已带「401 → 静默 refresh → 重放」逻辑；
    // 走到这里仍失败 = 未登录或登录彻底失效
    try {
      setUser(await api<User>("/users/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST", body: "{}" });
    } catch {
      // 后端不可达也照常清理本地态
    } finally {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // 登录失效时：受保护页面跳登录页，携带回跳地址
  useEffect(() => {
    if (!loading && user === null && isProtectedPath(pathname)) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, user, pathname, router]);

  return (
    <AuthContext.Provider value={{ user, loading, reload, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
