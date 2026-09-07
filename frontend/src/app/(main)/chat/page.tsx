"use client";

/*
 * AI 助手聊天页：多会话（IndexedDB）+ SSE 流式渲染 + 引用溯源 + 工具结果展示
 * + 图片上传 + 语音输入（MediaRecorder→ASR）+ 回答语音播报（TTS）。
 */

import {
  ArrowUp,
  Image as ImageIcon,
  Loader2,
  MessageSquarePlus,
  Mic,
  Square,
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
  updateMessage,
} from "@/lib/chat-store";

type ToolEvent = { name: string; result: unknown };

const TOOL_LABELS: Record<string, string> = {
  list_today_news: "正在查询新闻库…",
  match_similar_tags: "正在匹配相关标签…",
  web_search_news: "正在联网搜索…",
  analyze_image: "正在分析图片…",
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

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setError("");
    setStreaming(true);
    setStreamText("");
    setToolEvents([]);
    setInput("");

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
              setToolEvents([...collectedTools]);
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
    <div className="flex h-[calc(100dvh-108px)] gap-4">
      {/* 会话侧栏 */}
      <aside
        className={`${sidebarOpen ? "flex" : "hidden"} absolute inset-y-0 left-0 z-20 w-64 flex-col border-r border-solid border-black/[.06] bg-white p-3 md:relative md:flex dark:border-white/[.12] dark:bg-black`}
      >
        <button
          type="button"
          onClick={() => void newConversation()}
          className="mb-3 flex items-center justify-center gap-2 rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background"
        >
          <MessageSquarePlus className="size-4" /> 新对话
        </button>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {convs.map((c) => (
            <div
              key={c.id}
              className={`group flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm ${
                c.id === activeId
                  ? "bg-black/[.06] font-medium text-black dark:bg-white/[.12] dark:text-zinc-50"
                  : "text-zinc-600 hover:bg-black/[.04] dark:text-zinc-400 dark:hover:bg-white/[.06]"
              }`}
              onClick={() => {
                setActiveId(c.id);
                setSidebarOpen(false);
              }}
            >
              <span className="truncate">{c.title}</span>
              <button
                type="button"
                className="hidden text-zinc-400 hover:text-red-500 group-hover:block"
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
          {!convs.length && <p className="px-2 py-4 text-xs text-zinc-400">还没有对话</p>}
        </div>
      </aside>

      {/* 主聊天区 */}
      <section className="flex min-w-0 flex-1 flex-col rounded-xl border border-solid border-black/[.06] bg-white dark:border-white/[.12] dark:bg-black">
        <header className="flex items-center gap-2 border-b border-solid border-black/[.06] px-4 py-3 dark:border-white/[.12]">
          <button
            type="button"
            className="rounded-md px-2 py-1 text-sm text-zinc-500 md:hidden"
            onClick={() => setSidebarOpen((v) => !v)}
          >
            ☰
          </button>
          <h1 className="text-sm font-semibold text-black dark:text-zinc-50">AI 助手 · 小讯</h1>
          <span className="text-xs text-zinc-400">基于新闻库回答 · 支持多轮追问</span>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {!messages.length && !streaming && (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-zinc-400">
              <p className="text-sm">问我任何新闻相关的问题</p>
              <p className="text-xs">「今天有什么新闻」「自然灾害相关报道」「还有吗」</p>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} msg={m} onSpeak={speak} speaking={speaking} />
          ))}
          {streaming && (
            <div className="flex justify-start">
              <div className="max-w-[85%] space-y-2">
                {toolEvents.map((t, i) => (
                  <p key={i} className="flex items-center gap-1.5 text-xs text-blue-500">
                    <Loader2 className="size-3 animate-spin" />
                    {TOOL_LABELS[t.name] ?? t.name}
                  </p>
                ))}
                {streamText ? (
                  <div className="whitespace-pre-wrap rounded-lg bg-black/[.04] px-3 py-2 text-sm leading-relaxed text-black dark:bg-white/[.08] dark:text-zinc-100">
                    {streamText}
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
        <footer className="border-t border-solid border-black/[.06] p-3 dark:border-white/[.12]">
          {pendingImage && (
            <div className="mb-2 flex items-center gap-2 text-xs text-zinc-500">
              {/* eslint-disable-next-line @next/next/no-img-element -- 用户上传预览 */}
              <img src={pendingImage.preview} alt="待发送" className="size-10 rounded object-cover" />
              <span>图片已就绪（5 分钟内有效）</span>
              <button type="button" onClick={() => setPendingImage(null)} className="text-zinc-400 hover:text-red-500">
                <X className="size-3.5" />
              </button>
            </div>
          )}
          {error && <p className="mb-2 text-xs text-red-500">{error}</p>}
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
              className="rounded-md p-2 text-zinc-400 hover:text-foreground"
              title="上传图片"
            >
              <ImageIcon className="size-5" />
            </button>
            <button
              type="button"
              onClick={() => void toggleRecord()}
              className={`rounded-md p-2 ${recording ? "text-red-500" : "text-zinc-400 hover:text-foreground"}`}
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
              className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-lg border border-solid border-black/[.1] bg-transparent px-3 py-2 text-sm outline-none focus:border-black dark:border-white/[.2] dark:focus:border-zinc-50"
            />
            <button
              type="button"
              disabled={!input.trim() || streaming}
              onClick={() => void send()}
              className="rounded-lg bg-foreground p-2.5 text-background disabled:opacity-40"
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
}: {
  msg: StoredMessage;
  onSpeak: (t: string) => void;
  speaking: boolean;
}) {
  const isUser = msg.role === "user";
  const newsResult = !isUser
    ? (msg.meta?.tool_calls ?? []).filter((t) => t.name === "list_today_news")
    : [];
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[85%] space-y-2 ${isUser ? "items-end" : "items-start"}`}>
        {msg.meta?.image_preview && (
          // eslint-disable-next-line @next/next/no-img-element -- 用户上传预览
          <img src={msg.meta.image_preview} alt="" className="max-h-40 rounded-lg object-cover" />
        )}
        {msg.content && (
          <div
            className={`whitespace-pre-wrap rounded-lg px-3 py-2 text-sm leading-relaxed ${
              isUser
                ? "bg-foreground text-background"
                : "bg-black/[.04] text-black dark:bg-white/[.08] dark:text-zinc-100"
            }`}
          >
            {msg.content}
          </div>
        )}
        {/* 今日新闻列表 */}
        {newsResult.map((t, i) => {
          const r = t.result as { items?: { title: string; url: string; source: string; publish_time: string }[]; page?: number; has_more?: boolean };
          return (
            <div key={i} className="space-y-1 rounded-lg border border-solid border-black/[.06] p-2 dark:border-white/[.12]">
              {(r.items ?? []).map((n, j) => (
                <a
                  key={j}
                  href={n.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block truncate text-xs text-blue-600 hover:underline dark:text-blue-400"
                >
                  · {n.title}
                  <span className="ml-1 text-zinc-400">
                    {n.source} {n.publish_time}
                  </span>
                </a>
              ))}
              {r.has_more && <p className="text-xs text-zinc-400">（第 {r.page} 页，还有更多，可说“还有吗”）</p>}
            </div>
          );
        })}
        {/* 引用来源 */}
        {!isUser && msg.meta?.rag_sources && msg.meta.rag_sources.length > 0 && (
          <details className="rounded-md bg-black/[.03] px-2 py-1 text-xs dark:bg-white/[.05]">
            <summary className="cursor-pointer text-zinc-400">引用来源（{msg.meta.rag_sources.length}）</summary>
            <div className="mt-1 space-y-1">
              {msg.meta.rag_sources.map((s, i) => (
                <a key={i} href={s.url} target="_blank" rel="noreferrer" className="block truncate text-blue-600 hover:underline dark:text-blue-400">
                  [{i + 1}] {s.title}
                </a>
              ))}
            </div>
          </details>
        )}
        {!isUser && msg.content.length > 4 && (
          <button
            type="button"
            disabled={speaking}
            onClick={() => void onSpeak(msg.content)}
            className="flex items-center gap-1 text-xs text-zinc-400 hover:text-foreground"
            title="语音播报"
          >
            <Volume2 className="size-3.5" /> 播报
          </button>
        )}
      </div>
    </div>
  );
}
