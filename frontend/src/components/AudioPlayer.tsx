"use client";

/*
 * 波形播放器（wavesurfer.js v7）：播客列表用。
 * - 懒加载：首次点播放才创建实例并加载音频（列表几十条不批量下载）
 * - 全局单实例：module 级注册表，播放新的自动暂停旧的
 * - 暗色：创建时按当前主题读一次 CSS 变量（主题切换后下次播放生效，可接受）
 */

import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";

import Spinner from "@/components/Spinner";
import { cn } from "@/lib/utils";

let activePause: (() => void) | null = null;

const fmt = (sec: number) => {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const cssVar = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

export function AudioPlayer({ src, className }: { src: string; className?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [created, setCreated] = useState(false);
  const [duration, setDuration] = useState(0);
  const [current, setCurrent] = useState(0);

  useEffect(
    () => () => {
      wsRef.current?.destroy();
      wsRef.current = null;
    },
    []
  );

  const toggle = () => {
    const ws = wsRef.current;
    if (!ws) {
      setLoading(true);
      const instance = WaveSurfer.create({
        container: containerRef.current!,
        height: 36,
        waveColor: cssVar("--border", "#d4d4d8"),
        progressColor: cssVar("--primary", "#18181b"),
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        cursorWidth: 0,
        url: src,
      });
      wsRef.current = instance;
      activePause?.();
      activePause = () => instance.pause();
      instance.on("ready", () => {
        setCreated(true);
        setDuration(instance.getDuration());
        setLoading(false);
        void instance.play();
      });
      instance.on("play", () => setPlaying(true));
      instance.on("pause", () => setPlaying(false));
      instance.on("finish", () => setPlaying(false));
      instance.on("timeupdate", (t: number) => setCurrent(t));
      instance.on("error", () => {
        setLoading(false);
        setPlaying(false);
      });
      return;
    }
    if (playing) ws.pause();
    else void ws.play();
  };

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <button
        type="button"
        aria-label={playing ? "暂停" : "播放"}
        onClick={toggle}
        className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform hover:scale-105 active:scale-95"
      >
        {loading ? (
          <Spinner className="border-primary/30 border-t-primary-foreground size-4" />
        ) : playing ? (
          <Pause className="size-4 fill-current" />
        ) : (
          <Play className="size-4 translate-x-px fill-current" />
        )}
      </button>
      {/* 未创建实例前的波形占位（懒加载：点播放才拉音频） */}
      <div
        ref={containerRef}
        className="h-9 min-w-0 flex-1 [&:empty]:rounded-md [&:empty]:bg-gradient-to-r [&:empty]:from-muted [&:empty]:via-muted/40 [&:empty]:to-muted"
      />
      <span className="w-20 shrink-0 text-right font-mono text-xs whitespace-nowrap tabular-nums text-muted-foreground">
        {created ? `${fmt(current)} / ${fmt(duration)}` : fmt(0)}
      </span>
    </div>
  );
}
