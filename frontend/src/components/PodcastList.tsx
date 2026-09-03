"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

export type Podcast = {
  id: number;
  mode: string;
  status: string;
  topic_prompt: string;
  error: string | null;
  audio_url: string | null;
  duration_sec: number | null;
  created_at: string;
};

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中",
  scripting: "撰写脚本…",
  synthesizing: "语音合成…",
  composing: "音频拼接…",
  succeeded: "已完成",
  failed: "失败",
};

export default function PodcastList() {
  const [list, setList] = useState<Podcast[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await api<{ items: Podcast[] }>("/podcasts?page_size=50");
      setList(data.items);
    } catch {
      /* 忽略轮询失败 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 存在进行中的任务时 5s 轮询（点击生成即入库，失败项也留在列表）
  const hasRunning = list.some((p) =>
    ["pending", "scripting", "synthesizing", "composing"].includes(p.status)
  );
  useEffect(() => {
    if (!hasRunning) return;
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [hasRunning, load]);

  const remove = async (id: number) => {
    await api(`/podcasts/${id}`, { method: "DELETE" });
    await load();
  };

  if (loading) return <p className="text-sm text-zinc-400">加载中…</p>;
  if (list.length === 0)
    return <p className="py-10 text-center text-sm text-zinc-400">还没有生成过播客，去「播客生成」创建第一期</p>;

  return (
    <div className="space-y-3">
      {list.map((p) => (
        <div
          key={p.id}
          className="rounded-lg border border-solid border-black/[.06] bg-white p-4 dark:border-white/[.12] dark:bg-black"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="truncate font-medium text-black dark:text-zinc-50">{p.topic_prompt}</p>
              <p className="mt-1 text-xs text-zinc-400">
                #{p.id} · {p.mode === "dual" ? "双人对谈" : "单人独白"} · 创建于 {p.created_at}
                {p.duration_sec ? ` · ${p.duration_sec}s` : ""}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span
                className={
                  p.status === "succeeded"
                    ? "text-sm text-green-600"
                    : p.status === "failed"
                      ? "text-sm text-red-600"
                      : "animate-pulse text-sm text-blue-600"
                }
              >
                {STATUS_TEXT[p.status] ?? p.status}
              </span>
              <button
                type="button"
                onClick={() => void remove(p.id)}
                className="text-xs text-zinc-400 hover:text-red-600"
              >
                删除
              </button>
            </div>
          </div>
          {p.status === "failed" && p.error && (
            <p className="mt-2 text-sm text-red-500">{p.error}</p>
          )}
          {p.status === "succeeded" && p.audio_url && (
            <audio controls preload="none" src={p.audio_url} className="mt-3 w-full" />
          )}
        </div>
      ))}
    </div>
  );
}
