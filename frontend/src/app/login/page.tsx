"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import GithubIcon from "@/components/GithubIcon";
import Spinner from "@/components/Spinner";
import { Mic, Newspaper, Rss } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/providers/auth";

type Captcha = { captcha_id: string; image_base64: string };

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center">
          <Spinner />
        </main>
      }
    >
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading, reload } = useAuth();

  const [phone, setPhone] = useState("");
  const [captcha, setCaptcha] = useState<Captcha | null>(null);
  const [captchaCode, setCaptchaCode] = useState("");
  const [smsCode, setSmsCode] = useState("");
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const [remember, setRemember] = useState(false); // 七天内免登录（7 天档会话）
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  // 实时热点：最新入库新闻标题（公开接口），加载失败降级为静态特性文案
  const [ticker, setTicker] = useState<string[]>([]);

  useEffect(() => {
    const t = setTimeout(() => {
      api<{ items: string[] }>("/news/ticker")
        .then((d) => setTicker(d.items))
        .catch(() => {});
    }, 0);
    return () => clearTimeout(t);
  }, []);

  // 已登录用户不该停留在登录页：状态管理器检测到会话直接回首页
  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [user, loading, router]);

  const fetchCaptcha = useCallback(async () => {
    setCaptchaCode("");
    setCaptcha(await api<Captcha>("/auth/captcha"));
  }, []);

  useEffect(() => {
    const captchaTimer = setTimeout(() => void fetchCaptcha(), 0); // StrictMode 双挂载只取一次
    return () => clearTimeout(captchaTimer);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [fetchCaptcha]);

  useEffect(() => {
    if (countdown <= 0 && timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, [countdown]);

  const phoneValid = /^1[3-9]\d{9}$/.test(phone);

  const handleSend = async () => {
    if (!phoneValid || !captcha || !captchaCode || sending) return;
    setSending(true);
    setError("");
    try {
      await api("/auth/sms/send", {
        method: "POST",
        body: JSON.stringify({
          phone,
          captcha_id: captcha.captcha_id,
          captcha_code: captchaCode,
        }),
      });
      setCountdown(60);
      timer.current = setInterval(() => setCountdown((c) => c - 1), 1000);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "发送失败，请重试";
      setError(msg);
      // 图形验证码错误/过期：自动刷新
      if (e instanceof ApiError && e.status === 401) void fetchCaptcha();
    } finally {
      setSending(false);
    }
  };

  const handleLogin = async () => {
    if (!phoneValid || !/^\d{6}$/.test(smsCode)) return;
    setError("");
    try {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ phone, code: smsCode, remember }),
      });
      await reload();
      // 登录后回跳原页面（守卫跳转时携带 ?next=）
      const next = searchParams.get("next");
      router.push(next && next.startsWith("/") ? next : "/");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "登录失败，请重试");
    }
  };

  // GitHub OAuth：后端生成授权 URL（state 存 Redis 携带 next+remember），整页跳转
  const [ghLoading, setGhLoading] = useState(false);

  // 浏览器后退（bfcache 恢复）时 React 状态原样冻结：ghLoading 停在 true，
  // 按钮永久转圈。pageshow 在每次回到页面时触发，统一复位
  useEffect(() => {
    const onShow = () => setGhLoading(false);
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  const handleGithub = async () => {
    if (ghLoading) return;
    setGhLoading(true);
    setError("");
    try {
      const next = searchParams.get("next") ?? "/";
      const { url } = await api<{ url: string }>(
        `/auth/github/login?next=${encodeURIComponent(next.startsWith("/") ? next : "/")}&remember=${remember}`
      );
      window.location.href = url;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "GitHub 登录暂不可用");
      setGhLoading(false);
    }
  };

  // 加载中或已登录（即将跳转）时不渲染表单
  if (loading || user) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <Spinner />
      </main>
    );
  }

  const inputCls =
    "h-11 w-full rounded-lg border border-solid border-input bg-black/35 px-3.5 text-[15px] text-foreground outline-none transition-colors placeholder:text-zinc-600 focus:border-primary focus:ring-[3px] focus:ring-primary/15";

  return (
    <main className="flex flex-1">
      {/* 左：品牌价值区（窄屏隐藏） */}
      <section className="relative hidden flex-1 flex-col overflow-hidden lg:flex">
        <div className="flex flex-1 flex-col justify-center px-14 py-12">
          <h1 className="max-w-xl text-4xl font-bold leading-snug tracking-wide">
            每天 300 条新闻，
            <br />
            编译成
            <span className="bg-gradient-to-r from-primary to-[#a78bfa] bg-clip-text text-transparent">
              {" "}10 分钟播客
            </span>
            。
          </h1>
          <p className="mt-4 max-w-lg text-sm leading-8 text-muted-foreground">
            多源 RSS 聚合 → 语义去重 → 主播级 TTS 合成，
            <code className="rounded border border-primary/20 bg-primary/[.08] px-1.5 py-0.5 text-[13px] text-primary">
              全自动
            </code>
            。通勤路上用耳朵完成今天的
            <code className="ml-1 rounded border border-primary/20 bg-primary/[.08] px-1.5 py-0.5 text-[13px] text-primary">
              每日简报
            </code>
            。
          </p>

          {/* 特性三点 */}
          <div className="mt-12 flex max-w-lg flex-col gap-5">
            {(
              [
                {
                  icon: Newspaper,
                  title: "智能选稿",
                  desc: "多源新闻聚合，按你的口味自动筛选",
                },
                {
                  icon: Mic,
                  title: "双人对谈",
                  desc: "单人独白或双主播对谈，像听节目一样听新闻",
                },
                {
                  icon: Rss,
                  title: "RSS 分发",
                  desc: "生成的播客直接订阅到小宇宙、Apple Podcasts",
                },
              ] as const
            ).map((p) => (
              <div key={p.title} className="flex items-center gap-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-primary">
                  <p.icon className="size-4.5" />
                </span>
                <span>
                  <b className="block text-[15px] font-semibold text-foreground">{p.title}</b>
                  <span className="mt-0.5 block text-[13px] text-muted-foreground">{p.desc}</span>
                </span>
              </div>
            ))}
          </div>

          {/* 频谱装饰 */}
          <div className="mt-12 flex h-24 max-w-lg items-end gap-1">
            {[22, 46, 30, 68, 44, 82, 58, 92, 36, 64, 24, 76, 52, 88, 40, 30, 60, 96, 50, 70, 34, 48, 66, 26].map(
              (h, i) => (
                <i
                  key={i}
                  style={{ height: `${h}%` }}
                  className={
                    i % 4 === 2
                      ? "w-full rounded-t-sm bg-zinc-600/40"
                      : i % 4 === 1
                        ? "w-full rounded-t-sm bg-gradient-to-b from-[#a78bfa] to-transparent opacity-80 shadow-[0_0_10px_rgba(167,139,250,.3)]"
                        : "w-full rounded-t-sm bg-gradient-to-b from-primary to-transparent opacity-80 shadow-[0_0_10px_rgba(34,211,238,.3)]"
                  }
                />
              ),
            )}
          </div>
        </div>

        {/* 底部 ticker：真实入库标题跑马灯（内容重复两份实现无缝滚动） */}
        <div className="mx-14 mb-12 flex h-11 items-center overflow-hidden rounded-xl border border-solid border-border bg-white/[.04]">
          <span className="flex h-full shrink-0 items-center border-r border-solid border-border bg-primary/[.06] px-4 text-xs font-semibold tracking-[0.2em] text-primary">
            实时热点
          </span>
          {ticker.length > 0 ? (
            <span className="ticker-track">
              {[0, 1].map((copy) => (
                <span key={copy} className="flex items-center whitespace-nowrap pl-4 text-xs text-muted-foreground">
                  {ticker.map((title, i) => (
                    <span key={i} className="flex items-center">
                      {title}
                      <span className="mx-4 text-primary/60">/</span>
                    </span>
                  ))}
                </span>
              ))}
            </span>
          ) : (
            <span className="whitespace-nowrap pl-4 text-xs text-muted-foreground">
              多源聚合 / 语义去重 / 主播级合成 / RSS 全网分发
            </span>
          )}
        </div>
      </section>

      {/* 右：登录表单 */}
      <section className="flex flex-1 items-center justify-center px-6 lg:max-w-[45%]">
        <div className="relative w-full max-w-[420px] rounded-2xl border border-solid border-white/10 bg-[#121216]/80 p-9 shadow-2xl backdrop-blur-xl">
          <span className="absolute top-3 left-4 font-mono text-[10px] tracking-widest text-muted-foreground/70">
            AUTH://SESSION
          </span>

          <h2 className="text-2xl font-bold">登录 / 注册</h2>
          <p className="mb-7 mt-1.5 text-[13px] text-muted-foreground">
            未注册的手机号将自动创建账号
          </p>

          <div className="mb-4">
            <label className="mb-2 block text-[13px] font-medium text-zinc-400">手机号</label>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 11))}
              placeholder="请输入手机号"
              inputMode="numeric"
              className={inputCls}
            />
          </div>

          <div className="mb-4">
            <label className="mb-2 block text-[13px] font-medium text-zinc-400">图形验证码</label>
            <div className="flex gap-2">
              <input
                value={captchaCode}
                onChange={(e) => setCaptchaCode(e.target.value.toUpperCase().slice(0, 4))}
                placeholder="输入右侧字符"
                className={inputCls}
              />
              {captcha ? (
                // eslint-disable-next-line @next/next/no-img-element -- base64 动态图，非静态资源
                <img
                  src={captcha.image_base64}
                  alt="图形验证码，点击刷新"
                  onClick={() => void fetchCaptcha()}
                  className="h-11 w-28 cursor-pointer rounded-lg border border-solid border-input"
                />
              ) : (
                <div className="h-11 w-28 animate-pulse rounded-lg bg-muted" />
              )}
            </div>
          </div>

          <div className="mb-4">
            <label className="mb-2 block text-[13px] font-medium text-zinc-400">短信验证码</label>
            <div className="relative">
              <input
                value={smsCode}
                onChange={(e) => setSmsCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="6 位数字"
                inputMode="numeric"
                className={inputCls}
              />
              <button
                type="button"
                disabled={!phoneValid || !captchaCode || countdown > 0 || sending}
                onClick={() => void handleSend()}
                className="absolute top-1/2 right-1.5 h-8 -translate-y-1/2 rounded-md bg-primary/[.12] px-3 text-xs font-semibold text-primary transition-colors hover:bg-primary/20 disabled:bg-white/[.06] disabled:text-muted-foreground"
              >
                {countdown > 0 ? `${countdown}s` : sending ? "发送中…" : "获取验证码"}
              </button>
            </div>
          </div>

          {error && (
            <div className="mb-4 rounded-lg border border-solid border-destructive/35 bg-destructive/10 px-3 py-2.5 text-[13px] text-red-300">
              {error}
            </div>
          )}

          <button
            type="button"
            disabled={!phoneValid || !/^\d{6}$/.test(smsCode)}
            onClick={() => void handleLogin()}
            className="h-11.5 w-full rounded-lg bg-gradient-to-r from-primary to-[#67e8f9] text-[15px] font-bold tracking-[0.3em] text-[#001318] shadow-[0_0_24px_rgba(34,211,238,.3)] transition-shadow hover:shadow-[0_0_34px_rgba(34,211,238,.5)] disabled:opacity-40 disabled:shadow-none"
          >
            登 录
          </button>

          <label className="mt-4 flex cursor-pointer items-center gap-2 text-[13px] text-muted-foreground">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="size-4 accent-primary"
            />
            七天内免登录
          </label>

          <div className="my-6 flex items-center gap-3 text-xs text-zinc-600">
            <span className="h-px flex-1 bg-white/10" />
            或
            <span className="h-px flex-1 bg-white/10" />
          </div>

          <button
            type="button"
            disabled={ghLoading}
            onClick={() => void handleGithub()}
            className="flex h-11 w-full items-center justify-center gap-2.5 rounded-lg border border-solid border-white/15 bg-white/[.04] text-sm font-medium transition-all hover:border-[#a78bfa]/50 hover:shadow-[0_0_18px_rgba(167,139,250,.15)] disabled:opacity-40"
          >
            {ghLoading ? (
              <Spinner className="size-4" />
            ) : (
              <GithubIcon className="size-4" />
            )}
            使用 GitHub 登录
          </button>
        </div>
      </section>
    </main>
  );
}
