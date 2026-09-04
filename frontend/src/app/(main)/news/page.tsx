"use client";

import { useCallback, useEffect, useState } from "react";

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
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [tag, setTag] = useState("");
  const [showFailed, setShowFailed] = useState(false); // 勾选：查看质检不通过的新闻
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (p: number, kw: string, t: string, failed: boolean) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(p),
        page_size: "15",
        quality: failed ? "bad" : "ok",
      });
      if (kw.trim()) params.set("keyword", kw.trim());
      if (t) params.set("tag", t);
      setData(await api<ListResp>(`/news/articles?${params}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(page, keyword, tag, showFailed);
  }, [load, page, tag, showFailed]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const search = () => {
    setPage(1);
    void load(1, keyword, tag, showFailed);
  };

  return (
    <div className="space-y-4">
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
            onChange={(e) => {
              setShowFailed(e.target.checked);
              setPage(1);
            }}
            className="h-4 w-4 accent-foreground"
          />
          查看质检不通过的新闻
        </label>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => {
              setTag("");
              setPage(1);
            }}
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
              onClick={() => {
                setTag(t);
                setPage(1);
              }}
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

      {/* 列表 */}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {loading && <p className="text-sm text-zinc-400">加载中…</p>}
      {!loading && data && data.items.length === 0 && (
        <p className="py-16 text-center text-sm text-zinc-400">
          {showFailed ? "没有质检不通过的新闻" : "没有匹配的新闻"}
        </p>
      )}
      <div className="space-y-3">
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

      {/* 分页 */}
      {data && data.total > data.page_size && (
        <div className="flex items-center justify-center gap-3 pt-2 text-sm">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
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
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-solid border-black/[.1] px-3 py-1.5 disabled:opacity-40 dark:border-white/[.2]"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
