"use client";

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

  const inputCls =
    "w-full rounded-md border border-solid border-black/[.1] bg-white px-3 py-2 text-sm text-black outline-none focus:border-black dark:border-white/[.2] dark:bg-black dark:text-zinc-50 dark:focus:border-zinc-50";
  const labelCls = "mb-1 block text-sm text-zinc-600 dark:text-zinc-400";

  // 主播选择卡片：左上名字+radio 圆框，下方介绍，右侧试听
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
          ? "flex w-full items-center gap-3 rounded-lg border-2 border-solid border-foreground bg-white p-3 text-left dark:bg-black"
          : "flex w-full items-center gap-3 rounded-lg border border-solid border-black/[.1] bg-white p-3 text-left hover:border-black/30 dark:border-white/[.15] dark:bg-black dark:hover:border-white/30"
      }
    >
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          {/* radio 圆框 */}
          <span
            className={
              selected
                ? "flex h-4 w-4 items-center justify-center rounded-full border-2 border-foreground"
                : "flex h-4 w-4 items-center justify-center rounded-full border-2 border-zinc-300 dark:border-zinc-600"
            }
          >
            {selected && <span className="h-2 w-2 rounded-full bg-foreground" />}
          </span>
          <span className="truncate text-sm font-medium text-black dark:text-zinc-50">{host.name}</span>
        </span>
        <span className="mt-1 line-clamp-2 block pl-6 text-xs text-zinc-500">
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
              ? "animate-pulse rounded-full bg-blue-100 px-2 py-1 text-sm text-blue-600 dark:bg-blue-900/40"
              : "rounded-full bg-zinc-100 px-2 py-1 text-sm text-zinc-500 hover:text-blue-600 dark:bg-zinc-800"
          }
        >
          {playingId === host.id ? "⏹" : "▶"}
        </span>
      )}
    </button>
  );

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-black dark:text-zinc-50">播客生成</h1>

      <div className="rounded-lg border border-solid border-black/[.06] bg-white p-5 dark:border-white/[.12] dark:bg-black">
        <div className="mb-4 flex gap-2 text-sm">
          <span className={step === 1 ? "font-semibold text-black dark:text-zinc-50" : "text-zinc-400"}>
            ① 模式与主播
          </span>
          <span className="text-zinc-300">→</span>
          <span className={step === 2 ? "font-semibold text-black dark:text-zinc-50" : "text-zinc-400"}>
            ② 想播点什么
          </span>
        </div>

        {step === 1 && (
          <div className="max-w-2xl space-y-4">
            <div>
              <span className={labelCls}>模式</span>
              <div className="flex gap-2">
                {(["single", "dual"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMode(m)}
                    className={
                      mode === m
                        ? "rounded-md bg-foreground px-4 py-2 text-sm text-background"
                        : "rounded-md border border-solid border-black/[.1] px-4 py-2 text-sm text-zinc-600 dark:border-white/[.2] dark:text-zinc-400"
                    }
                  >
                    {m === "single" ? "单人独白" : "双人对谈"}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className={labelCls}>{mode === "dual" ? "主播 A" : "选择主播"}</span>
              {hosts.length === 0 ? (
                <p className="text-sm text-zinc-400">暂无可用主播</p>
              ) : (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {hosts.map((h) => (
                    <HostCard key={h.id} host={h} selected={hostA === h.id} onSelect={() => setHostA(h.id)} />
                  ))}
                </div>
              )}
            </div>

            {mode === "dual" && (
              <div>
                <span className={labelCls}>主播 B（需与 A 不同）</span>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {hosts.map((h) => (
                    <HostCard key={h.id} host={h} selected={hostB === h.id} onSelect={() => setHostB(h.id)} />
                  ))}
                </div>
              </div>
            )}

            <button
              type="button"
              disabled={!step1Valid}
              onClick={() => setStep(2)}
              className="rounded-md bg-foreground px-5 py-2 text-sm text-background disabled:opacity-40"
            >
              下一步
            </button>
          </div>
        )}

        {step === 2 && (
          <div className="max-w-xl space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className={labelCls}>播客时长</label>
                <select
                  value={targetMinutes}
                  onChange={(e) => setTargetMinutes(Number(e.target.value))}
                  className={inputCls}
                >
                  <option value={2}>短（1~2 分钟）· 1 条素材</option>
                  <option value={4}>中（3~5 分钟）· 最多 3 条素材</option>
                  <option value={7}>长（5~8 分钟）· 最多 5 条素材</option>
                </select>
                <p className="mt-1 text-xs text-zinc-400">
                  素材不足时对已有内容深聊，只有完全无相关新闻才会拒绝生成
                </p>
              </div>
              <div>
                <label className={labelCls}>话题提示词（想播点什么，将检索近 7 天相关新闻，优先最新）</label>
                <textarea
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  rows={3}
                  placeholder="例如：生成一份有关最近天气的播客"
                  className={inputCls}
                />
              </div>
            </div>
            <p className="text-xs text-zinc-400">
              每小时限 3 次、每天限 10 次；点击生成后立即排队（列表中可见），全流程约 1~3 分钟
            </p>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="rounded-md border border-solid border-black/[.1] px-5 py-2 text-sm dark:border-white/[.2]"
              >
                上一步
              </button>
              <button
                type="button"
                disabled={!topic.trim() || submitting}
                onClick={() => void submit()}
                className="rounded-md bg-foreground px-5 py-2 text-sm text-background disabled:opacity-40"
              >
                {submitting ? "提交中…" : "开始生成"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
