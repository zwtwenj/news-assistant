"use client";

import { Loader, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AudioPlayer } from "@/components/AudioPlayer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";

export type Podcast = {
  id: number;
  mode: string;
  status: string;
  topic_prompt: string;
  target_minutes: number;
  error: string | null;
  audio_url: string | null;
  duration_sec: number | null;
  created_at: string;
};

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

export default function PodcastList() {
  const [list, setList] = useState<Podcast[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<Podcast | null>(null); // 删除确认弹窗
  const [deleteBusy, setDeleteBusy] = useState(false);

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
    <div className="space-y-3">
      {list.map((p) => {
        const running = STATUS_PROGRESS[p.status] != null;
        return (
          <Card key={p.id} className="py-4">
            <CardContent className="space-y-3 px-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground" title={p.topic_prompt}>
                    {p.topic_prompt || "（无话题提示词）"}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    #{p.id} · {p.mode === "dual" ? "双人对谈" : "单人独白"} · {p.created_at}
                    {p.duration_sec
                      ? ` · ${Math.floor(p.duration_sec / 60)}分${p.duration_sec % 60}秒`
                      : ` · 目标 ${p.target_minutes} 分钟`}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <StatusBadge status={p.status} />
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
              {p.status === "failed" && p.error && (
                <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {p.error}
                </p>
              )}
              {running && (
                <Progress value={STATUS_PROGRESS[p.status]} className="mt-1" aria-label={STATUS_TEXT[p.status]} />
              )}
              {p.status === "succeeded" && p.audio_url && (
                <AudioPlayer src={p.audio_url} className="mt-1" />
              )}
            </CardContent>
          </Card>
        );
      })}

      {/* 删除确认弹窗 */}
      <Dialog open={deleting != null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除这条播客？</DialogTitle>
            <DialogDescription className="truncate">
              「{deleting?.topic_prompt}」删除后不可恢复。
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
