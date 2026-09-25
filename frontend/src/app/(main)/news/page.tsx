"use client";

import { Search } from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import Spinner from "@/components/Spinner";
import { api } from "@/lib/api";

// ── 类型（v3 接口专属，不做兼容）──
type Article = {
  id: number;
  title: string;
  source: string;
  publish_time: string;
  summary: string;
  tags: string[];
  category: string | null;
  aux_categories: string[];
  url: string;
  content_quality: string | null;
  fail_reason: string | null;
};

type ListResp = {
  total: number;
  page: number;
  page_size: number;
  items: Article[];
};

type ArticleDetail = Article & { content: string };

// ── 封闭类目表（与 backend categories.py 对齐，18 类）──
const CATEGORIES = [
  "时政国内", "国际", "财经", "科技", "体育", "娱乐", "社会", "军事",
  "法治", "教育", "文化", "健康", "汽车", "就业社保", "农业农村",
  "消费", "气象灾害", "other",
] as const;

/* 类目 chip 色（稳定映射，无需配置） */
const CAT_TONES: Record<string, string> = {
  时政国内: "border-red-400/30 bg-red-400/[.06] text-red-400",
  国际: "border-blue-400/30 bg-blue-400/[.06] text-blue-400",
  财经: "border-amber-400/30 bg-amber-400/[.06] text-amber-400",
  科技: "border-cyan-400/30 bg-cyan-400/[.06] text-cyan-400",
  体育: "border-emerald-400/30 bg-emerald-400/[.06] text-emerald-400",
  娱乐: "border-fuchsia-400/30 bg-fuchsia-400/[.06] text-fuchsia-400",
  社会: "border-orange-400/30 bg-orange-400/[.06] text-orange-400",
  军事: "border-red-500/30 bg-red-500/[.06] text-red-500",
  法治: "border-violet-400/30 bg-violet-400/[.06] text-violet-400",
  教育: "border-sky-400/30 bg-sky-400/[.06] text-sky-400",
  文化: "border-teal-400/30 bg-teal-400/[.06] text-teal-400",
  健康: "border-lime-400/30 bg-lime-400/[.06] text-lime-400",
  汽车: "border-indigo-400/30 bg-indigo-400/[.06] text-indigo-400",
  就业社保: "border-pink-400/30 bg-pink-400/[.06] text-pink-400",
  农业农村: "border-green-400/30 bg-green-400/[.06] text-green-400",
  消费: "border-yellow-400/30 bg-yellow-400/[.06] text-yellow-400",
  气象灾害: "border-blue-500/30 bg-blue-500/[.06] text-blue-500",
  other: "border-zinc-400/30 bg-zinc-400/[.06] text-zinc-400",
};
const catTone = (c: string) => CAT_TONES[c] ?? CAT_TONES.other;

export default function NewsListPage() {
  return (
    <Suspense fallback={null}>
      <NewsListInner />
    </Suspense>
  );
}

