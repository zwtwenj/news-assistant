"use client";

import { Check, Loader2, Mic, Mic2, Play, Square, User } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

type Host = {
  id: number;
  name: string;
  gender: string;
  description: string | null;
  sample_url: string | null;
};

const DURATIONS = [
  { value: 2, label: "短", hint: "1~2 分钟 · 1 条素材" },
  { value: 4, label: "中", hint: "3~5 分钟 · 最多 3 条" },
  { value: 7, label: "长", hint: "5~8 分钟 · 最多 5 条" },
];

function Stepper({ step }: { step: 1 | 2 }) {
  const dot = (n: 1 | 2, text: string) => {
    const active = step === n;
    const done = step > n;
    return (
      <span className="flex items-center gap-2">
        <span
          className={
            done
              ? "flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground"
              : active
                ? "flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground"
                : "flex size-6 items-center justify-center rounded-full border border-border text-muted-foreground"
          }
        >
          {done ? <Check className="size-3.5" /> : n}
        </span>
        <span className={active || done ? "font-medium text-foreground" : "text-muted-foreground"}>
          {text}
        </span>
      </span>
    );
  };
  return (
    <div className="flex items-center gap-3 text-sm">
      {dot(1, "模式与主播")}
      <span className="h-px w-8 bg-border" />
      {dot(2, "想播点什么")}
    </div>
  );
}

