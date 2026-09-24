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
});
