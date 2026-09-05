import { NextResponse, type NextRequest } from "next/server";

import { PROTECTED_PREFIXES } from "@/lib/auth-guard";

// C 端 UX 级路由守卫（第一道）：无 access_token cookie 直接跳登录页。
// cookie 存在但过期的情况由客户端处理：api() 静默 refresh → 仍失败则
// AuthProvider 跳转（见 providers/auth.tsx）。真正的鉴权永远在后端。
//
// 后管（/admin）：检查独立 admin_token cookie；登录页本身放行。
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname === "/admin" || pathname.startsWith("/admin/")) {
    if (pathname !== "/admin/login" && !request.cookies.has("admin_token")) {
      const url = new URL("/admin/login", request.url);
      url.searchParams.set("next", request.nextUrl.pathname);
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

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
  matcher: ["/account/:path*", "/news/:path*", "/podcasts/:path*", "/admin/:path*"],
};
