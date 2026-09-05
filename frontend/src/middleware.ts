import { NextResponse, type NextRequest } from "next/server";

import { PROTECTED_PREFIXES } from "@/lib/auth-guard";

// UX 级路由守卫（第一道）：无 access_token cookie 直接跳登录页。
// cookie 存在但过期的情况由客户端处理：api() 静默 refresh → 仍失败则
// AuthProvider 跳转（见 providers/auth.tsx）。真正的鉴权永远在后端。
// （后管为独立项目 news-admin，本应用不含 /admin 路由）
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`)
  );
  if (isProtected && !request.cookies.has("access_token")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // 注意：matcher 必须是静态字面量（Next 编译期解析），
  // 新增受保护前缀时同步更新 lib/auth-guard.ts 与此处
  matcher: ["/account/:path*", "/news/:path*", "/podcasts/:path*"],
};
