"use client";

/*
 * RSS 分发卡片（我的播客页顶部）：
 * - 首次进入自动开通默认配置（频道名/简介可改）
 * - feed URL 一键复制，拿去网易云/小宇宙等平台提交收录
 */

import { Check, Copy, Rss } from "lucide-react";
import { useEffect, useState } from "react";

import Spinner from "@/components/Spinner";
import { ApiError, api } from "@/lib/api";

type RssFeedInfo = {
  feed_url: string;
  channel_title: string;
  channel_description: string;
  published_count: number;
};

export default function RssFeedCard() {
  const [info, setInfo] = useState<RssFeedInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    api<RssFeedInfo>("/rss/me")
      .then((d) => {
        if (!alive) return;
        setInfo(d);
        setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof ApiError ? e.message : "RSS 信息加载失败");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const copy = async () => {
    if (!info) return;
    try {
      await navigator.clipboard.writeText(info.feed_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      window.prompt("复制以下链接：", info.feed_url);
    }
  };

  const save = async () => {
    if (!title.trim() || !desc.trim() || saving) return;
    setSaving(true);
    try {
      setInfo(
        await api<RssFeedInfo>("/rss/me", {
          method: "PUT",
          body: JSON.stringify({ channel_title: title.trim(), channel_description: desc.trim() }),
        })
      );
      setEditing(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-solid border-black/[.06] bg-white p-4 text-sm text-zinc-400 dark:border-white/[.12] dark:bg-black">
        <Spinner /> 正在加载 RSS 信息…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border border-solid border-amber-200 bg-amber-50 p-4 text-sm text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-400">
        {error}
      </div>
    );
  }
  if (!info) return null;

  return (
    <div className="rounded-lg border border-solid border-black/[.06] bg-white p-4 dark:border-white/[.12] dark:bg-black">
      <div className="flex items-center gap-2">
        <Rss className="size-4 text-orange-500" />
        <span className="text-sm font-medium text-black dark:text-zinc-50">RSS 分发</span>
        <span className="text-xs text-zinc-400">
          已发布 {info.published_count} 期 · 各平台同步周期为数小时至一天
        </span>
      </div>

      {!editing ? (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-zinc-500">
            频道：{info.channel_title} —— {info.channel_description}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="max-w-full truncate rounded bg-zinc-100 px-2 py-1 font-mono text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              {info.feed_url}
            </code>
            <button
              type="button"
              onClick={() => void copy()}
              className="flex items-center gap-1 rounded-md border border-solid border-black/[.08] px-2 py-1 text-xs text-zinc-600 hover:border-black/30 dark:border-white/[.145] dark:text-zinc-400 dark:hover:border-white/40"
            >
              {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
              {copied ? "已复制" : "复制地址"}
            </button>
            <button
              type="button"
              onClick={() => {
                setTitle(info.channel_title);
                setDesc(info.channel_description);
                setEditing(true);
              }}
              className="text-xs text-zinc-500 hover:text-black dark:hover:text-zinc-300"
            >
              编辑频道信息
            </button>
          </div>
          <p className="text-xs text-zinc-400">
            将此地址提交到网易云音乐、小宇宙等平台（平台 → 播客创作后台 → RSS 导入），即可在各平台同步你的播客。
            发布/撤下单集请使用下方列表中的操作。
          </p>
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            placeholder="频道名称"
            className="w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-1.5 text-sm outline-none focus:border-black dark:border-white/[.2] dark:focus:border-zinc-50"
          />
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            rows={2}
            maxLength={2000}
            placeholder="频道简介"
            className="w-full resize-none rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-1.5 text-sm outline-none focus:border-black dark:border-white/[.2] dark:focus:border-zinc-50"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => void save()}
              className="rounded-md bg-foreground px-3 py-1 text-xs font-medium text-background disabled:opacity-40"
            >
              保存
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-solid border-black/[.08] px-3 py-1 text-xs dark:border-white/[.145]"
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