function NewsListInner() {
  const searchParams = useSearchParams();
  const [data, setData] = useState<ListResp | null>(null);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [catOpen, setCatOpen] = useState(false);
  const [query, setQuery] = useState(() => ({
    page: 1,
    kw: "",
    category: searchParams.get("category") ?? "",
    source: searchParams.get("source") ?? "",
    failed: searchParams.get("failed") === "1",
    seq: 0,
  }));
  const seqRef = useRef(0);
  const listRef = useRef<HTMLDivElement>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailCache = useRef(new Map<number, ArticleDetail>());
  const detailSeq = useRef(0);

  useEffect(() => {
    listRef.current?.scrollTo({ top: 0 });
    const timer = setTimeout(() => {
      const seq = ++seqRef.current;
      setLoading(true);
      setError("");
      const params = new URLSearchParams({
        page: String(query.page),
        page_size: "15",
        quality: query.failed ? "bad" : "ok",
      });
      if (query.kw.trim()) params.set("keyword", query.kw.trim());
      if (query.category) params.set("category", query.category);
      if (query.source) params.set("source", query.source);
      api<ListResp>(`/news/v3/articles?${params}`)
        .then((d) => {
          if (seq === seqRef.current) {
            setData(d);
            setSelectedId((prev) =>
              d.items.some((i) => i.id === prev) ? prev : (d.items[0]?.id ?? null),
            );
          }
        })
        .catch((e) => {
          if (seq === seqRef.current) setError(e instanceof Error ? e.message : "加载失败");
        })
        .finally(() => {
          if (seq === seqRef.current) setLoading(false);
        });
    }, 0);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    if (detailCache.current.has(selectedId)) {
      setDetail(detailCache.current.get(selectedId)!);
      setDetailLoading(false);
      return;
    }
    setDetail(null);
    setDetailLoading(true);
    const timer = setTimeout(() => {
      const seq = ++detailSeq.current;
      api<ArticleDetail>(`/news/v3/articles/${selectedId}`)
        .then((d) => {
          if (seq !== detailSeq.current) return;
          detailCache.current.set(selectedId, d);
          setDetail(d);
        })
        .catch(() => {})
        .finally(() => {
          if (seq === detailSeq.current) setDetailLoading(false);
        });
    }, 0);
    return () => clearTimeout(timer);
  }, [selectedId]);

  const { page, category, failed: showFailed } = query;
  const setQueryPart = (part: Partial<typeof query>) =>
    setQuery((q) => ({ ...q, page: 1, ...part, seq: q.seq + 1 }));

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const search = () => setQueryPart({ kw: keyword });

  const groups = useMemo(() => {
    if (!data) return [];
    const key = (d: Date) =>
      `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const now = new Date();
    const todayKey = key(now);
    const y = new Date(now);
    y.setDate(y.getDate() - 1);
    const yKey = key(y);
    const map = new Map<string, Article[]>();
    for (const a of data.items) {
      const k = a.publish_time.slice(5, 10);
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(a);
    }
    return [...map.entries()].map(([k, items]) => ({
      label: k === todayKey ? `今天 · ${k}` : k === yKey ? `昨天 · ${k}` : k,
      items,
    }));
  }, [data]);

  const selected = data?.items.find((i) => i.id === selectedId) ?? null;

  return (
    <div className="flex h-[calc(100dvh-108px)] flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-2xl font-bold tracking-wide text-foreground">新闻列表</h1>
        <span className="text-[13px] text-muted-foreground">
          共 <b className="font-mono font-semibold text-primary">{data?.total ?? "—"}</b> 条 · 每页 15 条
        </span>
      </div>

      {/* 工具行：搜索 + 类目下拉 + 质检拦截 | 分页（右） */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative w-64">
          <Search className="absolute top-2.5 left-3 size-4 text-zinc-600" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            placeholder="搜索标题 / 正文关键词"
            className="h-9.5 w-full rounded-lg border border-solid border-input bg-black/35 pr-14 pl-9 text-[13px] text-foreground outline-none transition-colors placeholder:text-zinc-600 focus:border-primary focus:ring-[3px] focus:ring-primary/15"
          />
        </div>
        <button
          type="button"
          onClick={search}
          className="h-9.5 rounded-lg border border-solid border-primary/30 bg-primary/[.12] px-5 text-[13px] font-semibold tracking-[0.2em] text-primary transition-colors hover:bg-primary/20"
        >
          搜索
        </button>

        {/* 类目下拉（封闭 18 类，替代旧标签搜索） */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setCatOpen(!catOpen)}
            className={`flex h-9.5 items-center gap-2 rounded-lg border border-solid px-3 text-[13px] transition-colors ${
              category
                ? `${catTone(category)} border-current/40`
                : "border-input bg-black/35 text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {category || "按类目筛选"}
            <span className="text-[10px] opacity-60">{catOpen ? "▲" : "▼"}</span>
          </button>
          {category && !catOpen && (
            <button
              type="button"
              onClick={() => setQueryPart({ category: "" })}
              className="absolute top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
              style={{ insetInlineEnd: 8 }}
            >
              ✕
            </button>
          )}
          {catOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setCatOpen(false)} />
              <div className="absolute z-20 mt-1 grid max-h-64 w-64 grid-cols-2 gap-0.5 overflow-y-auto rounded-lg border border-solid border-border bg-popover p-1.5 shadow-2xl">
                <button
                  type="button"
                  onClick={() => { setQueryPart({ category: "" }); setCatOpen(false); }}
                  className="col-span-2 rounded px-2 py-1.5 text-left text-[12px] text-zinc-500 hover:bg-white/[.05]"
                >
                  全部类目
                </button>
                {CATEGORIES.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => { setQueryPart({ category: c }); setCatOpen(false); }}
                    className={`rounded px-2 py-1.5 text-left text-[12px] transition-colors ${
                      c === category
                        ? catTone(c)
                        : "text-zinc-400 hover:bg-white/[.05]"
                    }`}
                  >
                    {c === "other" ? "其他" : c}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <label className="ml-1 flex cursor-pointer items-center gap-2 text-[13px] text-muted-foreground">
          <input
            type="checkbox"
            checked={showFailed}
            onChange={(e) => setQueryPart({ failed: e.target.checked })}
            className="size-4 accent-primary"
          />
          查看质检不通过的新闻
        </label>

        {data && data.total > data.page_size && (
          <div className="ml-auto flex items-center gap-2.5 font-mono text-[11px] text-zinc-400">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setQuery((q) => ({ ...q, page: q.page - 1, seq: q.seq + 1 }))}
              className="rounded-lg border border-solid border-border bg-white/[.03] px-3 py-1.5 text-[12px] transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-35"
            >
              ← 上一页
            </button>
            <span>
              第 <b className="font-bold text-primary">{page}</b> / {totalPages} 页
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setQuery((q) => ({ ...q, page: q.page + 1, seq: q.seq + 1 }))}
              className="rounded-lg border border-solid border-border bg-white/[.03] px-3 py-1.5 text-[12px] transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-35"
            >
              下一页 →
            </button>
          </div>
        )}
      </div>

      {/* 主从双栏：左标题流 / 右阅读面板 */}
      <div className="grid min-h-0 flex-1 grid-cols-[420px_1fr] gap-3">
        <div className="relative flex min-h-0 flex-col overflow-hidden rounded-xl border border-solid border-border bg-white/[.04]">
          {loading && data && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-black/50 backdrop-blur-[2px]">
              <Spinner label="正在更新" />
            </div>
          )}
          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
            {loading && !data && (
              <div className="flex h-full items-center justify-center">
                <Spinner />
              </div>
            )}
            {error && <p className="p-4 text-sm text-red-400">{error}</p>}
            {!loading && data && data.items.length === 0 && (
              <p className="py-16 text-center text-sm text-muted-foreground">
                {showFailed ? "没有质检不通过的新闻" : "没有匹配的新闻"}
              </p>
            )}
            {groups.map((g, gi) => (
              <div key={g.label}>
                <div className="flex items-center gap-2.5 px-2 pt-3 pb-2 font-mono text-[10.5px] tracking-wider text-primary/80">
                  {g.label}
                  <span className="h-px flex-1 bg-white/[.07]" />
                </div>
                {g.items.map((a) => {
                  const featured = gi === 0 && g.items[0].id === a.id && !showFailed;
                  const active = selectedId === a.id;
                  return (
                    <div
                      key={a.id}
                      onClick={() => setSelectedId(a.id)}
                      className={`mb-0.5 cursor-pointer rounded-lg px-3 py-2.5 ${
                        active
                          ? "border border-solid border-primary/20 bg-primary/[.06] shadow-[inset_2px_0_0_var(--neon)]"
                          : featured
                            ? "border border-solid border-border bg-white/[.04]"
                            : "border border-solid border-transparent"
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        {a.category && (
                          <span
                            className={`mt-0.5 shrink-0 rounded-full border border-solid px-1.5 py-0 text-[9.5px] leading-4 ${catTone(a.category)}`}
                          >
                            {a.category === "other" ? "其他" : a.category}
                          </span>
                        )}
                        <p
                          className={`line-clamp-2 leading-snug ${
                            featured
                              ? "text-sm font-semibold text-zinc-100"
                              : "text-[13.5px] text-zinc-200"
                          }`}
                        >
                          {a.title}
                        </p>
                      </div>
                      {featured && a.summary && (
                        <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                          {a.summary}
                        </p>
                      )}
                      {showFailed && a.fail_reason && (
                        <p className="mt-1.5 rounded bg-destructive/10 px-2 py-1 text-[11px] text-red-300">
                          {a.content_quality === "bad" ? "语义/规则质检不通过" : "抓取/判重未通过"}
                          ：{a.fail_reason}
                        </p>
                      )}
                      <div className="mt-1.5 flex items-center gap-2 text-[10.5px] text-zinc-500">
                        <span>{a.source}</span>
                        <span className="font-mono">{a.publish_time.slice(5, 11)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        {/* 右：阅读面板 */}
        <div className="relative flex min-h-0 flex-col overflow-hidden rounded-xl border border-solid border-border bg-white/[.04]">
          {selected ? (
            <>
              <div className="flex items-center justify-between px-6 pt-4">
                <span className="font-mono text-[11px] tracking-[2px] text-primary/70">
                  READER://PREVIEW
                </span>
                <span className="font-mono text-[11px] text-zinc-600">{selected.publish_time}</span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
                <span className="font-mono text-[11px] tracking-wider text-primary">
                  {selected.source}
                </span>
                <h2 className="mt-2 text-[22px] font-bold leading-snug text-foreground">
                  {selected.title}
                </h2>
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {selected.category && (
                    <span className={`rounded-full border border-solid px-2.5 py-0.5 text-[10.5px] font-medium ${catTone(selected.category)}`}>
                      {selected.category === "other" ? "其他" : selected.category}
                    </span>
                  )}
                  {selected.aux_categories.map((c) => (
                    <span key={c} className={`rounded-full border border-solid px-2.5 py-0.5 text-[10.5px] opacity-60 ${catTone(c)}`}>
                      {c}
                    </span>
                  ))}
                </div>
                {showFailed && selected.fail_reason && (
                  <p className="mt-3 rounded-lg border border-solid border-destructive/30 bg-destructive/[.06] px-3 py-2 text-xs text-red-300">
                    {selected.content_quality === "bad" ? "语义/规则质检不通过" : "抓取/判重未通过"}
                    ：{selected.fail_reason}
                  </p>
                )}
                {detailLoading ? (
                  <div className="flex h-40 items-center justify-center">
                    <Spinner label="加载全文" />
                  </div>
                ) : detail ? (
                  <div className="mt-4 whitespace-pre-wrap text-[14.5px] leading-loose text-zinc-300">
                    {detail.content}
                  </div>
                ) : (
                  selected.summary && (
                    <div className="mt-4 text-[14.5px] leading-loose text-zinc-300">
                      {selected.summary}
                    </div>
                  )
                )}
              </div>
              <div className="border-t border-solid border-border px-6 py-3.5">
                <a
                  href={selected.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block h-11 w-full rounded-lg bg-gradient-to-r from-primary to-[#67e8f9] text-center text-sm font-bold leading-[44px] tracking-[2px] text-[#001318] shadow-[0_0_20px_rgba(34,211,238,.3)] transition-shadow hover:shadow-[0_0_30px_rgba(34,211,238,.45)]"
                >
                  阅读原文 ↗
                </a>
              </div>
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              ← 从左侧选择新闻查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
