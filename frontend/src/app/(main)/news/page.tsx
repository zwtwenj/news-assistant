"use client";

import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import Spinner from "@/components/Spinner";
import { api } from "@/lib/api";

type Article = {
  id: number;
  title: string;
  source: string;
  publish_time: string;
  summary: string;
  tags: string[];
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

type TagItem = { tag: string; count: number };

/* 标签 chips 按名称哈希取霓虹色，稳定且无需配置 */
const CHIP_TONES = [
  "border-primary/25 bg-primary/[.06] text-primary",
  "border-[#a78bfa]/30 bg-[#a78bfa]/[.07] text-[#a78bfa]",
  "border-emerald-400/30 bg-emerald-400/[.06] text-emerald-400",
  "border-amber-400/30 bg-amber-400/[.06] text-amber-400",
];
const chipTone = (tag: string) => {
  let h = 0;
  for (const ch of tag) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return CHIP_TONES[h % CHIP_TONES.length];
};

export default function NewsListPage() {
  const [data, setData] = useState<ListResp | null>(null);
  const [keyword, setKeyword] = useState(""); // 输入草稿，回车/点搜索才提交到查询
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 标签可搜索下拉：候选列表 + 输入过滤 + 开合状态
  const [tagItems, setTagItems] = useState<TagItem[]>([]);
  const [tagInput, setTagInput] = useState(""); // 下拉框输入草稿（过滤用）
  const [tagOpen, setTagOpen] = useState(false);
  // 查询态：仅在用户动作（搜索/切标签/翻页/切拦截区）时整体变更，effect 只依赖它 → 每动作恰好一次请求
  const [query, setQuery] = useState({ page: 1, kw: "", tag: "", failed: false, seq: 0 });
  const seqRef = useRef(0); // 响应序号：仅接受最新一次（丢弃过期响应）
  const listRef = useRef<HTMLDivElement>(null); // 列表滚动容器（翻页回顶）

  useEffect(() => {
    // 标签候选（使用中标签+计数）：一次拉取
    const t = setTimeout(() => {
      api<{ items: TagItem[] }>("/news/tags?limit=200")
        .then((d) => setTagItems(d.items))
        .catch(() => {});
    }, 0);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    // 翻页/筛选切换后列表回顶（滚动在列表内部）
    listRef.current?.scrollTo({ top: 0 });
    // 定时器 + 清理：StrictMode 双调用时第一个被清掉，挂载也只发一次请求
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
      if (query.tag) params.set("tag", query.tag);
      api<ListResp>(`/news/articles?${params}`)
        .then((d) => {
          if (seq === seqRef.current) setData(d);
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

  const { page, tag, failed: showFailed } = query;
  const setQueryPart = (part: Partial<typeof query>) =>
    setQuery((q) => ({ ...q, page: 1, ...part, seq: q.seq + 1 }));

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const search = () => setQueryPart({ kw: keyword });

  return (
    <div className="flex h-[calc(100dvh-108px)] flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-2xl font-bold tracking-wide text-foreground">新闻列表</h1>
        <span className="text-[13px] text-muted-foreground">
          共 <b className="font-mono font-semibold text-primary">{data?.total ?? "—"}</b> 条 · 每页 15 条
        </span>
      </div>

      {/* 搜索栏 */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative w-72">
          <Search className="absolute top-2.5 left-3 size-4 text-zinc-600" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            placeholder="搜索标题 / 正文关键词"
            className="h-9.5 w-full rounded-lg border border-solid border-input bg-black/35 pr-14 pl-9 text-[13px] text-foreground outline-none transition-colors placeholder:text-zinc-600 focus:border-primary focus:ring-[3px] focus:ring-primary/15"
          />
          <span className="absolute top-2 right-2.5 rounded border border-solid border-border bg-white/[.03] px-1.5 py-0.5 text-[10px] text-zinc-600">
            回车 ↵
          </span>
        </div>
        <button
          type="button"
          onClick={search}
          className="h-9.5 rounded-lg border border-solid border-primary/30 bg-primary/[.12] px-5 text-[13px] font-semibold tracking-[0.2em] text-primary transition-colors hover:bg-primary/20"
        >
          搜索
        </button>
        <label className="ml-2 flex cursor-pointer items-center gap-2 text-[13px] text-muted-foreground">
          <input
            type="checkbox"
            checked={showFailed}
            onChange={(e) => setQueryPart({ failed: e.target.checked })}
            className="size-4 accent-primary"
          />
          查看质检不通过的新闻
        </label>
        {/* 标签筛选：可搜索下拉（词表自生长，标签数量不定） */}
        <div className="relative">
          <input
            value={tagOpen ? tagInput : tag}
            onChange={(e) => {
              setTagInput(e.target.value);
              setTagOpen(true);
            }}
            onFocus={() => {
              setTagInput("");
              setTagOpen(true);
            }}
            onBlur={() => setTimeout(() => setTagOpen(false), 150)} // 等点选事件先触发
            placeholder={tag || "按标签筛选"}
            className={`h-9.5 w-44 rounded-lg border border-solid bg-black/35 px-3 text-[13px] outline-none transition-colors placeholder:text-zinc-600 focus:border-primary focus:ring-[3px] focus:ring-primary/15 ${
              tag && !tagOpen ? "border-primary/40 text-primary" : "border-input text-foreground"
            }`}
          />
          {tag && !tagOpen && (
            <button
              type="button"
              onClick={() => setQueryPart({ tag: "" })}
              className="absolute top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
              style={{ insetInlineEnd: 28 }}
              title="清除标签筛选"
            >
              ✕
            </button>
          )}
          {tagOpen && (
            <div className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-solid border-border bg-popover py-1 shadow-2xl">
              {tag && (
                <button
                  type="button"
                  onMouseDown={() => {
                    setQueryPart({ tag: "" });
                    setTagOpen(false);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-[13px] text-zinc-500 hover:bg-white/[.05]"
                >
                  全部（清除筛选）
                </button>
              )}
              {tagItems
                .filter((t) => !tagInput || t.tag.includes(tagInput))
                .map((t) => (
                  <button
                    key={t.tag}
                    type="button"
                    onMouseDown={() => {
                      setQueryPart({ tag: t.tag });
                      setTagOpen(false);
                    }}
                    className={
                      t.tag === tag
                        ? "block w-full bg-primary/10 px-3 py-1.5 text-left text-[13px] text-primary"
                        : "block w-full px-3 py-1.5 text-left text-[13px] text-zinc-400 hover:bg-white/[.05]"
                    }
                  >
                    {t.tag} <span className="font-mono text-xs text-zinc-600">({t.count})</span>
                  </button>
                ))}
              {tagItems.filter((t) => !tagInput || t.tag.includes(tagInput)).length === 0 && (
                <p className="px-3 py-2 text-[13px] text-zinc-500">无匹配标签</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 当前筛选状态行（无筛选时不占位） */}
      {(tag || query.kw || showFailed) && (
        <div className="-mt-2 flex gap-5 text-[11px] text-zinc-600">
          {tag && <span className="text-primary">筛选：标签 = {tag}</span>}
          {query.kw && <span>关键词：{query.kw}</span>}
          {showFailed && <span className="text-amber-400">质检：仅看不通过</span>}
        </div>
      )}

      {/* 列表（滚动在列表内部，翻页/筛选后回到顶部；loading 覆盖不顶开） */}
      <div className="relative min-h-0 flex-1">
        {loading && data && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60 backdrop-blur-[2px]">
            <Spinner label="正在更新…" />
          </div>
        )}
        {loading && !data && (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
        {!loading && data && data.items.length === 0 && (
          <p className="py-16 text-center text-sm text-muted-foreground">
            {showFailed ? "没有质检不通过的新闻" : "没有匹配的新闻"}
          </p>
        )}
        <div ref={listRef} className="h-full space-y-2.5 overflow-y-auto pr-1">
        {data?.items.map((a) => (
          <a
            key={a.id}
            href={a.url}
            target="_blank"
            rel="noopener noreferrer"
            className={
              showFailed
                ? "group block rounded-xl border border-solid border-destructive/30 bg-destructive/[.04] p-4 transition-colors hover:border-destructive/50"
                : "group block rounded-xl border border-solid border-border bg-white/[.04] p-4 transition-all hover:border-primary/35 hover:shadow-[0_0_20px_rgba(34,211,238,.07)]"
            }
          >
            <div className="flex items-baseline justify-between gap-4">
              <h2 className="truncate font-medium text-zinc-100">{a.title}</h2>
              <span className="shrink-0 font-mono text-[11px] text-zinc-600">{a.publish_time}</span>
            </div>
            {showFailed && (
              <p className="mt-1.5 rounded bg-destructive/10 px-2 py-1 text-xs text-red-300">
                {a.content_quality === "bad" ? "语义/规则质检不通过" : "抓取/判重未通过"}
                {a.fail_reason ? `：${a.fail_reason}` : ""}
              </p>
            )}
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">{a.summary}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-[11px] text-zinc-600">{a.source}</span>
              {a.tags.map((t) => (
                <span
                  key={t}
                  className={`rounded-full border border-solid px-2 py-0.5 text-[10.5px] ${chipTone(t)}`}
                >
                  {t}
                </span>
              ))}
              <span className="ml-auto text-[11px] text-zinc-600 opacity-0 transition-opacity group-hover:text-primary group-hover:opacity-100">
                打开原文 ↗
              </span>
            </div>
          </a>
        ))}
        </div>
      </div>

      {/* 分页（固定页面底部） */}
      {data && data.total > data.page_size && (
        <div className="flex shrink-0 items-center justify-center gap-3 text-sm">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setQuery((q) => ({ ...q, page: q.page - 1, seq: q.seq + 1 }))}
            className="rounded-lg border border-solid border-border bg-white/[.03] px-3.5 py-1.5 text-[13px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-35 disabled:hover:border-border disabled:hover:text-muted-foreground"
          >
            ← 上一页
          </button>
          <span className="text-[13px] text-muted-foreground">
            第 <b className="font-mono font-semibold text-primary">{page}</b> / {totalPages} 页
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setQuery((q) => ({ ...q, page: q.page + 1, seq: q.seq + 1 }))}
            className="rounded-lg border border-solid border-border bg-white/[.03] px-3.5 py-1.5 text-[13px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-35 disabled:hover:border-border disabled:hover:text-muted-foreground"
          >
            下一页 →
          </button>
        </div>
      )}
    </div>
  );
}
