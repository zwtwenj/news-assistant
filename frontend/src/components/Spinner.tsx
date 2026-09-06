/** 全局加载指示（列表/卡片/弹窗均可复用）。 */
export default function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-zinc-400">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-500 dark:border-zinc-600 dark:border-t-zinc-300" />
      {label}
    </span>
  );
}
