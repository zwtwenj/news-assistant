"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { adminApi } from "@/lib/admin-api";

const MENU: { href: string; label: string; icon: string; disabled?: boolean }[] = [
  { href: "/admin", label: "仪表盘", icon: "📊" },
  { href: "/admin/hosts", label: "主播管理", icon: "🎙️" },
  { href: "/admin/news", label: "新闻管理", icon: "📰", disabled: true },
  { href: "/admin/news/new", label: "添加新闻", icon: "➕", disabled: true },
  { href: "/admin/feeds", label: "源管理", icon: "📡", disabled: true },
  { href: "/admin/accounts", label: "账号管理", icon: "👤" },
];

export default function AdminSidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const logout = async () => {
    await adminApi("/admin/auth/logout", { method: "POST" }).catch(() => {});
    router.push("/admin/login");
  };

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-solid border-black/[.06] bg-white px-3 py-4 dark:border-white/[.12] dark:bg-black">
      <div className="mb-4 px-3">
        <p className="text-sm font-semibold text-black dark:text-zinc-50">新闻助手</p>
        <p className="text-xs text-zinc-400">管理后台</p>
      </div>
      <nav className="flex-1 space-y-1">
        {MENU.map((item) => {
          const active = !item.disabled && pathname === item.href;
          if (item.disabled) {
            return (
              <span
                key={item.label}
                className="flex cursor-not-allowed items-center gap-2 rounded-md px-3 py-2 text-sm text-zinc-300 dark:text-zinc-600"
                title="即将上线"
              >
                <span>{item.icon}</span>
                {item.label}
                <span className="ml-auto text-xs">A2</span>
              </span>
            );
          }
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                active
                  ? "flex items-center gap-2 rounded-md bg-black/[.06] px-3 py-2 text-sm font-medium text-black dark:bg-white/[.12] dark:text-zinc-50"
                  : "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-zinc-600 hover:bg-black/[.04] dark:text-zinc-400 dark:hover:bg-white/[.06]"
              }
            >
              <span>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <button
        type="button"
        onClick={() => void logout()}
        className="mt-4 rounded-md px-3 py-2 text-left text-sm text-zinc-500 hover:bg-black/[.04] dark:text-zinc-400 dark:hover:bg-white/[.06]"
      >
        退出登录
      </button>
    </aside>
  );
}
