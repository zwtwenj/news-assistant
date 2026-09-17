"use client";

import { Check, Loader2, Play, Square } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

type Host = {
  id: number;
  name: string;
  gender: string;
  description: string | null;
  sample_url: string | null;
};

const DURATIONS = [
  { value: 2, label: "短", range: "1~2 分钟", hint: "消耗 1 条素材", bars: 2 },
  { value: 4, label: "中", range: "3~5 分钟", hint: "最多 3 条素材", bars: 3 },
  { value: 7, label: "长", range: "5~8 分钟", hint: "最多 5 条素材", bars: 5 },
];

/* 试听按钮里的迷你波形（纯装饰） */
function MiniWave() {
  return (
    <span className="flex h-3 items-end gap-[2px]">
      {[6, 11, 8, 12].map((h, i) => (
        <i key={i} style={{ height: h }} className="w-[2px] rounded-sm bg-current" />
      ))}
    </span>
  );
}

export default function PodcastWizardPage() {
  const router = useRouter();
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
  // 生成配额余量（GET /podcasts/quota）
  const [quota, setQuota] = useState<{ hourly_left: number; daily_left: number } | null>(null);

  useEffect(() => {
    // 定时器 + 清理：StrictMode 双挂载只发一次请求
    const timer = setTimeout(() => {
      api<Host[]>("/hosts").then(setHosts).catch(() => {});
      api<{ hourly_left: number; daily_left: number }>("/podcasts/quota")
        .then(setQuota)
        .catch(() => {});
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
    [],
  );

  // 主播点选：单人选 1 位；双人依次填 A/B（点已选取消，都满后忽略）
  const toggleHost = (h: Host) => {
    if (mode === "single") {
      setHostA((prev) => (prev === h.id ? null : h.id));
      return;
    }
    if (hostA === h.id) {
      setHostA(null);
    } else if (hostB === h.id) {
      setHostB(null);
    } else if (hostA == null) {
      setHostA(h.id);
    } else if (hostB == null) {
      setHostB(h.id);
    }
  };

  const step1Valid =
    mode === "single" ? hostA != null : hostA != null && hostB != null && hostA !== hostB;
  const canSubmit = step1Valid && topic.trim().length > 0 && !submitting;

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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-bold tracking-wide text-foreground">播客生成</h1>
        <span className="rounded-md border border-solid border-border px-3 py-1 font-mono text-[11px] tracking-[2px] text-zinc-500">
          {submitting ? "ON AIR" : "OFF AIR"}
        </span>
        {quota && (
          <span className="ml-auto font-mono text-[11px] text-zinc-400">
            今日剩余 <b className="font-bold text-emerald-400">{quota.daily_left}</b> 期 · 本小时剩余{" "}
            <b className="font-bold text-emerald-400">{quota.hourly_left}</b> 期
          </span>
        )}
      </div>

      <div className="grid gap-3.5 lg:grid-cols-[460px_1fr]">
        {/* 左：主播通道条 */}
        <div className="rounded-2xl border border-solid border-border bg-white/[.04] p-5">
          <div className="mb-4 flex items-center gap-2.5">
            <span className="font-mono text-[10.5px] tracking-[2px] text-zinc-600">01 · HOSTS</span>
            <span className="text-sm font-semibold text-foreground">选择主播</span>
            <span className="ml-auto text-[11px] text-zinc-600">点击试听声音</span>
          </div>

          {/* 播出形式 */}
          <div className="mb-5 grid grid-cols-2 gap-2.5">
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
                className={`rounded-xl border p-3 text-left transition-colors ${
                  mode === m.value
                    ? "border-primary bg-primary/[.07]"
                    : "border-border bg-black/25 hover:border-primary/35"
                }`}
              >
                <span
                  className={`block text-sm font-semibold ${mode === m.value ? "text-primary" : "text-foreground"}`}
                >
                  {m.title}
                </span>
                <span className="mt-0.5 block text-[11.5px] text-muted-foreground">{m.desc}</span>
              </button>
            ))}
          </div>

          {/* 主播通道条 */}
          <div className="flex flex-col gap-2.5">
            {hosts.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无可用主播</p>
            ) : (
              hosts.map((h) => {
                const selected = hostA === h.id || (mode === "dual" && hostB === h.id);
                const role = hostA === h.id ? "A" : hostB === h.id ? "B" : null;
                return (
                  <button
                    key={h.id}
                    type="button"
                    onClick={() => toggleHost(h)}
                    className={`relative flex items-center gap-3.5 rounded-xl border p-3.5 text-left transition-colors ${
                      selected
                        ? "border-primary bg-primary/[.06]"
                        : "border-border bg-black/25 hover:border-primary/35"
                    }`}
                  >
                    {selected && (
                      <span
                        className={`absolute -top-2 -right-2 flex size-6 items-center justify-center rounded-full font-mono text-[11px] font-bold text-[#001318] ${
                          role === "B" ? "bg-[#a78bfa]" : "bg-primary"
                        }`}
                      >
                        {mode === "dual" ? role : <Check className="size-3.5" />}
                      </span>
                    )}
                    <span
                      className={`absolute top-3.5 bottom-3.5 left-0 w-[2px] rounded-r ${
                        selected ? "bg-primary shadow-[0_0_8px_rgba(34,211,238,.6)]" : "bg-transparent"
                      }`}
                    />
                    <span className="flex size-[52px] shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary to-[#a78bfa] text-lg font-bold text-[#001318]">
                      {h.name.slice(0, 1)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-foreground">
                        {h.name}
                      </span>
                      <span className="mt-0.5 block truncate text-[11.5px] text-muted-foreground">
                        {h.description || "暂无介绍"}
                      </span>
                    </span>
                    {h.sample_url && (
                      <span
                        role="button"
                        tabIndex={0}
                        title={playingId === h.id ? "停止试听" : "试听"}
                        onClick={(e) => {
                          e.stopPropagation(); // 点试听不触发选卡
                          togglePlay(h);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.stopPropagation();
                            togglePlay(h);
                          }
                        }}
                        className="flex shrink-0 items-center gap-2 rounded-full border border-solid border-border px-3.5 py-1.5 text-[11.5px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                      >
                        {playingId === h.id ? (
                          <Square className="size-3 fill-current" />
                        ) : (
                          <Play className="size-3 fill-current" />
                        )}
                        <MiniWave />
                        试听
                      </span>
                    )}
                  </button>
                );
              })
            )}
          </div>
          {mode === "dual" && (
            <p className="mt-3 text-[11px] text-zinc-600">※ 双人对谈需选择两位不同主播；试听不消耗生成次数</p>
          )}
        </div>

        {/* 右：节目参数 + 开播 */}
        <div className="flex min-h-0 flex-col gap-4 rounded-2xl border border-solid border-border bg-white/[.04] p-5">
          {/* 对谈阵容确认条（双人模式且选齐时出现） */}
          {mode === "dual" && hostA != null && hostB != null && (
            <div className="flex items-center gap-2.5 rounded-lg border border-solid border-primary/25 bg-primary/[.05] px-3.5 py-2.5">
              <span className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-primary to-[#a78bfa] text-[13px] font-bold text-[#001318]">
                {(hosts.find((h) => h.id === hostA)?.name ?? "?").slice(0, 1)}
              </span>
              <span className="font-mono text-xs text-primary">×</span>
              <span className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-primary text-[13px] font-bold text-[#001318]">
                {(hosts.find((h) => h.id === hostB)?.name ?? "?").slice(0, 1)}
              </span>
              <span className="text-[13px] font-semibold">
                {hosts.find((h) => h.id === hostA)?.name} × {hosts.find((h) => h.id === hostB)?.name}
              </span>
              <span className="ml-auto font-mono text-[10px] tracking-wider text-emerald-400">
                对谈阵容已确认
              </span>
            </div>
          )}

          <div>
            <p className="mb-2.5 text-[12.5px] font-medium text-muted-foreground">节目时长</p>
            <div className="grid grid-cols-3 gap-2.5">
              {DURATIONS.map((d) => (
                <button
                  key={d.value}
                  type="button"
                  onClick={() => setTargetMinutes(d.value)}
                  className={`rounded-xl border p-3 text-left transition-colors ${
                    targetMinutes === d.value
                      ? "border-primary bg-primary/[.06]"
                      : "border-border bg-black/25 hover:border-primary/35"
                  }`}
                >
                  <span className="flex items-baseline gap-1.5">
                    <span className="text-[13.5px] font-semibold text-foreground">{d.label}</span>
                    <span className="text-[11px] text-muted-foreground">{d.range}</span>
                  </span>
                  <span className="mt-1 block text-[11px] text-zinc-500">{d.hint}</span>
                  <span className="mt-2 flex gap-1">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <i
                        key={i}
                        className={`h-1 flex-1 rounded-sm ${
                          i < d.bars
                            ? targetMinutes === d.value
                              ? "bg-primary shadow-[0_0_6px_rgba(34,211,238,.4)]"
                              : "bg-zinc-700"
                            : "bg-white/[.06]"
                        }`}
                      />
                    ))}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            <p className="mb-2.5 text-[12.5px] font-medium text-muted-foreground">话题提示词</p>
            <div className="relative flex min-h-0 flex-1 flex-col rounded-xl border border-solid border-border bg-black/30">
              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                rows={6}
                maxLength={500}
                placeholder="例如：聊聊最近关于金砖合作与国际贸易的新闻，重点讲清楚对普通人的影响，语气轻松一点，最后做个总结。"
                className="min-h-32 w-full flex-1 resize-none rounded-xl bg-transparent p-4 text-sm leading-loose text-foreground outline-none placeholder:text-zinc-600"
              />
              <span className="absolute right-3 bottom-2 font-mono text-[10.5px] text-zinc-600">
                {topic.length} / 500
              </span>
            </div>
            <p className="mt-1.5 text-[11px] text-zinc-600">
              素材不足时对已有内容深聊，只有完全无相关新闻才会拒绝生成 · 检索近 7 天相关新闻，优先最新
            </p>
          </div>

          {error && (
            <p className="rounded-lg border border-solid border-destructive/30 bg-destructive/[.06] px-3 py-2 text-xs text-red-300">
              {error}
            </p>
          )}

          {/* ON AIR 开播区 */}
          <div className="mt-auto flex items-center gap-4 rounded-xl border border-solid border-border bg-gradient-to-r from-primary/[.05] to-transparent px-5 py-4">
            <button
              type="button"
              disabled={!canSubmit}
              onClick={() => void submit()}
              className="h-12 shrink-0 rounded-xl bg-gradient-to-r from-primary to-[#67e8f9] px-12 text-[15px] font-extrabold tracking-[3px] text-[#001318] shadow-[0_0_24px_rgba(34,211,238,.35)] transition-shadow hover:shadow-[0_0_36px_rgba(34,211,238,.5)] disabled:opacity-40 disabled:shadow-none"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 inline size-4 animate-spin" />
                  提交中…
                </>
              ) : (
                "开始生成 ▶"
              )}
            </button>
            <p className="font-mono text-[11px] leading-relaxed text-zinc-500">
              每小时限 3 次 · 每天限 10 次
              <br />
              点击后立即排队，全流程约 1~3 分钟 → 进度见「我的播客」
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
