/** 全局加载指示：霓虹频谱条（5 根错峰跳动），呼应播客音频的产品意象。

用法：<Spinner />（纯图标）/ <Spinner label="思考中…" />（带状态文字）
className 附加到外层容器（控制间距）；条体固定小尺寸，按钮内嵌也可用。
 */
export default function Spinner({
  label,
  className = "",
}: {
  label?: string;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 text-sm text-zinc-400 ${className}`}>
      <span className="inline-flex h-4 items-end gap-[3px]">
        {[0, 1, 2, 3, 4].map((i) => (
          <i
            key={i}
            className="loader-bar w-[3px] rounded-sm bg-primary shadow-[0_0_6px_rgba(34,211,238,.5)]"
            style={{ animationDelay: `${i * 0.12}s` }}
          />
        ))}
      </span>
      {label && (
        <span className="font-mono text-xs tracking-wide">
          {label}
          <span className="animate-pulse text-primary">_</span>
        </span>
      )}
    </span>
  );
}
