"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const MENU: { href: string; label: string; icon: string; disabled?: boolean }[] = [
  { href: "/", label: "数据总览", icon: "📊" },
  { href: "/news", label: "新闻列表", icon: "📰" },
  { href: "/account", label: "我的账号", icon: "👤" },
  { href: "", label: "播客生成", icon: "🎙️", disabled: true }, // M2
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-56 shrink-0 border-r border-solid border-black/[.06] bg-white px-3 py-4 dark:border-white/[.12] dark:bg-black md:block">
      <nav className="sticky top-16 space-y-1">
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
                <span className="ml-auto text-xs">M2</span>
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
    </aside>
  );
}
