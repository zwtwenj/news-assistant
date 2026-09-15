"use client";

/*
 * GitHub OAuth 回调页：GitHub 302 回来带 code/state，
 * 交给后端换 token（Set-Cookie 本站会话）→ 成功后跳 next（state 中携带）。
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import GithubIcon from "@/components/GithubIcon";
import Spinner from "@/components/Spinner";
import { ApiError, api } from "@/lib/api";

export default function GithubCallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-black">
          <Spinner label="加载中…" />
        </main>
      }
    >
      <CallbackInner />
    </Suspense>
  );
}

function CallbackInner() {
  const searchParams = useSearchParams();
  const [error, setError] = useState("");
  const triedRef = useRef(false); // StrictMode 双挂载只换一次（code 一次性）

  useEffect(() => {
    if (triedRef.current) return;
    triedRef.current = true;
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    if (!code || !state) {
      setError("授权参数缺失，请重新登录");
      return;
    }
    api<{ next: string }>("/auth/github/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    })
      .then((resp) => {
        // 整页跳转（非 router.push）：OAuth 回调后需完整重载让 middleware 与
        // AuthProvider 带着新 cookie 重新初始化，客户端路由可能出现不导航的竞态
        const next = resp.next && resp.next.startsWith("/") ? resp.next : "/";
        window.location.href = next;
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "GitHub 登录失败，请重试");
      });
  }, [searchParams]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-zinc-50 px-4 dark:bg-black">
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-solid border-black/[.08] bg-white p-8 text-center dark:border-white/[.145] dark:bg-black">
        {error ? (
          <>
            <p className="text-sm text-red-600">{error}</p>
            <button
              type="button"
              onClick={() => (window.location.href = "/login")}
              className="w-full rounded-md bg-foreground py-2.5 font-medium text-background"
            >
              返回登录
            </button>
          </>
        ) : (
          <div className="flex flex-col items-center gap-3 py-4">
            <GithubIcon className="size-6 text-zinc-400" />
            <Spinner label="GitHub 登录中…" />
          </div>
        )}
      </div>
    </main>
  );
}
