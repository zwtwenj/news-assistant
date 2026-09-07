"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import GithubIcon from "@/components/GithubIcon";
import Spinner from "@/components/Spinner";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/providers/auth";

type Captcha = { captcha_id: string; image_base64: string };

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-black">
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
      <main className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-black">
        <Spinner />
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-zinc-50 px-4 dark:bg-black">
      <div className="w-full max-w-sm space-y-5 rounded-xl border border-solid border-black/[.08] bg-white p-8 dark:border-white/[.145] dark:bg-black">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-black dark:text-zinc-50">登录 / 注册</h1>
          <p className="mt-1 text-sm text-zinc-500">未注册的手机号将自动创建账号</p>
        </div>

        <label className="block space-y-1">
          <span className="text-sm text-zinc-600 dark:text-zinc-400">手机号</span>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 11))}
            placeholder="请输入手机号"
            inputMode="numeric"
            className="w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-2 text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50"
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm text-zinc-600 dark:text-zinc-400">图形验证码</span>
          <div className="flex gap-2">
            <input
              value={captchaCode}
              onChange={(e) => setCaptchaCode(e.target.value.toUpperCase().slice(0, 4))}
              placeholder="输入右侧字符"
              className="w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-2 text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50"
            />
            {captcha ? (
              // eslint-disable-next-line @next/next/no-img-element -- base64 动态图，非静态资源
              <img
                src={captcha.image_base64}
                alt="图形验证码，点击刷新"
                onClick={() => void fetchCaptcha()}
                className="h-10 cursor-pointer rounded-md"
              />
            ) : (
              <div className="h-10 w-32 animate-pulse rounded-md bg-zinc-200 dark:bg-zinc-800" />
            )}
          </div>
        </label>

        <label className="block space-y-1">
          <span className="text-sm text-zinc-600 dark:text-zinc-400">短信验证码</span>
          <div className="flex gap-2">
            <input
              value={smsCode}
              onChange={(e) => setSmsCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="6 位数字"
              inputMode="numeric"
              className="w-full rounded-md border border-solid border-black/[.1] bg-transparent px-3 py-2 text-black outline-none focus:border-black dark:border-white/[.2] dark:text-zinc-50 dark:focus:border-zinc-50"
            />
            <button
              type="button"
              disabled={!phoneValid || !captchaCode || countdown > 0 || sending}
              onClick={() => void handleSend()}
              className="w-28 shrink-0 rounded-md border border-solid border-black/[.08] text-sm disabled:opacity-40 dark:border-white/[.145]"
            >
              {countdown > 0 ? `${countdown}s` : sending ? "发送中…" : "获取验证码"}
            </button>
          </div>
        </label>

        {error && <p className="text-center text-sm text-red-600">{error}</p>}

        <button
          type="button"
          disabled={!phoneValid || !/^\d{6}$/.test(smsCode)}
          onClick={() => void handleLogin()}
          className="w-full rounded-md bg-foreground py-2.5 font-medium text-background disabled:opacity-40"
        >
          登录
        </button>

        <label className="flex cursor-pointer items-center justify-center gap-1.5 text-sm text-zinc-600 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            className="h-4 w-4 accent-foreground"
          />
          七天内免登录
        </label>

        <div className="flex items-center gap-3 text-xs text-zinc-400">
          <span className="h-px flex-1 bg-black/[.08] dark:bg-white/[.12]" />
          或
          <span className="h-px flex-1 bg-black/[.08] dark:bg-white/[.12]" />
        </div>
        <button
          type="button"
          disabled={ghLoading}
          onClick={() => void handleGithub()}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-solid border-black/[.1] py-2.5 text-sm font-medium text-black hover:border-black/40 disabled:opacity-40 dark:border-white/[.2] dark:text-zinc-50 dark:hover:border-white/40"
        >
          {ghLoading ? (
            <Spinner className="size-4 border-zinc-300 border-t-zinc-500" />
          ) : (
            <GithubIcon className="size-4" />
          )}
          使用 GitHub 登录
        </button>
      </div>
    </main>
  );
}
