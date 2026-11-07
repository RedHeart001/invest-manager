// Next.js 服务端启动钩子（Next 15 起不需要 `experimental.instrumentationHook`）。
//
// 这里只做一件事：**把 undici 的传输层上限抬到 900s**，让 `AbortSignal.timeout(N)`
// 重新成为唯一的预算权威。背景与不变量（为什么是 900s、必须大于哪个预算）写在
// `lib/data-service.ts` 的 `TRANSPORT_CEILING_MS` 头上，改数值前先读那段。
//
// ⚠️ 三条踩过的坑，改写本文件前必读（全部是 2026-11-07 现场实测）：
//
// ① **安装动作不能住 `lib/data-service.ts`**：那个文件是同构的——`"use client"` 的
//    `ProductCharts.tsx` → `lib/events.ts` → `lib/data-service.ts` 这条链会把它打进
//    浏览器 bundle。顶层 `import { Agent } from "undici"` 会让 webpack 顺着
//    `undici/lib/dispatcher/client.js → node:assert` 报 `UnhandledSchemeError`，整站编译失败。
//
// ② **本文件会被 edge 与 nodejs 各编译一次**，所以里面**不许出现任何 `node:` 前缀的
//    静态 import 或 `await import()`**。edge 那个编译单元不认 `node:` 方案，
//    会在 bundler 阶段就报 `UnhandledSchemeError: Reading from "node:module"`——
//    此时 `NEXT_RUNTIME` 的运行期判断**还没机会跑**（实测：先报 webpack 错，
//    再报 `createRequire is not a function`）。
//
// ③ **`undici` 不能用 import 拿**：它的入口把 `lib/mock/*` 一起拉进来，那些文件
//    require `node:console`。`serverExternalPackages: ["undici"]` 也救不了本文件
//    （实测照样在 `○ Compiling /instrumentation` 阶段炸），因为 instrumentation
//    有自己的编译单元。
//
// ⇒ 结论：只用 `process.getBuiltinModule()` + `createRequire`（都是**运行期函数调用**，
//    webpack 的静态分析看不见），既绕开 edge 编译，也绕开 undici 的 mock 入口。

export async function register(): Promise<void> {
  // edge runtime 没有 undici 的 Node 版本，也不跑我们的 BFF 出网路径 ⇒ 直接跳过。
  // 这一步在 Node 上恒为 true（Next 只有一个 nodejs runtime 跑路由）。
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  // `process.getBuiltinModule`（Node ≥22.3）：取内置模块的**运行期**句柄。
  // 不用 `import("node:module")` —— 见上面坑 ②。
  const getBuiltinModule = (
    process as unknown as {
      getBuiltinModule?: (id: string) => unknown;
    }
  ).getBuiltinModule;
  if (typeof getBuiltinModule !== "function") return; // 老 Node：静默放弃，行为退回默认 300s

  const nodeModule = getBuiltinModule("node:module") as {
    createRequire: (p: string) => (id: string) => unknown;
  };
  // 用 cwd 而不是 `import.meta.url` 作基准：两者都能解析到 `node_modules/undici`，
  // 但 cwd 不依赖本文件被打包后的虚拟路径（webpack 会改写 `import.meta.url`）。
  const require_ = nodeModule.createRequire(`${process.cwd()}/instrumentation.js`);
  const undici = require_("undici") as typeof import("undici");

  // 上限常量从 lib 取——保持"一个数只写一次"。`data-service.ts` 顶层只有
  // fetch/AbortSignal 与纯数字，没有任何服务端专用 import ⇒ 引用它安全。
  const { TRANSPORT_CEILING_MS } = await import("@/lib/data-service");

  // C17 同款：挂 globalThis 做幂等。dev 下 HMR 会重跑本钩子，重复安装虽然无害，
  // 但每次都会新建一个 Agent ⇒ 连接池不复用。
  const key = Symbol.for("invest-manager.ds.transport-ceiling");
  const g = globalThis as unknown as Record<symbol, number | undefined>;
  if (g[key] === TRANSPORT_CEILING_MS) return;

  // 只设这两个；`connectTimeout` 保持默认 10s——ds 在同机/同 compose 网络内，
  // 连不上是立刻的事实，调大只会把"服务没起来"拖成慢失败。
  undici.setGlobalDispatcher(
    new undici.Agent({ headersTimeout: TRANSPORT_CEILING_MS, bodyTimeout: TRANSPORT_CEILING_MS }),
  );
  g[key] = TRANSPORT_CEILING_MS;
}
