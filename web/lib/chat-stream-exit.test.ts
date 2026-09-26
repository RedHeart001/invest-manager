import { describe, expect, it } from "vitest";

import { classifyStreamExit } from "./chat-stream-exit";

// CR7-5：ChatUI 180s 中断必须可感知。三形态判定（纯函数，零依赖）。
describe("classifyStreamExit（CR7-5）", () => {
  it("done + 未到期 = 正常完成", () => {
    expect(classifyStreamExit({ gotDone: true, expired: false })).toBe("completed");
  });

  it("未 done + 到期 = 中断（回答可能不完整）", () => {
    expect(classifyStreamExit({ gotDone: false, expired: true })).toBe("interrupted");
  });

  it("未 done + 未到期 = 异常退出（流被提前掐断）", () => {
    expect(classifyStreamExit({ gotDone: false, expired: false })).toBe("abnormal");
  });

  // CR9-2（2026-09-26）：服务端 error 事件已给出可行动原因，收尾不得用通用文案覆盖。
  // 反向对照：`api/chat/route.ts` 的 catch 分支发完 error 就 close（不发 done），
  // 三参数组合里 expired 两种取值都必须落到 "errored"。
  it("服务端已报 error + 未到期 = errored（覆盖真因的入口被封死）", () => {
    expect(classifyStreamExit({ gotDone: false, expired: false, sawError: true })).toBe("errored");
  });

  it("服务端已报 error + 同时到期 = errored（error 优先于超时文案）", () => {
    expect(classifyStreamExit({ gotDone: false, expired: true, sawError: true })).toBe("errored");
  });

  it("sawError 省略时向后兼容（CR7-5 三形态不变）", () => {
    expect(classifyStreamExit({ gotDone: false, expired: true })).toBe("interrupted");
    expect(classifyStreamExit({ gotDone: true, expired: true, sawError: true })).toBe("completed");
  });
});
