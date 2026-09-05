"use client";

import { useEffect, useState } from "react";

import { adminApi } from "@/lib/admin-api";

type Me = { id: number; username: string; display_name: string | null };

export default function AdminDashboardPage() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    adminApi<Me>("/admin/auth/me").then(setMe).catch(() => {});
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-black dark:text-zinc-50">仪表盘</h1>
        <p className="mt-1 text-sm text-zinc-500">
          {me ? `欢迎，${me.display_name || me.username}` : "…"}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-solid border-black/[.08] bg-white p-5 dark:border-white/[.145] dark:bg-black">
          <p className="text-sm text-zinc-500">主播管理</p>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
            配置主播人设与音色，C 端播客生成页可选择
          </p>
        </div>
        <div className="rounded-xl border border-solid border-black/[.08] bg-white p-5 opacity-60 dark:border-white/[.145] dark:bg-black">
          <p className="text-sm text-zinc-500">新闻管理（A2）</p>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">列表 / 删除（含 Milvus）/ 恢复</p>
        </div>
        <div className="rounded-xl border border-solid border-black/[.08] bg-white p-5 opacity-60 dark:border-white/[.145] dark:bg-black">
          <p className="text-sm text-zinc-500">手动添加新闻（A2）</p>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
            表单录入 → 自动分析 → 向量入库
          </p>
        </div>
      </div>
    </div>
  );
}
