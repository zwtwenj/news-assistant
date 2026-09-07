"use client";

/*
 * GitHub OAuth 回调页：GitHub 302 回来带 code/state，
 * 交给后端换 token（Set-Cookie 本站会话）→ 成功后跳 next（state 中携带）。
 */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import GithubIcon from "@/components/GithubIcon";
import Spinner from "@/components/Spinner";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/providers/auth";

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
  const router = useRouter();
  const searchParams = useSearchParams();
  const { reload } = useAuth();
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
      .then(async (resp) => {
        await reload();
        router.push(resp.next && resp.next.startsWith("/") ? resp.next : "/");
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "GitHub 登录失败，请重试");
      });
  }, [reload, router, searchParams]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-zinc-50 px-4 dark:bg-black">
      <div className="w-full max-w-sm space-y-4 rounded-xl border border-solid border-black/[.08] bg-white p-8 text-center dark:border-white/[.145] dark:bg-black">
        {error ? (
          <>
            <p className="text-sm text-red-600">{error}</p>
            <button
              type="button"
              onClick={() => router.push("/login")}
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
