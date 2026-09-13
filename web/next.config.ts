import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // 客户端路由缓存：back/forward 时复用已渲染的动态页面（默认 dynamic=0 会
    // 导致返回搜索页时结果丢失、重新请求）
    staleTimes: { dynamic: 300, static: 300 },
  },
};

export default nextConfig;
