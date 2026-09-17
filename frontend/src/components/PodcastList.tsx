"use client";

/*
 * 我的播客列表：统一三行卡片（标题行/进度或播放行/信息行）、状态进度线、
 * 分页、RSS 分发图标弹层、编辑（标题/简介/封面）、发布/撤下（风险告知）、删除确认。
 */

import { Loader, Pencil, Podcast, Rss, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AudioPlayer } from "@/components/AudioPlayer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

export type Podcast = {
  id: number;
  mode: string;
  status: string;
  topic_prompt: string;
  title: string | null;
  description: string | null;
  cover_url: string | null;
  target_minutes: number;
  error: string | null;
  audio_url: string | null;
  duration_sec: number | null;
  feed_published_at: string | null;
  created_at: string;
  tts_progress?: string;
};

type ListResp = {
  total: number;
  page: number;
  page_size: number;
  items: Podcast[];
};

type RssInfo = {
  feed_url: string;
  channel_title: string;
  published_count: number;
};

const PAGE_SIZE = 6;

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中",
  scripting: "撰写脚本",
  synthesizing: "语音合成",
  composing: "音频拼接",
  succeeded: "已完成",
  failed: "失败",
};

// 生成中状态集合（5s 轮询的触发条件）
const STATUS_STEP_KEYS = ["pending", "scripting", "synthesizing", "composing"];

// 各阶段示意进度（非精确，给用户「在动」的反馈；轮询到新状态会跳变）
const STATUS_PROGRESS: Record<string, number> = {
  pending: 8,
  scripting: 35,
  synthesizing: 65,
  composing: 88,
};

// 生成中五段进度线：排队→脚本→合成→混音→完成（状态→当前段下标）
const STATUS_STEP: Record<string, number> = {
  pending: 0,
  scripting: 1,
  synthesizing: 2,
  composing: 3,
  succeeded: 4,
};
const TOTAL_STEPS = 5;

/* 状态进度线：5 段。进行中=亮度波循环扫过（在干活的感觉）；完成=全部点亮；失败=脚本段标红 */
function Steps({ status }: { status: string }) {
  if (status === "failed") {
    return (
      <div className="flex items-center gap-1.5">
        <span className="h-1 w-7 rounded-sm bg-primary/50" />
        <span className="h-1 w-7 rounded-sm bg-destructive" />
        <span className="h-1 w-7 rounded-sm bg-white/[.08]" />
        <span className="h-1 w-7 rounded-sm bg-white/[.08]" />
        <span className="h-1 w-7 rounded-sm bg-white/[.08]" />
      </div>
    );
  }
  if (status === "succeeded") {
    return (
      <div className="flex items-center gap-1.5">
        {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
          <span key={i} className="h-1 w-7 rounded-sm bg-primary/60" />
        ))}
      </div>
    );
  }
  // 进行中：亮度波沿段循环扫过（seg-flow 定义在 globals.css）
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
        <span
          key={i}
          className="h-1 w-7 rounded-sm bg-primary"
          style={{ animation: `seg-flow 1.5s ease-in-out ${i * 0.18}s infinite` }}
        />
      ))}
    </div>
  );
}

/* 状态徽章：完成绿 / 失败红 / 进行中霓虹 + 旋转图标 */
function StatusBadge({ status }: { status: string }) {
  if (status === "succeeded")
    return (
      <Badge className="border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400">
        已完成
      </Badge>
    );
  if (status === "failed") return <Badge variant="destructive">失败</Badge>;
  return (
    <Badge className="border-transparent bg-blue-100 text-blue-700 dark:bg-blue-950/60 dark:text-blue-400">
      <Loader className="animate-spin" />
      {STATUS_TEXT[status] ?? status}
    </Badge>
  );
}

