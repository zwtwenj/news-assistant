"use client";

import { useEffect, useState } from "react";

import { AdminApiError, adminApi } from "@/lib/admin-api";

type Account = {
  id: number;
  username: string;
  display_name: string | null;
  status: string;
  last_login_at: string | null;
  created_at: string;
};

const inputCls =
  "w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-2 text-sm text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50";

export default function AdminAccountsPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [me, setMe] = useState<{ id: number } | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ username: "", password: "", display_name: "" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    adminApi<Account[]>("/admin/users").then((d) => alive && setAccounts(d)).catch(() => {});
    adminApi<{ id: number }>("/admin/auth/me").then((d) => alive && setMe(d)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const reload = async () => {
    try {
      setAccounts(await adminApi<Account[]>("/admin/users"));
    } catch {
      // 401 已由 adminApi 跳登录处理
    }
  };

  const create = async () => {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      await adminApi("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          username: form.username.trim(),
          password: form.password,
          display_name: form.display_name.trim() || null,
        }),
      });
      setCreating(false);
      setForm({ username: "", password: "", display_name: "" });
      await reload();
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "创建失败");
    } finally {
      setSaving(false);
    }
  };

  const resetPassword = async (a: Account) => {
    const pw = window.prompt(`为「${a.username}」设置新密码（至少 8 位）：`, "");
    if (!pw) return;
    try {
      await adminApi(`/admin/users/${a.id}`, { method: "PUT", body: JSON.stringify({ password: pw }) });
      window.alert("密码已重置");
    } catch (e) {
      window.alert(e instanceof AdminApiError ? e.message : "重置失败");
    }
  };

  const toggleStatus = async (a: Account) => {
    const next = a.status === "active" ? "banned" : "active";
    if (!window.confirm(`确认${next === "banned" ? "停用" : "启用"}账号「${a.username}」？`)) return;
    try {
      await adminApi(`/admin/users/${a.id}`, { method: "PUT", body: JSON.stringify({ status: next }) });
      await reload();
    } catch (e) {
      window.alert(e instanceof AdminApiError ? e.message : "操作失败");
    }
  };

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-black dark:text-zinc-50">账号管理</h1>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background"
        >
          + 新增管理员
        </button>
      </div>

      {creating && (
        <div className="space-y-4 rounded-xl border border-solid border-black/[.08] bg-white p-6 dark:border-white/[.145] dark:bg-black">
          <div className="grid grid-cols-2 gap-4">
            <label className="space-y-1">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">用户名 *</span>
              <input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value.slice(0, 50) })}
                className={inputCls}
                placeholder="登录用户名"
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">展示名</span>
              <input
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value.slice(0, 50) })}
                className={inputCls}
                placeholder="如：运营小王"
              />
            </label>
          </div>
          <label className="block space-y-1">
            <span className="text-sm text-zinc-600 dark:text-zinc-400">密码 *（至少 8 位）</span>
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value.slice(0, 128) })}
              className={inputCls}
              placeholder="初始密码"
            />
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3">
            <button
              type="button"
              disabled={!form.username.trim() || form.password.length < 8 || saving}
              onClick={() => void create()}
              className="rounded-md bg-foreground px-5 py-2 text-sm font-medium text-background disabled:opacity-40"
            >
              {saving ? "创建中…" : "创建"}
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="rounded-md border border-solid border-black/[.08] px-5 py-2 text-sm dark:border-white/[.145]"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {accounts === null ? (
        <p className="text-sm text-zinc-500">加载中…</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-solid border-black/[.08] bg-white dark:border-white/[.145] dark:bg-black">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-solid border-black/[.06] text-left text-zinc-500 dark:border-white/[.12]">
                <th className="px-4 py-3">用户名</th>
                <th className="px-4 py-3">展示名</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">最近登录</th>
                <th className="px-4 py-3">创建时间</th>
                <th className="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr
                  key={a.id}
                  className="border-b border-solid border-black/[.04] last:border-0 dark:border-white/[.08]"
                >
                  <td className="px-4 py-3 font-medium text-black dark:text-zinc-50">
                    {a.username}
                    {me?.id === a.id && <span className="ml-2 text-xs text-zinc-400">（当前登录）</span>}
                  </td>
                  <td className="px-4 py-3 text-zinc-500">{a.display_name ?? "-"}</td>
                  <td className="px-4 py-3">
                    <span
                      className={
                        a.status === "active"
                          ? "rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700 dark:bg-green-900/40 dark:text-green-400"
                          : "rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                      }
                    >
                      {a.status === "active" ? "启用" : "停用"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-zinc-500">
                    {a.last_login_at ? a.last_login_at.slice(0, 19).replace("T", " ") : "-"}
                  </td>
                  <td className="px-4 py-3 text-zinc-500">
                    {a.created_at.slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="space-x-3 px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => void resetPassword(a)}
                      className="text-zinc-600 hover:text-black dark:text-zinc-400 dark:hover:text-zinc-50"
                    >
                      重置密码
                    </button>
                    {me?.id !== a.id && (
                      <button
                        type="button"
                        onClick={() => void toggleStatus(a)}
                        className={
                          a.status === "active"
                            ? "text-red-600 hover:text-red-700"
                            : "text-green-600 hover:text-green-700"
                        }
                      >
                        {a.status === "active" ? "停用" : "启用"}
                      </button>
                    )}
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
