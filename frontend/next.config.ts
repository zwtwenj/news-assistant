import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // 容器化运行（frontend/Dockerfile）依赖 standalone 产物；dev/start 不受影响
  output: "standalone",
  async rewrites() {
    // 前端统一请求 /api/*，由 Next.js 转发到后端，避免开发期 CORS 问题
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
      {
        // 播客音频等本地存储产物（生产切 CDN/OSS 后移除）
        source: "/media/:path*",
        destination: `${BACKEND_URL}/media/:path*`,
      },
    ];
  },
};

export default nextConfig;
