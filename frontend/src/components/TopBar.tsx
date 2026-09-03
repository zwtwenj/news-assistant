"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/providers/auth";

export default function TopBar() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push("/");
  };

  return (
    <header className="sticky top-0 z-10 border-b border-solid border-black/[.06] bg-white dark:border-white/[.12] dark:bg-black">
      <div className="flex w-full items-center justify-between px-6 py-3">
        <Link href="/" className="text-lg font-semibold text-black dark:text-zinc-50">
          新闻助手
        </Link>
        <div className="flex items-center gap-4 text-sm">
          {loading && <span className="text-zinc-400">…</span>}
          {!loading && user && (
            <>
              <Link href="/account" className="text-zinc-600 hover:text-black dark:text-zinc-400">
                {user.phone.slice(0, 3)}****{user.phone.slice(-4)}
              </Link>
              <button
                type="button"
                onClick={() => void handleLogout()}
                className="rounded-md border border-solid border-black/[.08] px-3 py-1 dark:border-white/[.145]"
              >
                退出
              </button>
            </>
          )}
          {!loading && !user && (
            <Link
              href="/login"
              className="rounded-md bg-foreground px-3 py-1 text-background"
            >
              登录
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
