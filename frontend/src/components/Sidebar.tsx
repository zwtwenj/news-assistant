"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const MENU: { href: string; label: string }[] = [
  { href: "/", label: "数据总览" },
  { href: "/news", label: "新闻列表" },
  { href: "/podcasts", label: "播客生成" },
  { href: "/podcasts/history", label: "我的播客" },
  { href: "/chat", label: "AI 助手" },
  { href: "/account", label: "我的账号" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-56 shrink-0 border-r border-solid border-border bg-sidebar/60 px-3.5 py-7 md:block">
      <nav className="sticky top-[60px] space-y-0.5">
        {MENU.map((item, i) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                active
                  ? "flex items-center gap-3 rounded-lg border-l-2 border-primary bg-primary/[.07] px-3 py-2.5 text-[13px] font-medium text-primary"
                  : "flex items-center gap-3 rounded-lg border-l-2 border-transparent px-3 py-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              }
            >
              <span
                className={
                  active
                    ? "font-mono text-[10px] text-primary"
                    : "font-mono text-[10px] text-muted-foreground/50"
                }
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
