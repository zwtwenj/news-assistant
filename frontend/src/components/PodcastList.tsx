"use client";

/*
 * 我的播客列表：状态徽章、生成进度、波形播放、编辑（标题/简介/封面）、
 * RSS 发布/撤下（风险告知确认）、删除确认。
 */

import { Loader, Pencil, Podcast, Rss, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AudioPlayer } from "@/components/AudioPlayer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
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
};

type ListResp = { items: Podcast[] };

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中",
  scripting: "撰写脚本",
  synthesizing: "语音合成",
  composing: "音频拼接",
  succeeded: "已完成",
  failed: "失败",
};

// 生成中四阶段的示意进度（非精确，给用户「在动」的反馈；轮询到新状态会跳变）
const STATUS_PROGRESS: Record<string, number> = {
  pending: 8,
  scripting: 35,
  synthesizing: 75,
  composing: 92,
};

// 状态徽章：完成绿 / 失败红 / 进行中蓝 + 旋转图标
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

const inputCls =
  "rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-1.5 text-sm text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50";

export default function PodcastList() {
  const [list, setList] = useState<Podcast[]>([]);
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
    const timer = setTimeout(() => void load(), 0); // StrictMode 双挂载只发一次
    return () => clearTimeout(timer);
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

  const confirmDelete = async () => {
    if (!deleting || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await api(`/podcasts/${deleting.id}`, { method: "DELETE" });
      setDeleting(null);
      await load();
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
      await load();
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
      await load();
    } finally {
      setPublishBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-28 w-full rounded-xl" />
        ))}
      </div>
    );
  }
  if (list.length === 0)
    return (
      <p className="py-16 text-center text-sm text-muted-foreground">
        还没有生成过播客，去「播客生成」创建第一期
      </p>
    );

  return (
    <div className="space-y-4">
      {list.map((p) => {
        const published = p.feed_published_at != null;
        const displayTitle = p.title || p.topic_prompt || "（无标题）";
        const running = STATUS_PROGRESS[p.status] != null;
        return (
          <Card key={p.id} className="py-4 transition-colors hover:border-black/[.15] dark:hover:border-white/[.25]">
            <CardContent className="px-4">
              <div className="flex gap-4">
                {/* 封面：有图用图，无图用渐变占位 */}
                <div className="relative shrink-0">
                  {p.cover_url ? (
                    // eslint-disable-next-line @next/next/no-img-element -- 用户上传的动态图
                    <img src={p.cover_url} alt="" className="size-20 rounded-lg object-cover" />
                  ) : (
                    <div className="flex size-20 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500/80 via-indigo-500/80 to-violet-500/80">
                      <Podcast className="size-8 text-white/90" />
                    </div>
                  )}
                  {running && (
                    <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/40">
                      <Loader className="size-5 animate-spin text-white" />
                    </span>
                  )}
                </div>

                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p
                        className="truncate text-base font-semibold text-foreground"
                        title={displayTitle}
                      >
                        {displayTitle}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                        <StatusBadge status={p.status} />
                        {published && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-orange-100 px-2 py-0.5 text-orange-700 dark:bg-orange-950/50 dark:text-orange-400">
                            <Rss className="size-3" /> 已发布
                          </span>
                        )}
                        <span>{p.mode === "dual" ? "双人对谈" : "单人独白"}</span>
                        <span>·</span>
                        <span>
                          {p.duration_sec
                            ? `${Math.floor(p.duration_sec / 60)}分${p.duration_sec % 60}秒`
                            : `目标 ${p.target_minutes} 分钟`}
                        </span>
                        <span>·</span>
                        <span>{p.created_at}</span>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="text-muted-foreground hover:text-foreground"
                        title="编辑"
                        disabled={p.status === "failed"}
                        onClick={() => openEdit(p)}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="text-muted-foreground hover:text-destructive"
                        title="删除"
                        onClick={() => setDeleting(p)}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </div>

                  {p.description && (
                    <p className="mt-2 line-clamp-2 text-sm leading-relaxed text-muted-foreground">
                      {p.description}
                    </p>
                  )}

                  <div className="mt-auto pt-3">
                    {p.status === "failed" && p.error && (
                      <p className="mb-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                        {p.error}
                      </p>
                    )}
                    {running && (
                      <Progress value={STATUS_PROGRESS[p.status]} className="mb-2" aria-label={STATUS_TEXT[p.status]} />
                    )}
                    {p.status === "succeeded" && p.audio_url && (
                      <div className="flex items-center gap-3">
                        <AudioPlayer src={p.audio_url} className="flex-1" />
                        <button
                          type="button"
                          onClick={() => {
                            setAcknowledged(false);
                            setPublishing(p);
                          }}
                          className="shrink-0 text-xs font-medium text-orange-600 hover:underline dark:text-orange-400"
                        >
                          {published ? "从 RSS 撤下" : "发布到 RSS"}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}


      {/* 编辑弹窗（标题/简介/封面） */}
      <Dialog open={editing != null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>编辑播客信息</DialogTitle>
            <DialogDescription>
              标题与简介用于 RSS 分发展示；已发布到 RSS 的播客，修改会同步到各订阅平台。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-sm text-zinc-500">标题（留空则使用话题提示词）</span>
              <Input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                maxLength={200}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm text-zinc-500">简介</span>
              <Textarea
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                rows={3}
                maxLength={2000}
                className="resize-none"
              />
            </label>
            <div className="flex items-center gap-3">
              {editCover && (
                // eslint-disable-next-line @next/next/no-img-element -- 用户上传的动态图
                <img src={editCover} alt="封面" className="size-14 rounded object-cover" />
              )}
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
                onClick={() => editCoverRef.current?.click()}
                disabled={uploading}
              >
                {uploading ? "上传中…" : "上传封面（jpg/png，≤5MB）"}
              </Button>
              {editCover && (
                <button
                  type="button"
                  className="text-xs text-zinc-400 hover:text-destructive"
                  onClick={() => setEditCover(null)}
                >
                  移除封面
                </button>
              )}
            </div>
            {editError && <p className="text-sm text-destructive">{editError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)} disabled={editBusy}>
              取消
            </Button>
            <Button onClick={() => void saveEdit()} disabled={editBusy}>
              保存
            </Button>
          </DialogFooter>
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
