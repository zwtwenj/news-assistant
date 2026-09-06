"use client";

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

const TAGS = ["社会", "国际", "财经", "娱乐", "体育", "科技", "健康", "军事", "教育", "其他"];

export default function NewsListPage() {
  const [data, setData] = useState<ListResp | null>(null);
  const [keyword, setKeyword] = useState(""); // 输入草稿，回车/点搜索才提交到查询
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 查询态：仅在用户动作（搜索/切标签/翻页/切拦截区）时整体变更，effect 只依赖它 → 每动作恰好一次请求
  const [query, setQuery] = useState({ page: 1, kw: "", tag: "", failed: false, seq: 0 });
  const seqRef = useRef(0); // 响应序号：仅接受最新一次（丢弃过期响应）
  const listRef = useRef<HTMLDivElement>(null); // 列表滚动容器（翻页回顶）

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
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-black dark:text-zinc-50">新闻列表</h1>
        <span className="text-sm text-zinc-400">{data ? `共 ${data.total} 条` : ""}</span>
      </div>

      {/* 搜索栏 */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="搜索标题 / 正文关键词，回车搜索"
          className="w-72 rounded-md border border-solid border-black/[.1] bg-white px-3 py-2 text-sm text-black outline-none focus:border-black dark:border-white/[.2] dark:bg-black dark:text-zinc-50 dark:focus:border-zinc-50"
        />
        <button
          type="button"
          onClick={search}
          className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
        >
          搜索
        </button>
        <label className="ml-2 flex cursor-pointer items-center gap-1.5 text-sm text-zinc-600 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={showFailed}
            onChange={(e) => setQueryPart({ failed: e.target.checked })}
            className="h-4 w-4 accent-foreground"
          />
          查看质检不通过的新闻
        </label>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setQueryPart({ tag: "" })}
            className={
              !tag
                ? "rounded-full bg-foreground px-3 py-1 text-xs text-background"
                : "rounded-full border border-solid border-black/[.1] px-3 py-1 text-xs text-zinc-600 dark:border-white/[.2] dark:text-zinc-400"
            }
          >
            全部
          </button>
          {TAGS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setQueryPart({ tag: t })}
              className={
                tag === t
                  ? "rounded-full bg-foreground px-3 py-1 text-xs text-background"
                  : "rounded-full border border-solid border-black/[.1] px-3 py-1 text-xs text-zinc-600 hover:border-black dark:border-white/[.2] dark:text-zinc-400 dark:hover:border-zinc-50"
              }
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* 列表（滚动在列表内部，翻页/筛选后回到顶部；loading 覆盖不顶开） */}
      <div className="relative min-h-0 flex-1">
        {loading && data && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-zinc-50/60 backdrop-blur-[1px] dark:bg-black/60">
            <Spinner label="正在更新…" />
          </div>
        )}
        {loading && !data && (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && data && data.items.length === 0 && (
          <p className="py-16 text-center text-sm text-zinc-400">
            {showFailed ? "没有质检不通过的新闻" : "没有匹配的新闻"}
          </p>
        )}
        <div ref={listRef} className="h-full space-y-3 overflow-y-auto pr-1">
        {data?.items.map((a) => (
          <a
            key={a.id}
            href={a.url}
            target="_blank"
            rel="noopener noreferrer"
            className={
              showFailed
                ? "block rounded-lg border border-solid border-red-200 bg-white p-4 dark:border-red-900/50 dark:bg-black"
                : "block rounded-lg border border-solid border-black/[.06] bg-white p-4 transition-colors hover:border-black/[.2] dark:border-white/[.12] dark:bg-black dark:hover:border-white/[.3]"
            }
          >
            <div className="flex items-start justify-between gap-4">
              <h2 className="font-medium text-black dark:text-zinc-50">{a.title}</h2>
              <span className="shrink-0 text-xs text-zinc-400">{a.publish_time}</span>
            </div>
            {showFailed && (
              <p className="mt-1.5 rounded bg-red-50 px-2 py-1 text-xs text-red-600 dark:bg-red-950/40 dark:text-red-400">
                {a.content_quality === "bad" ? "语义/规则质检不通过" : "抓取/判重未通过"}
                {a.fail_reason ? `：${a.fail_reason}` : ""}
              </p>
            )}
            <p className="mt-1 line-clamp-2 text-sm text-zinc-500 dark:text-zinc-400">{a.summary}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-xs text-zinc-400">{a.source}</span>
              {a.tags.map((t) => (
                <span
                  key={t}
                  className="rounded-full bg-black/[.05] px-2 py-0.5 text-xs text-zinc-600 dark:bg-white/[.1] dark:text-zinc-300"
                >
                  {t}
                </span>
              ))}
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
            className="rounded-md border border-solid border-black/[.1] px-3 py-1.5 disabled:opacity-40 dark:border-white/[.2]"
          >
            上一页
          </button>
          <span className="text-zinc-500">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setQuery((q) => ({ ...q, page: q.page + 1, seq: q.seq + 1 }))}
            className="rounded-md border border-solid border-black/[.1] px-3 py-1.5 disabled:opacity-40 dark:border-white/[.2]"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
