"use client";

import { useEffect, useState } from "react";

type HealthStatus = {
  name: string;
  ok: boolean;
  detail: string;
};

export default function Home() {
  const [statuses, setStatuses] = useState<HealthStatus[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const check = async () => {
      const results: HealthStatus[] = [];
      try {
        const resp = await fetch("/api/v1/healthz");
        results.push({
          name: "后端 API",
          ok: resp.ok,
          detail: resp.ok ? "运行中" : `HTTP ${resp.status}`,
        });
      } catch {
        results.push({ name: "后端 API", ok: false, detail: "无法连接" });
      }
      try {
        const resp = await fetch("/api/v1/readyz");
        const body = (await resp.json()) as { status: string; checks: Record<string, string> };
        results.push({
          name: "依赖服务",
          ok: body.status === "ok",
          detail: Object.entries(body.checks)
            .map(([k, v]) => `${k}: ${v}`)
            .join(" / "),
        });
      } catch {
        results.push({ name: "依赖服务", ok: false, detail: "无法连接" });
      }
      setStatuses(results);
      setLoading(false);
    };
    check();
  }, []);

  return (
    <div className="flex flex-col flex-1 items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex w-full max-w-3xl flex-col items-center justify-center gap-8 py-32 px-16">
        <div className="flex flex-col items-center gap-6 text-center">
          <h1 className="text-3xl font-semibold leading-10 tracking-tight text-black dark:text-zinc-50">
            新闻助手
          </h1>
          <p className="max-w-md text-lg leading-8 text-zinc-600 dark:text-zinc-400">
            脚手架状态面板：验证前后端链路连通
          </p>
        </div>

        <div className="w-full max-w-md space-y-3">
          {loading && <p className="text-center text-sm text-zinc-400">检查中…</p>}
          {!loading &&
            statuses.map((s) => (
              <div
                key={s.name}
                className="flex items-center justify-between rounded-lg border border-solid border-black/[.08] bg-white px-4 py-3 dark:border-white/[.145] dark:bg-black"
              >
                <span className="font-medium text-black dark:text-zinc-50">{s.name}</span>
                <span className={s.ok ? "text-green-600" : "text-red-600"}>
                  {s.ok ? "✓ " : "✗ "}
                  {s.detail}
                </span>
              </div>
            ))}
        </div>
      </main>
    </div>
  );
}
