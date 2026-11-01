// G7 最小版（BACKLOG-PLAN §2.3，主人 11-02 定档「P4 WRITE_TOKEN」）：
// ds→web 服务器间写端点的身份凭据。独立 env `WRITE_TOKEN`，不动 `INGEST_TOKEN` 的
// 语义（那枚管 ds 的 ingest 回调）。未设 = 放行（本机默认态，零破坏）；上云前设值
// 即整体生效，届时 ds 侧两处调用点（sync_scheduler.py 的 `/api/sync` 与
// `/api/market/refresh`）同批加头。
//
// ⚠️ 浏览器端入口刻意**不挂**本守卫：`/api/hotspots/run`（HotspotFeed 手动按钮）与
// `/api/research/start`（详情页按钮＋聊天 L2）的调用方是浏览器，持不了 secret——
// 挂上 = 设 token 那一刻这两个按钮死。11-02 落码时现查修正：BACKLOG-PLAN §2.3 那张表
// 把 hotspots/run 记成 ds 调用方，实况是 ds 从不调它（只调 /api/sync 与 refresh）。

import type { NextRequest } from "next/server";

/** 返回 null = 放行；返回字符串 = 拒绝原因（调用方应回 401）。 */
export function requireWriteToken(req: NextRequest): string | null {
  const expected = process.env.WRITE_TOKEN ?? "";
  if (!expected) return null;
  const authorization = req.headers.get("authorization");
  const got = authorization?.startsWith("Bearer ")
    ? authorization.slice("Bearer ".length)
    : req.headers.get("x-write-token");
  return got === expected ? null : "unauthorized";
}
