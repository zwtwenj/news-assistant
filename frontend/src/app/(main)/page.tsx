"use client";

import { useRouter } from "next/navigation";
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

import Spinner from "@/components/Spinner";
import { api } from "@/lib/api";

type Stats = {
  total: number;
  feeds: number;
  fetch: { succeeded: number; skipped: number; pending: number; failed: number };
  last_updated_at: string | null;
  last_fetched_at: string | null;
  by_day: { date: string; count: number }[];
  by_category: { tag: string; count: number }[];
  by_feed: {
    id: number;
    name: string;
    enabled: boolean;
    last_fetched_at: string | null;
    today: number;
    total: number;
    sample_source: string | null;
  }[];
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
/* Tooltip 的文字色必须单独给（contentStyle 不影响 item/label 的默认深色） */
const TOOLTIP_ITEM = { color: "#e4e4e7" } as const;
const TOOLTIP_LABEL = { color: "#a1a1aa" } as const;

export default function DashboardPage() {
  const router = useRouter();
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
    // 页面级加载：垂直居中并放大一档
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <Spinner label="数据同步中" className="scale-150" />
      </div>
    );
  }

  const retryCount = stats.fetch.pending + stats.fetch.failed;
  const dayData = stats.by_day.map((d) => ({ ...d, day: d.date.slice(5) }));
  const maxDay = Math.max(...dayData.map((d) => d.count), 0);
  const tagged = stats.by_category.reduce((s, c) => s + c.count, 0);

  return (
    <div className="space-y-4">
      {/* 行动警示条：唯一需要"行动吗"判断的信号，无待处理时隐藏 */}
      {retryCount > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-solid border-amber-400/30 bg-amber-400/[.06] px-4 py-2.5 text-[12.5px] text-amber-400">
          <span>⚠</span>
          <span>
            昨日 <b className="font-mono font-bold">{retryCount}</b> 条待处理/失败，将在下一轮流水线自动补偿重试
          </span>
          <button
            type="button"
            onClick={() => router.push("/news?failed=1")}
            className="ml-auto rounded-md border border-solid border-amber-400/35 px-3 py-1 text-[11.5px] transition-colors hover:bg-amber-400/10"
          >
            查看失败明细
          </button>
        </div>
      )}

      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-bold tracking-wide text-foreground">数据总览</h1>
        {stats.last_updated_at && (
          <span className="rounded-md border border-solid border-emerald-400/30 bg-emerald-400/[.06] px-3 py-1 text-[11.5px] text-emerald-400">
            最后更新 <b className="font-mono">{stats.last_updated_at}</b>
          </span>
        )}
      </div>

      {/* 管道即界面：数字住在流程节点里 */}
      <div className="grid grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] items-stretch gap-x-2">
        <div className="rounded-2xl border border-solid border-border bg-white/[.04] px-5 py-4">
          <p className="font-mono text-[10.5px] tracking-[2px] text-zinc-600">01 · INGEST</p>
          <p className="mt-2.5 text-[13px] text-muted-foreground">数据源采集</p>
          <p className="mt-1 font-mono text-[34px] font-bold leading-none text-primary">{stats.feeds}</p>
          <p className="mt-1.5 text-[11px] text-zinc-500">全部启用中</p>
        </div>
        <div className="flex items-center justify-center font-mono text-lg text-primary opacity-70">→</div>
        <div className="rounded-2xl border border-solid border-border bg-white/[.04] px-5 py-4">
          <p className="font-mono text-[10.5px] tracking-[2px] text-zinc-600">02 · FETCH</p>
          <p className="mt-2.5 text-[13px] text-muted-foreground">抓取正文</p>
          <p className="mt-1 font-mono text-[34px] font-bold leading-none text-primary">
            {stats.fetch.succeeded} <small className="text-[15px] font-semibold text-muted-foreground">成功</small>
          </p>
          <p className="mt-1.5 text-[11px] text-zinc-500">{stats.fetch.skipped} 条判重跳过</p>
        </div>
        <div className="flex items-center justify-center font-mono text-lg text-primary opacity-70">→</div>
        <div className="rounded-2xl border border-solid border-border bg-white/[.04] px-5 py-4">
          <p className="font-mono text-[10.5px] tracking-[2px] text-zinc-600">03 · INDEX</p>
          <p className="mt-2.5 text-[13px] text-muted-foreground">打标 + 向量化</p>
          <p className="mt-1 font-mono text-[34px] font-bold leading-none text-primary">{stats.fetch.succeeded}</p>
          <p className="mt-1.5 text-[11px] text-zinc-500">已入 Milvus 索引</p>
        </div>
        <div className="flex items-center justify-center font-mono text-lg text-amber-400 opacity-70">→</div>
        <div className="rounded-2xl border border-solid border-amber-400/35 bg-amber-400/[.04] px-5 py-4">
          <p className="font-mono text-[10.5px] tracking-[2px] text-zinc-600">04 · RETRY</p>
          <p className="mt-2.5 text-[13px] text-muted-foreground">补偿队列</p>
          <p className="mt-1 font-mono text-[34px] font-bold leading-none text-amber-400">{retryCount}</p>
          <p className="mt-1.5 text-[11px] text-zinc-500">次日自动重试</p>
        </div>
      </div>

      {/* 趋势为主、构成为辅 */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_380px]">
        <div className="rounded-xl border border-solid border-border bg-white/[.04] p-5">
          <div className="mb-3 flex items-baseline">
            <h2 className="text-sm font-semibold text-foreground">每日入库文章</h2>
            <span className="ml-auto text-[11px] text-zinc-400">
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
                  tick={{ fill: "#a1a1aa", fontFamily: "var(--font-geist-mono)" }}
                />
                <YAxis
                  allowDecimals={false}
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  width={28}
                  tick={{ fill: "#a1a1aa", fontFamily: "var(--font-geist-mono)" }}
                />
                <Tooltip
                  cursor={{ fill: "rgba(255,255,255,.04)" }}
                  contentStyle={TOOLTIP_STYLE}
                  itemStyle={TOOLTIP_ITEM}
                  labelStyle={TOOLTIP_LABEL}
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
            <h2 className="text-sm font-semibold text-foreground">内容构成</h2>
            <span className="ml-auto text-[11px] text-zinc-400">
              近 14 天 · {tagged} 篇
            </span>
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
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    itemStyle={TOOLTIP_ITEM}
                    labelStyle={TOOLTIP_LABEL}
                    formatter={(v, name) => [`${v} 篇`, name]}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
            {stats.by_category.slice(0, 6).map((c, i) => (
              <span key={c.tag} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  className="inline-block size-2 rounded-sm"
                  style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                />
                {c.tag}
                <b className="ml-auto font-mono font-semibold text-zinc-300">{c.count}</b>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* 数据源明细：数字 6 → 6 行事实；点击行跳新闻列表按来源筛选 */}
      {stats.by_feed.length > 0 && (
        <div className="rounded-xl border border-solid border-border bg-white/[.04] px-3 py-2">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-solid border-border text-left font-mono text-[10.5px] tracking-wider text-zinc-500">
                <th className="px-3 py-2 font-medium">数据源</th>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-3 py-2 font-medium">最后抓取</th>
                <th className="px-3 py-2 text-right font-medium">本批入库</th>
                <th className="px-3 py-2 text-right font-medium">累计文章</th>
              </tr>
            </thead>
            <tbody>
              {stats.by_feed.map((f) => (
                <tr
                  key={f.id}
                  onClick={() =>
                    f.sample_source && router.push(`/news?source=${encodeURIComponent(f.sample_source)}`)
                  }
                  className={`border-b border-solid border-white/[.04] text-zinc-400 last:border-0 ${
                    f.sample_source ? "cursor-pointer hover:bg-white/[.03]" : ""
                  }`}
                >
                  <td className="px-3 py-2 text-zinc-200">{f.name}</td>
                  <td className={`px-3 py-2 ${f.enabled ? "text-emerald-400" : "text-zinc-500"}`}>
                    {f.enabled ? "● 启用" : "○ 停用"}
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px]">{f.last_fetched_at ?? "-"}</td>
                  <td className="px-3 py-2 text-right font-mono">{f.today}</td>
                  <td className="px-3 py-2 text-right font-mono">{f.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-3 pb-1 pt-1.5 text-[10.5px] text-zinc-600">
            点击数据源行可跳转新闻列表（按来源筛选）
          </p>
        </div>
      )}
    </div>
  );
}
