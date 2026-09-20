import { afterEach, beforeEach, describe, expect, it } from "vitest";

// CR-04：connection_limit=1 注入（使 busy_timeout 覆盖 Prisma 唯一连接）
import { datasourceUrl } from "./prisma";

describe("datasourceUrl（CR-04）", () => {
  let saved: string | undefined;
  beforeEach(() => {
    saved = process.env.DATABASE_URL;
  });
  afterEach(() => {
    if (saved === undefined) delete process.env.DATABASE_URL;
    else process.env.DATABASE_URL = saved;
  });

  it("无 query 时追加 ?connection_limit=1", () => {
    expect(datasourceUrl("file:./dev.db")).toBe("file:./dev.db?connection_limit=1");
  });

  it("已有 query 时用 & 追加", () => {
    expect(datasourceUrl("file:./dev.db?socket_timeout=5")).toBe(
      "file:./dev.db?socket_timeout=5&connection_limit=1",
    );
  });

  it("已显式配置 connection_limit 时不覆盖（尊重用户设置）", () => {
    expect(datasourceUrl("file:./dev.db?connection_limit=5")).toBe("file:./dev.db?connection_limit=5");
    expect(datasourceUrl("file:./dev.db?x=1&connection_limit=3")).toBe(
      "file:./dev.db?x=1&connection_limit=3",
    );
  });

  it("容器路径同样生效", () => {
    expect(datasourceUrl("file:/app/data/dev.db")).toBe(
      "file:/app/data/dev.db?connection_limit=1",
    );
  });

  it("未配置 DATABASE_URL → undefined（不注入）", () => {
    delete process.env.DATABASE_URL;
    expect(datasourceUrl()).toBeUndefined();
    expect(datasourceUrl("")).toBeUndefined();
  });
});
