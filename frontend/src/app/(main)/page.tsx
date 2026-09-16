"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";

type Stats = {
  total: number;
  feeds: number;
  fetch: { succeeded: number; skipped: number; pending: number; failed: number };
  last_updated_at: string | null;
  last_fetched_at: string | null;
  by_day: { date: string; count: number }[];
  by_category: { tag: string; count: number }[];
};

/* 霓虹色板：青为主，紫/绿/粉/黄交替，超出的用灰 */
const PIE_COLORS = [
  "#22d3ee", "#a78bfa", "#34d399", "#f472b6", "#fbbf24", "#52525b",
  "#67e8f9", "#c4b5fd", "#6ee7b7", "#fda4af",
];

const TOOLTIP_STYLE = {
  background: "#16161b",
  border: "1px solid rgba(255,255,255,.1)",
  borderRadius: 10,
  fontSize: 12,
  color: "#e4e4e7",
} as const;

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      api<Stats>("/news/stats")
        .then(setStats)
        .catch((e) => setError(String(e instanceof Error ? e.message : e)));
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  if (error) {
    return <p className="text-sm text-red-400">统计加载失败：{error}</p>;
  }
  if (!stats) {
    return <p className="text-sm text-muted-foreground">加载中…</p>;
  }

  const cards: { label: string; value: string; hint?: string; tone?: string }[] = [
    { label: "文章总数", value: String(stats.total), tone: "text-primary", hint: "全部收录" },
    { label: "已入库", value: String(stats.fetch.succeeded), tone: "text-emerald-400", hint: "完成全流程" },
    { label: "内容判重", value: String(stats.fetch.skipped), tone: "text-[#a78bfa]", hint: "SimHash 命中" },
    {
      label: "待处理/失败",
      value: String(stats.fetch.pending + stats.fetch.failed),
      tone: "text-amber-400",
      hint: "次日自动补偿",
    },
    { label: "数据源", value: String(stats.feeds), hint: "启用中" },
    {
      label: "最后更新",
      value: stats.last_updated_at?.slice(11) ?? "-",
      hint: stats.last_updated_at?.slice(0, 10),
    },
  ];

  const dayData = stats.by_day.map((d) => ({
    ...d,
    day: d.date.slice(5), // MM-DD
  }));
  const maxDay = Math.max(...dayData.map((d) => d.count), 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <h1 className="text-2xl font-bold tracking-wide text-foreground">数据总览</h1>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          采集<span className="font-mono text-primary">→</span>
          抓取<span className="font-mono text-primary">→</span>
          打标<span className="font-mono text-primary">→</span>
          向量化
        </span>
        <span className="ml-auto rounded-md border border-solid border-emerald-400/30 bg-emerald-400/[.07] px-3 py-1 text-[11px] text-emerald-400">
          每日 <b className="font-mono">02:00</b> 自动运行
        </span>
      </div>

      {/* 指标卡片 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {cards.map((c) => (
          <div
            key={c.label}
            className="rounded-xl border border-solid border-border bg-white/[.04] px-4 py-3.5"
          >
            <p className="text-xs text-muted-foreground">{c.label}</p>
            <p
              className={`mt-1.5 font-mono text-[26px] font-bold leading-none tracking-wide ${
                c.tone ?? "text-foreground"
              }`}
            >
              {c.value}
            </p>
            {c.hint && <p className="mt-1.5 text-[11px] text-zinc-600">{c.hint}</p>}
          </div>
        ))}
      </div>

      {/* 图表 */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <div className="rounded-xl border border-solid border-border bg-white/[.04] p-5 xl:col-span-2">
          <div className="mb-3 flex items-baseline">
            <h2 className="text-sm font-semibold text-foreground">每日入库文章</h2>
            <span className="ml-auto text-[11px] text-zinc-600">
              近 14 天 · 日均{" "}
              {dayData.length
                ? Math.round(dayData.reduce((s, d) => s + d.count, 0) / dayData.length)
                : 0}{" "}
              篇
            </span>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dayData}>
                <XAxis
                  dataKey="day"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: "rgba(255,255,255,.1)" }}
                  tick={{ fill: "#52525b", fontFamily: "var(--font-geist-mono)" }}
                />
                <YAxis
                  allowDecimals={false}
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  width={28}
                  tick={{ fill: "#52525b", fontFamily: "var(--font-geist-mono)" }}
                />
                <Tooltip
                  cursor={{ fill: "rgba(255,255,255,.04)" }}
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v) => [`${v} 篇`, "入库"]}
                  labelFormatter={(l) => `日期 ${l}`}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={26}>
                  {dayData.map((d) => (
                    <Cell
                      key={d.date}
                      fill={d.count === maxDay ? "#a78bfa" : "#22d3ee"}
                      fillOpacity={d.count === maxDay ? 1 : 0.9}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-xl border border-solid border-border bg-white/[.04] p-5">
          <div className="mb-3 flex items-baseline">
            <h2 className="text-sm font-semibold text-foreground">分类分布</h2>
            <span className="ml-auto text-[11px] text-zinc-600">按标签统计</span>
          </div>
          <div className="h-56">
            {stats.by_category.length === 0 ? (
              <p className="pt-20 text-center text-sm text-muted-foreground">暂无打标数据</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={stats.by_category}
                    dataKey="count"
                    nameKey="tag"
                    innerRadius="52%"
                    outerRadius="82%"
                    paddingAngle={2}
                    strokeWidth={0}
                  >
                    {stats.by_category.map((entry, i) => (
                      <Cell key={entry.tag} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, name) => [`${v} 篇`, name]} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {stats.by_category.slice(0, 6).map((c, i) => (
              <span key={c.tag} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  className="inline-block size-2 rounded-sm"
                  style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                />
                {c.tag}
                <b className="font-mono font-semibold text-zinc-400">{c.count}</b>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
