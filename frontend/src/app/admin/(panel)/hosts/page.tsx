"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminApiError, adminApi } from "@/lib/admin-api";

type Host = {
  id: number;
  name: string;
  voice_id: string;
  gender: string;
  persona: string;
  description: string | null;
  enabled: boolean;
  sort_order: number;
};

const EMPTY: Omit<Host, "id"> = {
  name: "",
  voice_id: "",
  gender: "custom",
  persona: "",
  description: "",
  enabled: true,
  sort_order: 0,
};

const GENDERS = [
  ["male", "男声"],
  ["female", "女声"],
  ["custom", "自定义/复刻"],
];

const inputCls =
  "w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-2 text-sm text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50";

export default function AdminHostsPage() {
  const [hosts, setHosts] = useState<Host[] | null>(null);
  const [editing, setEditing] = useState<Host | null>(null); // null=列表态
  const [form, setForm] = useState<Omit<Host, "id">>(EMPTY);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setHosts(await adminApi<Host[]>("/admin/hosts"));
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    // 内联异步（含 alive 守卫）：变更后由 save/remove/toggle 显式调 load 刷新
    let alive = true;
    adminApi<Host[]>("/admin/hosts")
      .then((d) => {
        if (alive) setHosts(d);
      })
      .catch((e) => {
        if (alive) setError(e instanceof AdminApiError ? e.message : "加载失败");
      });
    return () => {
      alive = false;
    };
  }, []);

  const openCreate = () => {
    setForm(EMPTY);
    setEditing({ ...EMPTY, id: 0 });
    setError("");
  };

  const openEdit = (h: Host) => {
    setForm({ ...h });
    setEditing(h);
    setError("");
  };

  const save = async () => {
    if (!editing || saving) return;
    setSaving(true);
    setError("");
    try {
      const body = JSON.stringify({ ...form, description: form.description || null });
      if (editing.id === 0) {
        await adminApi("/admin/hosts", { method: "POST", body });
      } else {
        await adminApi(`/admin/hosts/${editing.id}`, { method: "PUT", body });
      }
      setEditing(null);
      await load();
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (h: Host) => {
    if (!window.confirm(`确认删除主播「${h.name}」？历史播客不受影响。`)) return;
    await adminApi(`/admin/hosts/${h.id}`, { method: "DELETE" }).catch(() => {});
    await load();
  };

  const toggleEnabled = async (h: Host) => {
    await adminApi(`/admin/hosts/${h.id}`, {
      method: "PUT",
      body: JSON.stringify({ ...h, enabled: !h.enabled }),
    }).catch(() => {});
    await load();
  };

  if (editing) {
    const valid = form.name.trim() && form.voice_id.trim() && form.persona.trim();
    return (
      <div className="max-w-2xl space-y-5">
        <h1 className="text-xl font-semibold text-black dark:text-zinc-50">
          {editing.id === 0 ? "新增主播" : `编辑主播：${editing.name}`}
        </h1>

        <div className="space-y-4 rounded-xl border border-solid border-black/[.08] bg-white p-6 dark:border-white/[.145] dark:bg-black">
          <div className="grid grid-cols-2 gap-4">
            <label className="space-y-1">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">名称 *</span>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value.slice(0, 50) })}
                className={inputCls}
                placeholder="如：闻远"
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">voice_id *</span>
              <input
                value={form.voice_id}
                onChange={(e) => setForm({ ...form, voice_id: e.target.value.slice(0, 128) })}
                className={inputCls}
                placeholder="MiniMax 音色 ID（预置或复刻）"
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <label className="space-y-1">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">声音类型</span>
              <select
                value={form.gender}
                onChange={(e) => setForm({ ...form, gender: e.target.value })}
                className={inputCls}
              >
                {GENDERS.map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">排序（小在前）</span>
              <input
                type="number"
                min={0}
                max={9999}
                value={form.sort_order}
                onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) || 0 })}
                className={inputCls}
              />
            </label>
          </div>

          <label className="block space-y-1">
            <span className="text-sm text-zinc-600 dark:text-zinc-400">
              人设 / 脚本提示词 *（单人模式即播报风格，双人模式即角色人设）
            </span>
            <textarea
              rows={4}
              value={form.persona}
              onChange={(e) => setForm({ ...form, persona: e.target.value.slice(0, 2000) })}
              className={inputCls}
              placeholder="沉稳专业的新闻主播，语速适中……"
            />
            <span className="text-xs text-zinc-400">{form.persona.length}/2000</span>
          </label>

          <label className="block space-y-1">
            <span className="text-sm text-zinc-600 dark:text-zinc-400">简介（C 端选择卡展示）</span>
            <input
              value={form.description ?? ""}
              onChange={(e) => setForm({ ...form, description: e.target.value.slice(0, 200) })}
              className={inputCls}
              placeholder="如：沉稳播报男声"
            />
          </label>

          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            启用（C 端可见可选）
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex gap-3">
            <button
              type="button"
              disabled={!valid || saving}
              onClick={() => void save()}
              className="rounded-md bg-foreground px-5 py-2 text-sm font-medium text-background disabled:opacity-40"
            >
              {saving ? "保存中…" : "保存"}
            </button>
            <button
              type="button"
              onClick={() => setEditing(null)}
              className="rounded-md border border-solid border-black/[.08] px-5 py-2 text-sm dark:border-white/[.145]"
            >
              取消
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-black dark:text-zinc-50">主播管理</h1>
        <button
          type="button"
          onClick={openCreate}
          className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background"
        >
          + 新增主播
        </button>
      </div>

      {hosts === null ? (
        <p className="text-sm text-zinc-500">加载中…</p>
      ) : hosts.length === 0 ? (
        <p className="text-sm text-zinc-500">暂无主播，点击右上角新增</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-solid border-black/[.08] bg-white dark:border-white/[.145] dark:bg-black">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-solid border-black/[.06] text-left text-zinc-500 dark:border-white/[.12]">
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">voice_id</th>
                <th className="px-4 py-3">类型</th>
                <th className="px-4 py-3">人设摘要</th>
                <th className="px-4 py-3">排序</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((h) => (
                <tr
                  key={h.id}
                  className="border-b border-solid border-black/[.04] last:border-0 dark:border-white/[.08]"
                >
                  <td className="px-4 py-3 font-medium text-black dark:text-zinc-50">{h.name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-500">{h.voice_id}</td>
                  <td className="px-4 py-3 text-zinc-500">
                    {GENDERS.find(([v]) => v === h.gender)?.[1] ?? h.gender}
                  </td>
                  <td className="max-w-56 truncate px-4 py-3 text-zinc-500" title={h.persona}>
                    {h.persona}
                  </td>
                  <td className="px-4 py-3 text-zinc-500">{h.sort_order}</td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => void toggleEnabled(h)}
                      className={
                        h.enabled
                          ? "rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700 dark:bg-green-900/40 dark:text-green-400"
                          : "rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                      }
                    >
                      {h.enabled ? "启用" : "停用"}
                    </button>
                  </td>
                  <td className="space-x-3 px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => openEdit(h)}
                      className="text-zinc-600 hover:text-black dark:text-zinc-400 dark:hover:text-zinc-50"
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => void remove(h)}
                      className="text-red-600 hover:text-red-700"
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
