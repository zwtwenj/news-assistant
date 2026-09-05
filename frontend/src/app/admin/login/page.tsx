"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { AdminApiError, adminApi } from "@/lib/admin-api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const valid = username.trim().length >= 1 && password.length >= 1;

  const handleLogin = async () => {
    if (!valid || loading) return;
    setLoading(true);
    setError("");
    try {
      await adminApi("/admin/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next && next.startsWith("/admin") ? next : "/admin");
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "登录失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-zinc-100 px-4 dark:bg-black">
      <div className="w-full max-w-sm space-y-5 rounded-xl border border-solid border-black/[.08] bg-white p-8 dark:border-white/[.145] dark:bg-black">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-black dark:text-zinc-50">管理后台</h1>
          <p className="mt-1 text-sm text-zinc-500">仅限管理员账号</p>
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-zinc-600 dark:text-zinc-400">用户名</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value.slice(0, 50))}
            placeholder="管理员用户名"
            autoComplete="username"
            className="w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-2 text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50"
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm text-zinc-600 dark:text-zinc-400">密码</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value.slice(0, 128))}
            placeholder="请输入密码"
            autoComplete="current-password"
            onKeyDown={(e) => e.key === "Enter" && void handleLogin()}
            className="w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-2 text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50"
          />
        </label>

        {error && <p className="text-center text-sm text-red-600">{error}</p>}

        <button
          type="button"
          disabled={!valid || loading}
          onClick={() => void handleLogin()}
          className="w-full rounded-md bg-foreground py-2.5 font-medium text-background disabled:opacity-40"
        >
          {loading ? "登录中…" : "登录"}
        </button>
      </div>
    </main>
  );
}
