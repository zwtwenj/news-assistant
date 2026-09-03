// 受保护路径前缀：middleware（服务端）与 AuthProvider（客户端）共用
export const PROTECTED_PREFIXES = ["/account"];

export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
