"use client";

import { useAuth } from "@/providers/auth";
import GithubIcon from "@/components/GithubIcon";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function TopBar() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push("/");
  };

  return (
    <header className="sticky top-0 z-20 border-b border-solid border-border bg-card/80 backdrop-blur-md">
      <div className="flex w-full items-center justify-between px-7 py-2.5">
        <Link
          href="/"
          className="text-[15px] font-semibold tracking-wide text-foreground"
        >
          新闻助手<span className="animate-pulse text-primary">_</span>
        </Link>
        <div className="flex items-center gap-5 text-xs text-muted-foreground">
          {loading && <span>…</span>}
          {!loading && user && (
            <>
              <span className="flex items-center gap-1.5 text-emerald-400">
                <span className="text-[8px] leading-none">●</span>
                系统在线
              </span>
              <Link
                href="/account"
                className="transition-colors hover:text-foreground"
              >
                {user.phone
                  ? `${user.phone.slice(0, 3)}****${user.phone.slice(-4)}`
                  : `@${user.github_login}`}
              </Link>
              <a
                href="https://github.com/zwtwenj/news-assistant"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1.5 transition-colors hover:text-foreground"
                title="GitHub 开源仓库"
              >
                <GithubIcon className="size-3.5" />
                GitHub 仓库
              </a>
              <button
                type="button"
                onClick={() => void handleLogout()}
                className="transition-colors hover:text-foreground"
              >
                退出
              </button>
            </>
          )}
          {!loading && !user && (
            <Link
              href="/login"
              className="rounded-md border border-border bg-white/[.04] px-3.5 py-1.5 transition-colors hover:border-primary/40 hover:text-primary"
            >
              登录
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
