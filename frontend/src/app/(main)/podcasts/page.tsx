"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

type Voice = { id: string; name: string; gender: string };

export default function PodcastWizardPage() {
  const router = useRouter();
  // 两步向导状态
  const [step, setStep] = useState<1 | 2>(1);
  const [mode, setMode] = useState<"single" | "dual">("single");
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voiceA, setVoiceA] = useState("");
  const [voiceB, setVoiceB] = useState("");
  const [scriptPrompt, setScriptPrompt] = useState("");
  const [promptA, setPromptA] = useState("");
  const [promptB, setPromptB] = useState("");
  const [topic, setTopic] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Voice[]>("/podcasts/voices").then(setVoices).catch(() => {});
  }, []);

  const step1Valid =
    mode === "single"
      ? !!voiceA && scriptPrompt.trim().length > 0
      : !!voiceA && !!voiceB && voiceA !== voiceB && promptA.trim() && promptB.trim();

  const submit = async () => {
    setSubmitting(true);
    setError("");
    try {
      await api("/podcasts", {
        method: "POST",
        body: JSON.stringify(
          mode === "single"
            ? { mode, topic_prompt: topic, voice_a: voiceA, script_prompt: scriptPrompt }
            : {
                mode,
                topic_prompt: topic,
                voice_a: voiceA,
                voice_b: voiceB,
                script_prompt_a: promptA,
                script_prompt_b: promptB,
              }
        ),
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

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-black dark:text-zinc-50">播客生成</h1>

      <div className="rounded-lg border border-solid border-black/[.06] bg-white p-5 dark:border-white/[.12] dark:bg-black">
        <div className="mb-4 flex gap-2 text-sm">
          <span className={step === 1 ? "font-semibold text-black dark:text-zinc-50" : "text-zinc-400"}>
            ① 模式与提示词
          </span>
          <span className="text-zinc-300">→</span>
          <span className={step === 2 ? "font-semibold text-black dark:text-zinc-50" : "text-zinc-400"}>
            ② 想播点什么
          </span>
        </div>

        {step === 1 && (
          <div className="max-w-xl space-y-4">
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

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className={labelCls}>{mode === "dual" ? "主播 A 音色" : "主播音色"}</label>
                <select value={voiceA} onChange={(e) => setVoiceA(e.target.value)} className={inputCls}>
                  <option value="">选择音色</option>
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </div>
              {mode === "dual" && (
                <div>
                  <label className={labelCls}>主播 B 音色（需与 A 不同）</label>
                  <select value={voiceB} onChange={(e) => setVoiceB(e.target.value)} className={inputCls}>
                    <option value="">选择音色</option>
                    {voices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {mode === "single" ? (
              <div>
                <label className={labelCls}>脚本提示词（怎么写：风格/口吻）</label>
                <textarea
                  value={scriptPrompt}
                  onChange={(e) => setScriptPrompt(e.target.value)}
                  rows={3}
                  placeholder="例如：轻松随意的清晨电台风格，语气亲切自然，偶尔开个小玩笑"
                  className={inputCls}
                />
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className={labelCls}>A 的脚本提示词（人设）</label>
                  <textarea
                    value={promptA}
                    onChange={(e) => setPromptA(e.target.value)}
                    rows={3}
                    placeholder="例如：严谨的科技编辑，负责讲解新闻背景和数据"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>B 的脚本提示词（人设）</label>
                  <textarea
                    value={promptB}
                    onChange={(e) => setPromptB(e.target.value)}
                    rows={3}
                    placeholder="例如：活泼的吐槽担当，负责接梗和提问"
                    className={inputCls}
                  />
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
            <div>
              <label className={labelCls}>话题提示词（想播点什么，将检索近 7 天相关新闻）</label>
              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                rows={3}
                placeholder="例如：生成一份有关最近天气的播客"
                className={inputCls}
              />
              <p className="mt-1 text-xs text-zinc-400">
                每小时限 3 次、每天限 10 次；点击生成后立即排队（列表中可见），全流程约 1~3 分钟
              </p>
            </div>
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
