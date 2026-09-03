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

const PIE_COLORS = [
  "#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed",
  "#0891b2", "#db2777", "#65a30d", "#475569", "#ea580c",
];

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Stats>("/news/stats")
      .then(setStats)
      .catch((e) => setError(String(e instanceof Error ? e.message : e)));
  }, []);

  if (error) {
    return <p className="text-sm text-red-600">统计加载失败：{error}</p>;
  }
  if (!stats) {
    return <p className="text-sm text-zinc-400">加载中…</p>;
  }

  const cards: { label: string; value: string; hint?: string }[] = [
    { label: "文章总数", value: String(stats.total) },
    { label: "已入库", value: String(stats.fetch.succeeded), hint: "完成全流程" },
    { label: "内容判重", value: String(stats.fetch.skipped), hint: "SimHash 命中" },
    {
      label: "待处理/失败",
      value: String(stats.fetch.pending + stats.fetch.failed),
      hint: "次日自动补偿",
    },
    { label: "数据源", value: String(stats.feeds), hint: "启用中" },
    { label: "最后更新", value: stats.last_updated_at?.slice(11) ?? "-", hint: stats.last_updated_at?.slice(0, 10) },
  ];

  const dayData = stats.by_day.map((d) => ({
    ...d,
    day: d.date.slice(5), // MM-DD
  }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-black dark:text-zinc-50">数据总览</h1>
        <p className="mt-1 text-sm text-zinc-500">
          流水线每日 02:00 自动运行（采集 → 抓取 → 打标 → 向量化）
        </p>
      </div>

      {/* 指标卡片 */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        {cards.map((c) => (
          <div
            key={c.label}
            className="rounded-lg border border-solid border-black/[.06] bg-white px-4 py-3 dark:border-white/[.12] dark:bg-black"
          >
            <p className="text-xs text-zinc-500">{c.label}</p>
            <p className="mt-1 text-2xl font-semibold text-black dark:text-zinc-50">{c.value}</p>
            {c.hint && <p className="mt-0.5 text-xs text-zinc-400">{c.hint}</p>}
          </div>
        ))}
      </div>

      {/* 图表 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="rounded-lg border border-solid border-black/[.06] bg-white p-4 dark:border-white/[.12] dark:bg-black xl:col-span-2">
          <h2 className="mb-3 text-sm font-medium text-black dark:text-zinc-50">
            每日入库文章（近 14 天）
          </h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dayData}>
                <XAxis dataKey="day" fontSize={12} tickLine={false} />
                <YAxis allowDecimals={false} fontSize={12} tickLine={false} width={28} />
                <Tooltip
                  formatter={(v) => [`${v} 篇`, "入库"]}
                  labelFormatter={(l) => `日期 ${l}`}
                />
                <Bar dataKey="count" fill="#2563eb" radius={[3, 3, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-solid border-black/[.06] bg-white p-4 dark:border-white/[.12] dark:bg-black">
          <h2 className="mb-3 text-sm font-medium text-black dark:text-zinc-50">分类分布</h2>
          <div className="h-64">
            {stats.by_category.length === 0 ? (
              <p className="pt-20 text-center text-sm text-zinc-400">暂无打标数据</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={stats.by_category}
                    dataKey="count"
                    nameKey="tag"
                    innerRadius="45%"
                    outerRadius="80%"
                    paddingAngle={2}
                  >
                    {stats.by_category.map((entry, i) => (
                      <Cell key={entry.tag} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v, name) => [`${v} 篇`, name]} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {stats.by_category.slice(0, 6).map((c, i) => (
              <span key={c.tag} className="flex items-center gap-1 text-xs text-zinc-500">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                />
                {c.tag} {c.count}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
