// 写接口 CSRF 防护：Origin/Referer 校验（CR-08，本轮 code review）
//
// 背景：/api/sync、/api/market/refresh、/api/hotspots/run 均为无请求体的 POST，
// 可被第三方页面的**简单表单**（`<form action="http://localhost:3000/api/sync"
// method="post" enctype="text/plain">`）跨站触发——浏览器对简单请求不发预检，
// 服务端此前也不校验来源 → 全量同步 / 热点 pipeline 被任意网站或爬虫触发。
//
// 对策（轻量，不改前端调用点）：校验 Origin（缺失时回退 Referer）的 host
// 是否属于"本站"。规则：
//   - 无 Origin 且无 Referer：放行（同源 fetch 可能不带 Origin；非浏览器客户端
//     如 curl/测试脚本也属此类——它们已是可信的本地操作方，本防护只针对**浏览器跨站**）
//   - 有来源：其 host 必须等于请求 Host（同站）或 env `ALLOWED_ORIGINS` 白名单
//
// 说明：这是 CSRF 层面的纵深防御，不等同于身份鉴权（G7 的完整方案另议）。

import type { NextRequest } from "next/server";

function hostOf(value: string | null): string | null {
  if (!value) return null;
  try {
    return new URL(value).host;
  } catch {
    return null;
  }
}

/** 解析允许的额外来源 host（逗号分隔），如 "192.168.1.10:3000,example.com" */
function allowedHosts(): Set<string> {
  const raw = process.env.ALLOWED_ORIGINS ?? "";
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => hostOf(s.includes("://") ? s : `http://${s}`) ?? s),
  );
}

/**
 * 校验请求来源是否可信（防浏览器跨站简单请求）。
 * 返回 null = 放行；返回字符串 = 拒绝原因。
 */
export function checkRequestOrigin(req: NextRequest): string | null {
  const originHost = hostOf(req.headers.get("origin"));
  const refererHost = hostOf(req.headers.get("referer"));
  const sourceHost = originHost ?? refererHost;
  // 无来源（curl/测试/部分同源请求）：放行
  if (!sourceHost) return null;

  const selfHost = hostOf(req.nextUrl.origin) ?? req.headers.get("host");
  if (selfHost && sourceHost === selfHost) return null;
  if (allowedHosts().has(sourceHost)) return null;

  return `cross-site request blocked (origin=${sourceHost})`;
}