export default function PodcastWizardPage() {
  const router = useRouter();
  // 两步向导状态
  const [step, setStep] = useState<1 | 2>(1);
  const [mode, setMode] = useState<"single" | "dual">("single");
  const [hosts, setHosts] = useState<Host[]>([]);
  const [hostA, setHostA] = useState<number | null>(null);
  const [hostB, setHostB] = useState<number | null>(null);
  const [playingId, setPlayingId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null); // 单实例试听（同时只播一个）
  const [topic, setTopic] = useState("");
  const [targetMinutes, setTargetMinutes] = useState(4);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // 定时器 + 清理：StrictMode 双挂载只发一次请求
    const timer = setTimeout(() => {
      api<Host[]>("/hosts").then(setHosts).catch(() => {});
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const togglePlay = (h: Host) => {
    if (!h.sample_url) return;
    const audio = audioRef.current ?? new Audio();
    audioRef.current = audio;
    if (playingId === h.id) {
      audio.pause();
      audio.currentTime = 0;
      setPlayingId(null);
      return;
    }
    audio.pause();
    audio.currentTime = 0;
    audio.src = h.sample_url;
    audio.onended = () => setPlayingId(null);
    audio.onerror = () => setPlayingId(null);
    void audio.play().then(() => setPlayingId(h.id)).catch(() => setPlayingId(null));
  };

  useEffect(
    () => () => {
      audioRef.current?.pause();
    },
    []
  );

  const step1Valid =
    mode === "single" ? hostA != null : hostA != null && hostB != null && hostA !== hostB;

  const submit = async () => {
    if (hostA == null) return;
    setSubmitting(true);
    setError("");
    try {
      await api("/podcasts", {
        method: "POST",
        body: JSON.stringify({
          mode,
          topic_prompt: topic,
          target_minutes: targetMinutes,
          host_a: hostA,
          host_b: mode === "dual" ? hostB : null,
        }),
      });
      router.push("/podcasts/history"); // 已入库排队，去列表页看进度
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
      setSubmitting(false);
    }
  };

  // 主播选择卡片：选中态 primary 描边 + 角标，性别图标，右侧试听
  const HostCard = ({
    host,
    selected,
    onSelect,
  }: {
    host: Host;
    selected: boolean;
    onSelect: () => void;
  }) => (
    <button
      type="button"
      onClick={onSelect}
      className={
        selected
          ? "group relative flex w-full items-center gap-3 rounded-xl border-2 border-primary bg-card p-3.5 text-left shadow-sm"
          : "flex w-full items-center gap-3 rounded-xl border border-border bg-card p-3.5 text-left transition-colors hover:border-primary/40"
      }
    >
      {selected && (
        <span className="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Check className="size-3" />
        </span>
      )}
      <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        {host.gender === "female" ? <Mic2 className="size-4.5" /> : <Mic className="size-4.5" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{host.name}</span>
        <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
          {host.description || "暂无介绍"}
        </span>
      </span>
      {host.sample_url && (
        <span
          role="button"
          tabIndex={0}
          title={playingId === host.id ? "停止试听" : "试听"}
          onClick={(e) => {
            e.stopPropagation(); // 点试听不触发选卡
            togglePlay(host);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.stopPropagation();
              togglePlay(host);
            }
          }}
          className={
            playingId === host.id
              ? "flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"
              : "flex size-8 shrink-0 items-center justify-center rounded-full border border-border text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
          }
        >
          {playingId === host.id ? (
            <Square className="size-3 fill-current" />
          ) : (
            <Play className="size-3 translate-x-px fill-current" />
          )}
        </span>
      )}
    </button>
  );

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">播客生成</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          两步创建你的专属新闻播客：选择主播，告诉它想播什么
        </p>
      </div>

      <Card>
        <CardContent className="space-y-6">
          <Stepper step={step} />

          {step === 1 && (
            <div className="space-y-5">
              <div>
                <p className="mb-2 text-sm font-medium text-foreground">播出形式</p>
                <div className="grid grid-cols-2 gap-3">
                  {(
                    [
                      { value: "single", title: "单人独白", desc: "一位主播娓娓道来" },
                      { value: "dual", title: "双人对谈", desc: "两位主播观点碰撞" },
                    ] as const
                  ).map((m) => (
                    <button
                      key={m.value}
                      type="button"
                      onClick={() => setMode(m.value)}
                      className={
                        mode === m.value
                          ? "relative rounded-xl border-2 border-primary bg-card p-3.5 text-left"
                          : "rounded-xl border border-border bg-card p-3.5 text-left transition-colors hover:border-primary/40"
                      }
                    >
                      {mode === m.value && (
                        <span className="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                          <Check className="size-3" />
                        </span>
                      )}
                      <span className="block text-sm font-medium text-foreground">{m.title}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{m.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-foreground">
                  <User className="size-4 text-muted-foreground" />
                  {mode === "dual" ? "主播 A" : "选择主播"}
                </p>
                {hosts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">暂无可用主播</p>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {hosts.map((h) => (
                      <HostCard
                        key={h.id}
                        host={h}
                        selected={hostA === h.id}
                        onSelect={() => setHostA(h.id)}
                      />
                    ))}
                  </div>
                )}
              </div>

              {mode === "dual" && (
                <div>
                  <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-foreground">
                    <User className="size-4 text-muted-foreground" />
                    主播 B（需与 A 不同）
                  </p>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {hosts.map((h) => (
                      <HostCard
                        key={h.id}
                        host={h}
                        selected={hostB === h.id}
                        onSelect={() => setHostB(h.id)}
                      />
                    ))}
                  </div>
                </div>
              )}

              <Button size="lg" className="w-full sm:w-auto" disabled={!step1Valid} onClick={() => setStep(2)}>
                下一步
              </Button>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <div>
                <p className="mb-2 text-sm font-medium text-foreground">播客时长</p>
                <div className="grid grid-cols-3 gap-2">
                  {DURATIONS.map((d) => (
                    <button
                      key={d.value}
                      type="button"
                      onClick={() => setTargetMinutes(d.value)}
                      className={
                        targetMinutes === d.value
                          ? "rounded-xl border-2 border-primary bg-primary/5 px-3 py-2.5 text-left"
                          : "rounded-xl border border-border px-3 py-2.5 text-left transition-colors hover:border-primary/40"
                      }
                    >
                      <span className="block text-sm font-medium text-foreground">{d.label}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{d.hint}</span>
                    </button>
                  ))}
                </div>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  素材不足时对已有内容深聊，只有完全无相关新闻才会拒绝生成
                </p>
              </div>

              <div>
                <p className="mb-2 text-sm font-medium text-foreground">话题提示词</p>
                <Textarea
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  rows={4}
                  maxLength={500}
                  placeholder="例如：生成一份有关最近天气的播客"
                  className="resize-none"
                />
                <p className="mt-1 text-right text-xs text-muted-foreground">
                  {topic.length} / 500 · 将检索近 7 天相关新闻，优先最新
                </p>
              </div>

              {error && <p className="text-sm text-destructive">{error}</p>}

              <div className="flex items-center gap-3">
                <Button variant="outline" size="lg" onClick={() => setStep(1)} disabled={submitting}>
                  上一步
                </Button>
                <Button
                  size="lg"
                  className="flex-1 sm:flex-none sm:px-8"
                  disabled={!topic.trim() || submitting}
                  onClick={() => void submit()}
                >
                  {submitting && <Loader2 className="size-4 animate-spin" />}
                  {submitting ? "提交中…" : "开始生成"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                每小时限 3 次、每天限 10 次；点击生成后立即排队（列表中可见），全流程约 1~3 分钟
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
