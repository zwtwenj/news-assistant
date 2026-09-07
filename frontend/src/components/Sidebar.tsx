"use client";

import { BarChart3, Bot, Headphones, Mic, Newspaper, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const MENU: { href: string; label: string; icon: LucideIcon; disabled?: boolean }[] = [
  { href: "/", label: "数据总览", icon: BarChart3 },
  { href: "/news", label: "新闻列表", icon: Newspaper },
  { href: "/podcasts", label: "播客生成", icon: Mic },
  { href: "/podcasts/history", label: "我的播客", icon: Headphones },
  { href: "/chat", label: "AI 助手", icon: Bot },
  { href: "/account", label: "我的账号", icon: User },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-56 shrink-0 border-r border-solid border-border bg-card px-3 py-4 md:block">
      <nav className="sticky top-16 space-y-1">
        {MENU.map((item) => {
          const active = !item.disabled && pathname === item.href;
          const Icon = item.icon;
          if (item.disabled) {
            return (
              <span
                key={item.label}
                className="flex cursor-not-allowed items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground/50"
                title="即将上线"
              >
                <Icon className="size-4" />
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
                  ? "flex items-center gap-2.5 rounded-md bg-muted px-3 py-2 text-sm font-medium text-foreground"
                  : "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
              }
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
