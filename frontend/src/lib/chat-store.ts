"use client";

/*
 * 聊天会话 IndexedDB 存储（news-chat-db）：
 * - conversations：会话（id/title/created_at/updated_at）
 * - messages：消息（id/conv_id/role/content/meta[引用来源|工具调用|图片]/created_at）
 * 容量守卫：单会话超 500 条截断旧消息。
 */

const DB_NAME = "news-chat-db";
const DB_VERSION = 1;
const MAX_MESSAGES = 500;

export type ChatRole = "user" | "assistant";

export type MessageMeta = {
  rag_sources?: { title: string; url: string; score?: number }[];
  memories?: string[];
  used_query?: string;
  tool_calls?: { name: string; result: unknown }[];
  image_id?: string;
  image_preview?: string; // dataURL 预览
  error?: string;
  trace_id?: string; // Langfuse trace：👍/👎 评分挂载点
  feedback?: 0 | 1; // 用户已提交的评分
};

export type StoredMessage = {
  id: string;
  conv_id: string;
  role: ChatRole;
  content: string;
  meta?: MessageMeta;
  created_at: number;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
};

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("conversations")) {
        db.createObjectStore("conversations", { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains("messages")) {
        const ms = db.createObjectStore("messages", { keyPath: "id" });
        ms.createIndex("conv_time", ["conv_id", "created_at"]);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDB().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(store, mode);
        const req = fn(t.objectStore(store));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      })
  );
}

const uid = () =>
  (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`);

export async function listConversations(): Promise<Conversation[]> {
  const all = await tx<Conversation[]>("conversations", "readonly", (s) => s.getAll());
  return all.sort((a, b) => b.updated_at - a.updated_at);
}

export async function createConversation(title = "新对话"): Promise<Conversation> {
  const conv: Conversation = {
    id: uid(),
    title,
    created_at: Date.now(),
    updated_at: Date.now(),
  };
  await tx("conversations", "readwrite", (s) => s.put(conv));
  return conv;
}

export async function deleteConversation(convId: string): Promise<void> {
  await tx("conversations", "readwrite", (s) => s.delete(convId));
  const db = await openDB();
  await new Promise<void>((resolve, reject) => {
    const t = db.transaction("messages", "readwrite");
    const idx = t.objectStore("messages").index("conv_time");
    const range = IDBKeyRange.bound([convId, 0], [convId, Infinity]);
    const req = idx.openCursor(range);
    req.onsuccess = () => {
      const cursor = req.result;
      if (cursor) {
        cursor.delete();
        cursor.continue();
      }
    };
    t.oncomplete = () => resolve();
    t.onerror = () => reject(t.error);
  });
}

export async function renameConversation(convId: string, title: string): Promise<void> {
  const conv = await tx<Conversation | undefined>("conversations", "readonly", (s) => s.get(convId));
  if (conv) {
    conv.title = title;
    await tx("conversations", "readwrite", (s) => s.put(conv));
  }
}

export async function addMessage(
  convId: string,
  role: ChatRole,
  content: string,
  meta?: MessageMeta
): Promise<StoredMessage> {
  const msg: StoredMessage = {
    id: uid(),
    conv_id: convId,
    role,
    content,
    meta,
    created_at: Date.now(),
  };
  await tx("messages", "readwrite", (s) => s.put(msg));
  await touchConversation(convId, content);
  trimConversation(convId);
  return msg;
}

export async function updateMessage(msg: StoredMessage): Promise<void> {
  await tx("messages", "readwrite", (s) => s.put(msg));
  await touchConversation(msg.conv_id);
}

async function touchConversation(convId: string, firstUserContent?: string) {
  const conv = await tx<Conversation | undefined>("conversations", "readonly", (s) => s.get(convId));
  if (!conv) return;
  conv.updated_at = Date.now();
  if (firstUserContent && conv.title === "新对话" && firstUserContent.trim()) {
    conv.title = firstUserContent.trim().slice(0, 24);
  }
  await tx("conversations", "readwrite", (s) => s.put(conv));
}

export async function listMessages(convId: string): Promise<StoredMessage[]> {
  const db = await openDB();
  const msgs = await new Promise<StoredMessage[]>((resolve, reject) => {
    const t = db.transaction("messages", "readonly");
    const idx = t.objectStore("messages").index("conv_time");
    const range = IDBKeyRange.bound([convId, 0], [convId, Infinity]);
    const req = idx.getAll(range);
    req.onsuccess = () => resolve(req.result as StoredMessage[]);
    req.onerror = () => reject(req.error);
  });
  return msgs.sort((a, b) => a.created_at - b.created_at);
}

async function trimConversation(convId: string) {
  const msgs = await listMessages(convId);
  if (msgs.length <= MAX_MESSAGES) return;
  const doomed = msgs.slice(0, msgs.length - MAX_MESSAGES);
  const db = await openDB();
  const t = db.transaction("messages", "readwrite");
  const store = t.objectStore("messages");
  for (const m of doomed) store.delete(m.id);
}
