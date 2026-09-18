"use client";

/*
 * AI 助手聊天页：多会话（IndexedDB）+ SSE 流式渲染 + 引用溯源 + 工具过程可见化
 * + 图片上传 + 语音输入（MediaRecorder→ASR）+ 回答语音播报（TTS）。
 */

import {
  ArrowUp,
  Image as ImageIcon,
  Loader2,
  MessageSquarePlus,
  Mic,
  Square,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import Spinner from "@/components/Spinner";
import { ApiError, api } from "@/lib/api";
import {
  type Conversation,
  type MessageMeta,
  type StoredMessage,
  addMessage,
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
} from "@/lib/chat-store";

type ToolEvent = { name: string; result: unknown };

const TOOL_LABELS: Record<string, string> = {
  list_today_news: "检索新闻库",
  match_similar_tags: "匹配相关标签",
  web_search_news: "联网搜索",
  analyze_image: "分析图片",
};

export default function ChatPage() {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [pendingImage, setPendingImage] = useState<{ id: string; preview: string } | null>(null);
  const [error, setError] = useState("");
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    void (async () => {
      const list = await listConversations();
      setConvs(list);
      if (list.length) setActiveId(list[0].id);
    })();
  }, []);

  useEffect(() => {
    if (activeId) void listMessages(activeId).then(setMessages);
  }, [activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamText, toolEvents]);

  const newConversation = async () => {
    const conv = await createConversation();
    setConvs((l) => [conv, ...l]);
    setActiveId(conv.id);
    setMessages([]);
  };

  const removeConversation = async (id: string) => {
    await deleteConversation(id);
    const list = await listConversations();
    setConvs(list);
    if (activeId === id) {
      setActiveId(list[0]?.id ?? null);
      setMessages([]);
    }
  };

  const uploadImage = useCallback(async (file: File) => {
    setError("");
    const preview = await new Promise<string>((resolve) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result));
      r.readAsDataURL(file);
    });
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await api<{ image_id: string }>("/chat/upload-image", {
        method: "POST",
        body: form,
      });
      setPendingImage({ id: resp.image_id, preview });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "图片上传失败");
    }
  }, []);

  const toggleRecord = async () => {
    if (recording) {
      recorderRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        try {
          const form = new FormData();
          form.append("file", new File([blob], "speech.webm", { type: "audio/webm" }));
          const resp = await api<{ text: string }>("/chat/voice-input", {
            method: "POST",
            body: form,
          });
          if (resp.text) setInput((t) => (t ? t + resp.text : resp.text));
        } catch {
          setError("语音识别失败");
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      setError("无法访问麦克风");
    }
  };

  const speak = async (text: string) => {
    if (speaking) return;
    setSpeaking(true);
    try {
      const resp = await fetch("/api/v1/chat/voice-output", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ text: text.slice(0, 2000) }),
      });
      if (resp.ok) {
        const blob = await resp.blob();
        await new Promise<void>((resolve) => {
          const audio = new Audio(URL.createObjectURL(blob));
          audio.onended = () => resolve();
          void audio.play();
        });
      }
    } catch {
      /* 播报失败静默 */
    } finally {
      setSpeaking(false);
    }
  };

  const send = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || streaming) return;
    setError("");
    setStreaming(true);
    setStreamText("");
    setToolEvents([]);
    if (!override) setInput("");

    // 首次发送时自动建会话
    let convId = activeId;
    if (!convId) {
      const conv = await createConversation();
      convId = conv.id;
      setConvs((l) => [conv, ...l]);
      setActiveId(conv.id);
    }
    await addMessage(convId, "user", text, pendingImage ? { image_id: pendingImage.id, image_preview: pendingImage.preview } : undefined);
    setMessages(await listMessages(convId));
    const history = (await listMessages(convId)).slice(-60).map((m) => ({ role: m.role, content: m.content }));

    let answer = "";
    const meta: MessageMeta = {};
    if (pendingImage) meta.image_id = pendingImage.id;
    const collectedTools: ToolEvent[] = [];
    setPendingImage(null);

    try {
      const resp = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          messages: [...history, { role: "user", content: text }],
          image_id: meta.image_id ?? null,
        }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "meta") {
              meta.rag_sources = ev.rag_sources;
              meta.memories = ev.memories;
              meta.used_query = ev.used_query;
            } else if (ev.type === "delta") {
              answer += ev.content;
              setStreamText(answer);
            } else if (ev.type === "tool") {
              collectedTools.push({ name: ev.name, result: ev.result });
              meta.tool_calls = collectedTools;
              if (ev.rag_sources) meta.rag_sources = ev.rag_sources;
              setToolEvents([...collectedTools]);
            } else if (ev.type === "done") {
              if (ev.trace_id) meta.trace_id = ev.trace_id;
            } else if (ev.type === "error") {
              throw new Error(ev.message);
            }
          } catch {
            /* 忽略解析失败的事件 */
          }
        }
      }
      const saved = await addMessage(convId, "assistant", answer || "（无回复）", meta);
      setMessages((prev) => [...prev, saved]);
      const list = await listConversations();
      setConvs(list);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "对话失败";
      setError(msg);
      if (answer || msg) {
        await addMessage(convId, "assistant", answer || `⚠ ${msg}`, { ...meta, error: answer ? undefined : msg });
      }
      setMessages(await listMessages(convId));
    } finally {
      setStreaming(false);
      setStreamText("");
      setToolEvents([]);
    }
  };

  return (
    <div className="flex h-[calc(100dvh-108px)] gap-3.5">
      {/* 会话侧栏 */}
      <aside
        className={`${sidebarOpen ? "flex" : "hidden"} absolute inset-y-0 left-0 z-20 w-64 flex-col rounded-xl border border-solid border-border bg-white/[.04] p-3 md:relative md:flex dark:bg-white/[.02]`}
      >
        <button
          type="button"
          onClick={() => void newConversation()}
          className="mb-3 flex items-center justify-center gap-2 rounded-lg border border-solid border-primary/40 bg-primary/[.07] px-3 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/[.14]"
        >
          <MessageSquarePlus className="size-4" /> 新对话
        </button>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {convs.map((c) => (
            <div
              key={c.id}
              className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-sm ${
                c.id === activeId
                  ? "bg-primary/[.08] font-medium text-zinc-100"
                  : "text-zinc-400 hover:bg-white/[.05] hover:text-zinc-200"
              }`}
              onClick={() => {
                setActiveId(c.id);
                setSidebarOpen(false);
              }}
            >
              <span className="truncate">{c.title}</span>
              <button
                type="button"
                className="hidden text-zinc-500 hover:text-destructive group-hover:block"
                onClick={(e) => {
                  e.stopPropagation();
                  void removeConversation(c.id);
                }}
                title="删除会话"
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
          {!convs.length && <p className="px-2 py-4 text-xs text-zinc-500">还没有对话</p>}
        </div>
      </aside>

      {/* 主聊天区 */}
      <section className="relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-solid border-border bg-white/[.04]">
        <header className="flex items-center gap-2 border-b border-solid border-border px-4 py-3">
          <button
            type="button"
            className="rounded-md px-2 py-1 text-sm text-zinc-500 md:hidden"
            onClick={() => setSidebarOpen((v) => !v)}
          >
            ☰
          </button>
          <h1 className="text-sm font-semibold text-foreground">AI 助手 · 小讯</h1>
          <span className="text-xs text-zinc-500">基于新闻库回答 · 支持多轮追问</span>
          <span className="ml-auto font-mono text-[10px] tracking-[2px] text-zinc-600">RAG://ONLINE</span>
        </header>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          {!messages.length && !streaming && (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-zinc-400">
              <div className="flex size-12 items-center justify-center rounded-full border border-solid border-primary/30 bg-primary/10 text-base font-bold text-primary">
                讯
              </div>
              <p className="text-sm">问我任何新闻相关的问题</p>
              <div className="flex flex-wrap justify-center gap-2">
                {["今天有什么新闻", "自然灾害相关报道", "还有吗"].map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => {
                      setInput(s);
                      void send(s);
                    }}
                    className="rounded-full border border-solid border-border bg-white/[.03] px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-primary/40 hover:text-primary"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble
              key={m.id}
              msg={m}
              onSpeak={speak}
              speaking={speaking}
              onFeedback={(tid, r) => void api("/chat/feedback", {
                method: "POST",
                body: JSON.stringify({ trace_id: tid, rating: r ?? 0, cancel: r == null }),
              }).then(() => {
                setMessages((prev) =>
                  prev.map((x) => {
                    if (x.id !== m.id) return x;
                    const meta = { ...x.meta };
                    if (r == null) delete meta.feedback;
                    else meta.feedback = r;
                    return { ...x, meta };
                  }),
                );
              })}
            />
          ))}
          {streaming && (
            <div className="flex justify-start">
              <div className="max-w-[85%] space-y-2">
                {toolEvents.map((t, i) => (
                  <p key={i} className="flex items-center gap-1.5 font-mono text-[11px] text-primary/80">
                    <Loader2 className="size-3 animate-spin" />
                    {TOOL_LABELS[t.name] ?? t.name}
                  </p>
                ))}
                {streamText ? (
                  <div className="whitespace-pre-wrap rounded-lg border border-solid border-border bg-white/[.05] px-3.5 py-2.5 text-sm leading-relaxed text-zinc-200">
                    {streamText}
                    <span className="ml-0.5 inline-block h-3.5 w-[6px] animate-pulse bg-primary align-middle" />
                  </div>
                ) : (
                  !toolEvents.length && <Spinner label="思考中…" />
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 输入区 */}
        <footer className="border-t border-solid border-border p-3.5">
          {pendingImage && (
            <div className="mb-2 flex items-center gap-2 text-xs text-zinc-500">
              {/* eslint-disable-next-line @next/next/no-img-element -- 用户上传预览 */}
              <img src={pendingImage.preview} alt="待发送" className="size-10 rounded object-cover" />
              <span>图片已就绪（5 分钟内有效）</span>
              <button type="button" onClick={() => setPendingImage(null)} className="text-zinc-500 hover:text-red-400">
                <X className="size-3.5" />
              </button>
            </div>
          )}
          {error && <p className="mb-2 text-xs text-red-400">{error}</p>}
          <div className="flex items-end gap-2">
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void uploadImage(f);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="rounded-lg p-2 text-zinc-500 hover:text-primary"
              title="上传图片"
            >
              <ImageIcon className="size-5" />
            </button>
            <button
              type="button"
              onClick={() => void toggleRecord()}
              className={`rounded-lg p-2 ${recording ? "text-red-400" : "text-zinc-500 hover:text-foreground"}`}
              title={recording ? "停止录音" : "语音输入"}
            >
              {recording ? <Square className="size-5" /> : <Mic className="size-5" />}
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              rows={1}
              placeholder="输入问题，Enter 发送（Shift+Enter 换行）"
              className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-lg border border-solid border-white/10 bg-black/30 px-3.5 py-2.5 text-sm text-foreground outline-none placeholder:text-zinc-600 focus:border-primary focus:ring-[3px] focus:ring-primary/15"
            />
            <button
              type="button"
              disabled={!input.trim() || streaming}
              onClick={() => void send()}
              className="rounded-lg bg-gradient-to-r from-primary to-[#67e8f9] p-2.5 text-[#001318] shadow-[0_0_16px_rgba(34,211,238,.3)] transition-shadow hover:shadow-[0_0_26px_rgba(34,211,238,.5)] disabled:opacity-40 disabled:shadow-none"
              title="发送"
            >
              <ArrowUp className="size-4" />
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function MessageBubble({
  msg,
  onSpeak,
  speaking,
  onFeedback,
}: {
  msg: StoredMessage;
  onSpeak: (t: string) => void;
  speaking: boolean;
  onFeedback: (traceId: string, rating: 0 | 1 | null) => void;
}) {
  const [feedbackShown, setFeedbackShown] = useState(msg.meta?.feedback ?? null);
  if (feedbackShown !== (msg.meta?.feedback ?? null)) {
    // 渲染期校正：外部数据变化直接反映（无副作用，安全）
    setFeedbackShown(msg.meta?.feedback ?? null);
  }
  const feedback = feedbackShown;
  const isUser = msg.role === "user";
  const newsResult = !isUser
    ? (msg.meta?.tool_calls ?? []).filter((t) => t.name === "list_today_news")
    : [];
  const msgTime = new Date(msg.created_at);
  const timeText = `${String(msgTime.getHours()).padStart(2, "0")}:${String(msgTime.getMinutes()).padStart(2, "0")}`;

  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div className="mb-1 flex items-center gap-2 text-[10px] text-zinc-500">
        {!isUser && (
          <>
            <span className="flex size-5 items-center justify-center rounded-full bg-gradient-to-br from-primary to-[#a78bfa] text-[9px] font-bold text-[#001318]">
              讯
            </span>
            <span className="font-medium text-zinc-400">小讯</span>
          </>
        )}
        <span className="font-mono">{timeText}</span>
      </div>
      {msg.meta?.image_preview && (
        // eslint-disable-next-line @next/next/no-img-element -- 用户上传预览
        <img src={msg.meta.image_preview} alt="" className="mb-2 max-h-40 rounded-lg object-cover" />
      )}
      {msg.content && (
        <div
          className={`whitespace-pre-wrap px-3.5 py-2.5 text-sm leading-relaxed ${
            isUser
              ? "rounded-xl border border-solid border-primary/25 bg-primary/[.08] text-zinc-100"
              : "rounded-lg bg-white/[.05] text-zinc-200"
          }`}
        >
          {msg.content}
        </div>
      )}
      {/* 今日新闻列表 */}
      {newsResult.map((t, i) => {
        const r = t.result as { items?: { title: string; url: string; source: string; publish_time: string }[]; page?: number; has_more?: boolean };
        return (
          <div key={i} className="mt-2 w-full space-y-1 rounded-lg border border-solid border-border bg-black/25 p-2.5">
            {(r.items ?? []).map((item, j) => (
              <a
                key={j}
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-xs text-zinc-400 hover:text-primary"
              >
                · {item.title}
                <span className="ml-1.5 font-mono text-[10px] text-zinc-600">
                  {item.source} {item.publish_time}
                </span>
              </a>
            ))}
            {r.has_more && <p className="text-xs text-zinc-500">（第 {r.page} 页，还有更多，可说“还有吗”）</p>}
          </div>
        );
      })}
      {/* 引用来源 */}
      {!isUser && msg.meta?.rag_sources && msg.meta.rag_sources.length > 0 && (
        <details className="mt-2 w-full rounded-lg border border-solid border-border bg-black/25 px-3 py-2 text-xs">
          <summary className="cursor-pointer text-zinc-400">
            引用来源（{msg.meta.rag_sources.length}）
          </summary>
          <div className="mt-1.5 space-y-1">
            {msg.meta.rag_sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-zinc-400 hover:text-primary"
              >
                [{i + 1}] {s.title}
              </a>
            ))}
          </div>
        </details>
      )}
      {!isUser && msg.content.length > 4 && (
        <div className="mt-2 flex items-center gap-3 text-xs text-zinc-500">
          <button
            type="button"
            disabled={speaking}
            onClick={() => void onSpeak(msg.content)}
            className="flex items-center gap-1 hover:text-foreground"
            title="语音播报"
          >
            <Volume2 className="size-3.5" /> 播报
          </button>
          {msg.meta?.trace_id && (
            <>
              <button
                type="button"
                onClick={() => onFeedback(msg.meta!.trace_id!, feedback === 1 ? null : 1)}
                className={feedback === 1 ? "text-emerald-500" : "text-zinc-500 hover:text-emerald-400"}
                title={feedback === 1 ? "撤销评分" : "有用"}
              >
                <ThumbsUp className="size-3.5" />
              </button>
              <button
                type="button"
                onClick={() => onFeedback(msg.meta!.trace_id!, feedback === 0 ? null : 0)}
                className="text-zinc-500 hover:text-red-400"
                title={feedback === 0 ? "撤销评分" : "没用"}
              >
                <ThumbsDown className="size-3.5" />
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
