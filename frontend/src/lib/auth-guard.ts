// 受保护路径前缀：middleware（服务端）与 AuthProvider（客户端）共用
export const PROTECTED_PREFIXES = ["/account", "/news", "/podcasts", "/chat"];

export function isProtectedPath(pathname: string): boolean {
  // 首页（数据总览）需登录；根路径单独判断——若并入前缀列表，"/" 会匹配所有路径
  if (pathname === "/") return true;
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
