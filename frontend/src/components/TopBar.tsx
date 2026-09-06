"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/auth";

export default function TopBar() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push("/");
  };

  return (
    <header className="sticky top-0 z-10 border-b border-solid border-border bg-card">
      <div className="flex w-full items-center justify-between px-6 py-3">
        <Link href="/" className="text-lg font-semibold text-foreground">
          新闻助手
        </Link>
        <div className="flex items-center gap-4 text-sm">
          {loading && <span className="text-muted-foreground">…</span>}
          {!loading && user && (
            <>
              <Link
                href="/account"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {user.phone.slice(0, 3)}****{user.phone.slice(-4)}
              </Link>
              <Button variant="outline" size="sm" onClick={() => void handleLogout()}>
                <LogOut />
                退出
              </Button>
            </>
          )}
          {!loading && !user && (
            <Link href="/login">
              <Button size="sm">登录</Button>
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
