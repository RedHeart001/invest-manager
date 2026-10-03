import type { NextConfig } from "next";

// CR9-58（#31 选 A）：`dev.db` 就住在 Next dev 的监听目录里（web/prisma/），
// **每一次写库都会触发一次全量重编译**（10-03 与 10-04 两次对照实验：30 次纯 GET
// ⇒ `Compiled` 0 次；12 轮写库回环 ⇒ 13 次）。落在重编译窗口里的请求由 Next 自己
// 返回 500（响应体为空或 text/html，路由的 catch 根本没机会跑），每晚 02:00 那轮
// 同步一次写 5571 行 ⇒ 那几分钟页面上是"偶发 500/白屏"。
// 主人的口径＝排除监听，**不挪库**（不动数据位置、不动 DATABASE_URL，单点可回退）。
const nextConfig: NextConfig = {
  experimental: {
    // 客户端路由缓存：back/forward 时复用已渲染的动态页面（默认 dynamic=0 会
    // 导致返回搜索页时结果丢失、重新请求）
    staleTimes: { dynamic: 300, static: 300 },
  },
  webpack(config) {
    // `**/*.db*` 覆盖 dev.db / -wal / -shm 三件套（SQLite 写一次会碰其中多个文件）；
    // `.prisma` 是生成客户端的目录，Prisma client 落库时同样会 touch 它。
    // webpack 的 schema 明写"ignored 的每一项是 glob"，且**空串会被判非法**（本轮就是这么把
    // dev server 弄死一次的）⇒ Next 传进来的默认值若是空串必须先滤掉，再拼我们这四条。
    const prev = config.watchOptions?.ignored;
    const kept = (Array.isArray(prev) ? prev : [prev]).filter(
      (p): p is string => typeof p === "string" && p.length > 0,
    );
    config.watchOptions = {
      ...config.watchOptions,
      ignored: [...new Set([...kept, "**/*.db", "**/*.db-wal", "**/*.db-shm", "**/prisma/**"])],
    };
    return config;
  },
};

export default nextConfig;