export default function PodcastList() {
  const [list, setList] = useState<Podcast[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<Podcast | null>(null); // 删除确认弹窗
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [editing, setEditing] = useState<Podcast | null>(null); // 编辑弹窗
  const [editBusy, setEditBusy] = useState(false);
  const [editCover, setEditCover] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editError, setEditError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [publishing, setPublishing] = useState<Podcast | null>(null); // 发布确认弹窗
  const [publishBusy, setPublishBusy] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false); // 风险告知勾选
  const editCoverRef = useRef<HTMLInputElement>(null);
  // RSS 分发：图标点击展开的弹层（feed 信息 + 复制）
  const [rssOpen, setRssOpen] = useState(false);
  const [rssInfo, setRssInfo] = useState<RssInfo | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async (pg: number) => {
    try {
      const data = await api<ListResp>(`/podcasts?page=${pg}&page_size=${PAGE_SIZE}`);
      setList(data.items);
      setTotal(data.total);
      setPage(data.page);
    } catch {
      /* 忽略轮询失败 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(1), 0); // StrictMode 双挂载只发一次
    return () => clearTimeout(timer);
  }, [load]);

  // RSS feed 信息（弹层用；首次访问自动开通）
  useEffect(() => {
    const timer = setTimeout(() => {
      api<RssInfo>("/rss/me")
        .then(setRssInfo)
        .catch(() => {});
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  // 存在进行中的任务时 5s 轮询（点击生成即入库，失败项也留在列表）
  const hasRunning = list.some((p) =>
    ["pending", "scripting", "synthesizing", "composing"].includes(p.status),
  );
  useEffect(() => {
    if (!hasRunning) return;
    const t = setInterval(() => void load(page), 5000);
    return () => clearInterval(t);
  }, [hasRunning, load, page]);

  const copyFeedUrl = async () => {
    if (!rssInfo) return;
    try {
      await navigator.clipboard.writeText(rssInfo.feed_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 剪贴板不可用忽略 */
    }
  };

  const confirmDelete = async () => {
    if (!deleting || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await api(`/podcasts/${deleting.id}`, { method: "DELETE" });
      setDeleting(null);
      // 当前页删空时回退一页（第 1 页除外）
      const target = list.length === 1 && page > 1 ? page - 1 : page;
      if (target !== page) setPage(target);
      await load(target);
    } finally {
      setDeleteBusy(false);
    }
  };

  const openEdit = (p: Podcast) => {
    setEditTitle(p.title ?? "");
    setEditDesc(p.description ?? "");
    setEditCover(p.cover_url);
    setEditError("");
    setEditing(p);
  };

  const uploadCover = async (file: File) => {
    setUploading(true);
    setEditError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await api<{ url: string }>("/podcasts/cover", { method: "POST", body: form });
      setEditCover(resp.url);
    } catch (e) {
      setEditError(e instanceof Error ? e.message : "封面上传失败");
    } finally {
      setUploading(false);
    }
  };

  const saveEdit = async () => {
    if (!editing || editBusy) return;
    setEditBusy(true);
    setEditError("");
    try {
      await api(`/podcasts/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: editTitle,
          description: editDesc,
          cover_url: editCover,
        }),
      });
      setEditing(null);
      await load(page);
    } catch (e) {
      setEditError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setEditBusy(false);
    }
  };

  const confirmPublish = async () => {
    if (!publishing || publishBusy) return;
    setPublishBusy(true);
    try {
      await api(`/podcasts/${publishing.id}/feed`, {
        method: "POST",
        body: JSON.stringify({ published: publishing.feed_published_at == null }),
      });
      setPublishing(null);
      await load(page);
    } finally {
      setPublishBusy(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      {/* 页头：标题 + 总数 + RSS 分发图标（点击弹层） */}
      <div className="flex flex-wrap items-center gap-3.5">
        <h1 className="text-2xl font-bold tracking-wide text-foreground">我的播客</h1>
        <span className="text-[13px] text-muted-foreground">
          共 <b className="font-mono font-semibold text-primary">{total}</b> 期 · 每页 {PAGE_SIZE} 期
        </span>
        <div className="relative ml-auto">
          <button
            type="button"
            onClick={() => setRssOpen((v) => !v)}
            className="flex items-center gap-2 rounded-lg border border-solid border-primary/35 bg-primary/[.07] px-3.5 py-2 text-[12.5px] text-primary transition-colors hover:bg-primary/[.12]"
          >
            <Rss className="size-3.5" />
            RSS 分发
            {rssInfo && rssInfo.published_count > 0 && (
              <span className="size-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,.6)]" />
            )}
          </button>
          {rssOpen && rssInfo && (
            <div className="absolute top-full right-0 z-30 mt-2 w-[460px] rounded-xl border border-solid border-primary/25 bg-[#121216] p-4 shadow-[0_18px_50px_rgba(0,0,0,.6)]">
              <div className="flex items-center gap-2">
                <Rss className="size-4 text-primary" />
                <span className="text-[13.5px] font-semibold">RSS 分发</span>
                {rssInfo.published_count > 0 && (
                  <span className="ml-auto font-mono text-[10.5px] text-emerald-400">
                    已发布 {rssInfo.published_count} 期
                  </span>
                )}
              </div>
              <div className="mt-2.5 flex items-center gap-2 rounded-lg border border-solid border-border bg-black/35 px-2.5 py-2">
                <code className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                  {rssInfo.feed_url}
                </code>
                <button
                  type="button"
                  onClick={() => void navigator.clipboard.writeText(rssInfo.feed_url)}
                  className="shrink-0 rounded border border-solid border-border bg-white/[.04] px-2 py-0.5 text-[10.5px] text-muted-foreground transition-colors hover:text-foreground"
                >
                  {copied ? "已复制" : "复制"}
                </button>
              </div>
              <p className="mt-2.5 text-[11px] leading-relaxed text-zinc-500">
                将此地址提交到小宇宙、网易云音乐等平台（平台 → 播客创作后台 → RSS 导入），即可在各平台同步你的播客。单集的发布/撤下使用列表中的操作。
              </p>
            </div>
          )}
        </div>
      </div>

      {/* 列表骨架 */}
      {loading && (
        <div className="space-y-2.5">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[100px] w-full rounded-xl" />
          ))}
        </div>
      )}

      {!loading && total === 0 && (
        <p className="py-16 text-center text-sm text-muted-foreground">
          还没有生成过播客，去「播客生成」创建第一期
        </p>
      )}

      {/* 播客卡片：统一三行结构（标题行/进度或播放行/信息行），等高 100px */}
      {!loading && list.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {list.map((p) => {
            const published = p.feed_published_at != null;
            const displayTitle = p.title || p.topic_prompt || "（无标题）";
            const running = STATUS_STEP_KEYS.includes(p.status);
            const failed = p.status === "failed";
            const coverInner = p.cover_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- 用户上传的动态图
              <img src={p.cover_url} alt="" className="size-full rounded-[10px] object-cover" />
            ) : (
              <Podcast className="size-5 text-white/90" />
            );
            return (
              <div
                key={p.id}
                className={`flex h-[100px] flex-col overflow-hidden rounded-xl border border-solid px-4 ${
                  failed
                    ? "border-destructive/35 bg-destructive/[.04]"
                    : running
                      ? "border-primary/25 bg-white/[.04]"
                      : "border-border bg-white/[.04]"
                }`}
              >
                {/* 行 1：标题 + 徽章 + 图标操作 */}
                <div className="flex min-h-0 flex-1 items-center gap-2.5">
                  <h3 className="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-zinc-100" title={displayTitle}>
                    {displayTitle}
                  </h3>
                  <StatusBadge status={p.status} />
                  {published && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-solid border-primary/30 bg-primary/[.06] px-2 py-0.5 text-[10.5px] text-primary">
                      <Rss className="size-3" /> 已发布
                    </span>
                  )}
                  <div className="flex shrink-0 items-center gap-1.5">
                    {p.status === "succeeded" && p.audio_url && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className={`size-6 ${
                          published
                            ? "text-primary hover:text-primary"
                            : "text-orange-400/90 hover:text-orange-300"
                        }`}
                        title={published ? "从 RSS 撤下" : "发布到 RSS"}
                        onClick={() => {
                          setAcknowledged(false);
                          setPublishing(p);
                        }}
                      >
                        <Rss />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="size-6 text-muted-foreground hover:text-foreground"
                      title="编辑"
                      disabled={failed}
                      onClick={() => openEdit(p)}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="size-6 text-muted-foreground hover:text-destructive"
                      title="删除"
                      onClick={() => setDeleting(p)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </div>

                {/* 行 2：进度线（进行中）或播放条（已完成） */}
                <div className="flex min-h-0 flex-1 items-center gap-3">
                  {running ? (
                    <>
                      <Steps status={p.status} />
                      <span className="ml-auto font-mono text-[10.5px] text-zinc-500">
                        {STATUS_PROGRESS[p.status]}%
                      </span>
                    </>
                  ) : p.status === "succeeded" && p.audio_url ? (
                    <>
                      <AudioPlayer src={p.audio_url} className="flex-1" />
                      <span className="shrink-0 font-mono text-[11px] text-zinc-500">
                        {p.duration_sec
                          ? `${Math.floor(p.duration_sec / 60)}:${String(p.duration_sec % 60).padStart(2, "0")}`
                          : ""}
                      </span>
                    </>
                  ) : (
                    <span className="text-[11px] text-zinc-600">
                      {p.duration_sec
                        ? `${Math.floor(p.duration_sec / 60)}分${p.duration_sec % 60}秒`
                        : `目标 ${p.target_minutes} 分钟`}
                    </span>
                  )}
                </div>

                {/* 行 3：状态文字（进行中）| 模式 · 创建时间（已完成/失败） */}
                <div className="flex min-h-0 flex-1 items-center gap-2 text-[11px] text-zinc-500">
                  {running ? (
                    <span className="running-note">
                      {p.status === "synthesizing" && p.tts_progress
                        ? `正在合成语音 ${p.tts_progress} 段…`
                        : `${STATUS_TEXT[p.status]}…`}
                      <span className="st-dots">
                        <span>.</span>
                        <span>.</span>
                        <span>.</span>
                      </span>
                    </span>
                  ) : failed && p.error ? (
                    <span className="truncate rounded bg-destructive/10 px-2 py-0.5 text-red-300">
                      {p.error}
                    </span>
                  ) : (
                    <span>{p.mode === "dual" ? "双人对谈" : "单人独白"}</span>
                  )}
                  <span className="ml-auto font-mono">{p.created_at}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 分页 */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-3 font-mono text-[11px] text-zinc-400">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => void load(page - 1)}
            className="rounded-lg border border-solid border-border bg-white/[.03] px-3.5 py-1.5 text-[12px] transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-35"
          >
            ← 上一页
          </button>
          <span>
            第 <b className="font-bold text-primary">{page}</b> / {Math.max(1, Math.ceil(total / PAGE_SIZE))} 页
          </span>
          <button
            type="button"
            disabled={page >= Math.ceil(total / PAGE_SIZE)}
            onClick={() => void load(page + 1)}
            className="rounded-lg border border-solid border-border bg-white/[.03] px-3.5 py-1.5 text-[12px] transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-35"
          >
            下一页 →
          </button>
        </div>
      )}

      {/* 编辑弹窗（标题/简介/封面）：cyber 玻璃弹窗 */}
      <Dialog open={editing != null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="max-w-lg gap-0 overflow-hidden rounded-2xl border-white/10 bg-[#121216]/95 p-0 shadow-[0_24px_60px_rgba(0,0,0,.6)] backdrop-blur-xl">
          <span className="absolute top-3.5 right-5 font-mono text-[10px] tracking-[2px] text-zinc-600">
            EDIT://META
          </span>
          <div className="px-7 pb-2 pt-7">
            <DialogHeader className="space-y-1.5 text-left">
              <DialogTitle className="text-lg font-bold tracking-wide">编辑播客信息</DialogTitle>
              <DialogDescription className="text-xs text-zinc-500">
                {editing?.feed_published_at
                  ? "该期已发布至 RSS，修改将同步至各订阅平台"
                  : "标题与简介用于 RSS 分发展示"}
              </DialogDescription>
            </DialogHeader>
            {editing?.feed_published_at && (
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-solid border-primary/25 bg-primary/[.05] px-3 py-2 text-[11.5px] text-primary">
                <Rss className="size-3.5" /> 该期已发布至 RSS，修改将同步至各订阅平台
              </div>
            )}

            <div className="mt-6 space-y-5">
              <label className="block">
                <span className="mb-2 block font-mono text-[10.5px] tracking-[1px] text-zinc-500">
                  标题 · TITLE
                </span>
                <Input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  maxLength={200}
                  placeholder={editing?.topic_prompt || ""}
                  className="h-10 rounded-lg border-white/10 bg-black/30 px-3.5 text-sm outline-none placeholder:text-zinc-600 focus-visible:ring-primary/15"
                />
              </label>

              <label className="block">
                <span className="mb-2 block font-mono text-[10.5px] tracking-[1px] text-zinc-500">
                  简介 · DESCRIPTION
                </span>
                <Textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  rows={3}
                  maxLength={2000}
                  className="min-h-20 resize-none rounded-lg border-white/10 bg-black/30 p-3 text-sm leading-relaxed outline-none placeholder:text-zinc-600 focus-visible:ring-primary/15"
                />
              </label>

              <div>
                <span className="mb-2 block font-mono text-[10.5px] tracking-[1px] text-zinc-500">
                  封面 · COVER
                </span>
                <div className="flex items-center gap-4">
                  <div className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-dashed border-white/15 bg-black/30">
                    {editCover ? (
                      // eslint-disable-next-line @next/next/no-img-element -- 用户上传的动态图
                      <img src={editCover} alt="封面" className="size-full object-cover" />
                    ) : (
                      <Podcast className="size-5 text-zinc-600" />
                    )}
                  </div>
                  <div>
                    <input
                      ref={editCoverRef}
                      type="file"
                      accept="image/jpeg,image/png"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void uploadCover(f);
                        e.target.value = "";
                      }}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-lg border-white/15 bg-transparent text-xs text-zinc-300 hover:border-primary/40 hover:bg-primary/10 hover:text-primary"
                      onClick={() => editCoverRef.current?.click()}
                      disabled={uploading}
                    >
                      {uploading ? "上传中…" : editCover ? "更换封面" : "上传封面"}
                    </Button>
                    <p className="mt-1.5 text-[10.5px] text-zinc-600">jpg/png · ≤5MB</p>
                  </div>
                  {editCover && (
                    <button
                      type="button"
                      className="text-[11px] text-zinc-500 hover:text-destructive"
                      onClick={() => setEditCover(null)}
                    >
                      移除
                    </button>
                  )}
                </div>
              </div>
            </div>

            {editError && (
              <p className="mt-4 rounded-lg border border-solid border-destructive/30 bg-destructive/[.08] px-3 py-2 text-xs text-red-300">
                {editError}
              </p>
            )}
          </div>

          <div className="mt-2 flex items-center justify-end gap-3 border-t border-solid border-white/[.08] bg-black/20 px-7 py-4">
            <Button
              variant="ghost"
              className="rounded-lg text-zinc-400 hover:bg-white/[.06] hover:text-zinc-200"
              onClick={() => setEditing(null)}
              disabled={editBusy}
            >
              取消
            </Button>
            <Button
              className="h-9 rounded-lg bg-gradient-to-r from-primary to-[#67e8f9] px-7 text-[13px] font-bold text-[#001318] shadow-[0_0_20px_rgba(34,211,238,.3)] transition-shadow hover:shadow-[0_0_30px_rgba(34,211,238,.45)]"
              onClick={() => void saveEdit()}
              disabled={editBusy}
            >
              保存修改
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* 发布/撤下确认弹窗（含风险告知） */}
      <Dialog open={publishing != null} onOpenChange={(open) => !open && setPublishing(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {publishing?.feed_published_at == null ? "发布到 RSS？" : "从 RSS 撤下？"}
            </DialogTitle>
            <DialogDescription>
              {publishing?.feed_published_at == null ? (
                <div className="space-y-2 text-left">
                  <p>发布后该单集将进入你的 RSS 订阅源，在公开范围内可见、可收听下载。</p>
                  <ul className="list-disc space-y-1 pl-4 text-xs">
                    <li>各平台（网易云/小宇宙等）同步周期为数小时至一天</li>
                    <li>部分平台会转存音频，撤下后平台侧可能仍有缓存副本</li>
                    <li>平台侧的审核/下架状态请前往对应平台后台查看</li>
                  </ul>
                  <label className="flex items-center gap-2 pt-1 text-xs">
                    <input
                      type="checkbox"
                      checked={acknowledged}
                      onChange={(e) => setAcknowledged(e.target.checked)}
                      className="h-4 w-4 accent-foreground"
                    />
                    我已了解以上内容
                  </label>
                </div>
              ) : (
                <p>撤下后各订阅平台将在下次同步时移除该单集（通常 24 小时内），随时可重新发布。</p>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishing(null)} disabled={publishBusy}>
              取消
            </Button>
            <Button
              variant={publishing?.feed_published_at == null ? "default" : "destructive"}
              disabled={(publishing?.feed_published_at == null && !acknowledged) || publishBusy}
              onClick={() => void confirmPublish()}
            >
              确认{publishing?.feed_published_at == null ? "发布" : "撤下"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认弹窗 */}
      <Dialog open={deleting != null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除这条播客？</DialogTitle>
            <DialogDescription className="truncate">
              「{deleting?.title || deleting?.topic_prompt}」删除后不可恢复。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)} disabled={deleteBusy}>
              取消
            </Button>
            <Button variant="destructive" onClick={() => void confirmDelete()} disabled={deleteBusy}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
