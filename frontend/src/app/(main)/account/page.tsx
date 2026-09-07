"use client";

import Link from "next/link";

import { useAuth } from "@/providers/auth";

export default function AccountPage() {
  const { user, loading } = useAuth();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-zinc-50 px-4 dark:bg-black">
      <div className="w-full max-w-sm space-y-5 rounded-xl border border-solid border-black/[.08] bg-white p-8 dark:border-white/[.145] dark:bg-black">
        <h1 className="text-center text-2xl font-semibold text-black dark:text-zinc-50">
          我的账号
        </h1>
        {loading && <p className="text-center text-zinc-400">加载中…</p>}
        {user && (
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-zinc-500">用户 ID</dt>
              <dd className="text-black dark:text-zinc-50">{user.id}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-zinc-500">手机号</dt>
              <dd className="text-black dark:text-zinc-50">
                {user.phone ? `${user.phone.slice(0, 3)}****${user.phone.slice(-4)}` : "未绑定"}
              </dd>
            </div>
            {user.github_login && (
              <div className="flex justify-between">
                <dt className="text-zinc-500">GitHub</dt>
                <dd className="text-black dark:text-zinc-50">@{user.github_login}</dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-zinc-500">状态</dt>
              <dd className="text-black dark:text-zinc-50">{user.status}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-zinc-500">注册时间</dt>
              <dd className="text-black dark:text-zinc-50">{user.created_at}</dd>
            </div>
          </dl>
        )}
        <Link href="/" className="block text-center text-sm text-zinc-500 hover:text-black">
          返回首页
        </Link>
      </div>
    </main>
  );
}
