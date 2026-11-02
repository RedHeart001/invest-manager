/**
 * CR10-9 附项（零改 compose）：`WRITE_TOKEN` 在 `docker-compose.yml` 两侧的**注入一致性**守卫。
 *
 * 为什么欠这一份（11-02 实测把账上那句"未决"证伪后剩下的那一半）：
 * - 校验侧 `web/lib/guard.ts:17`＝`if (!expected) return null;` ⇒ **未配值＝放行**；
 * - 发送侧 `data-service/app/sync_scheduler.py:281`＝无 token 就不带头；
 * - compose 全文零 `env_file:`，两枚 service 都没有 `WRITE_TOKEN` 那一行，而两侧 `.dockerignore`
 *   把 `.env` 挡在镜像外、`data-service/app/config.py` 又从不读 `.env.local`
 *   ⇒ **默认容器态＝双侧同在"未设"档＝02:00 那两条写腿双双 200**（不是"401 死"）。
 *
 * 真正会死、且今天**没有任何仪器会红**的形＝**只注入一侧**：ds 带头、web 不认 ⇒ 两条腿 401，
 * 而 `run_now` 在认领那一刻已落当日 marker（CR9-94）⇒ 这一天不再自动补跑。本守卫钉的就是这一形。
 *
 * 运行方式（零出网、不起容器、不改 compose）：
 *     npx vitest run lib/compose-token.test.ts
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const COMPOSE = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "docker-compose.yml"),
  "utf-8",
);

/** 只解析 `environment:` 块里那些「6 空格 + KEY: 值」的行，按 service 归组（够用且可反证） */
function parseServiceEnvs(yaml: string): Map<string, Map<string, string>> {
  const out = new Map<string, Map<string, string>>();
  let svc: string | null = null;
  let inEnv = false;
  for (const raw of yaml.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (/^\S/.test(line)) {
      svc = null;
      inEnv = false;
      continue;
    }
    const svcMatch = /^  ([A-Za-z0-9_-]+):\s*$/.exec(line);
    if (svcMatch) {
      svc = svcMatch[1];
      inEnv = false;
      out.set(svc, new Map());
      continue;
    }
    if (svc === null) continue;
    if (/^    environment:\s*$/.test(line)) {
      inEnv = true;
      continue;
    }
    if (/^    \S/.test(line)) inEnv = false;
    if (!inEnv) continue;
    const kv = /^      ([A-Za-z0-9_]+):\s*(.+?)\s*$/.exec(line);
    if (kv) out.get(svc)!.set(kv[1], kv[2]);
  }
  return out;
}

/** `${VAR}` 的"形"＝键名 + 修饰符（`""`／`:-`／`:?`）；只有同形才谈得上同值 */
function injectionForm(value: string | undefined): string | null {
  if (value === undefined) return null;
  const m = /\$\{([A-Za-z0-9_]+)(:([-?]))?/.exec(value);
  return m ? `${m[1]}${m[2] ?? ""}` : "LITERAL"; // 写死值＝本仓库不允许的形，出现即坏形
}

/** 判据函数（本守卫唯一的出口）：返回问题清单，空数组＝一致 */
function writeTokenDrift(webForm: string | null, dsForm: string | null): string[] {
  if (webForm === null && dsForm === null) return []; // 双侧未注入＝放行档＝自洽
  if (webForm === null || dsForm === null) {
    return [
      `单侧注入（web=${webForm ?? "未设"}／ds=${dsForm ?? "未设"}）⇒ 两条写腿 401，且当日 marker 已落不再自动补跑`,
    ];
  }
  if (webForm !== dsForm) return [`两侧不同形（web=${webForm}／ds=${dsForm}）⇒ 值不可能一致`];
  return [];
}

function formsOf(yaml: string) {
  const envs = parseServiceEnvs(yaml);
  return {
    web: injectionForm(envs.get("web")?.get("WRITE_TOKEN")),
    ds: injectionForm(envs.get("data-service")?.get("WRITE_TOKEN")),
  };
}

const INGEST_LINE =
  "      INGEST_TOKEN: ${INGEST_TOKEN:?必须在 .env 中设置 INGEST_TOKEN（ingest 回调共享密钥）}";

/**
 * 在第 `which`（1＝web／2＝data-service，按 compose 里的出现次序）枚 `INGEST_TOKEN` 之后插一行
 * `WRITE_TOKEN`——反向样本的造法。**找不到那一行就抛**，不许静默造出"两侧都没注入"的假好样本。
 */
function injectAfterIngest(yaml: string, which: 1 | 2, expr: string): string {
  const lines = yaml.split("\n");
  let seen = 0;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].replace(/\r$/, "") !== INGEST_LINE) continue;
    seen += 1;
    if (seen !== which) continue;
    lines.splice(i + 1, 0, `      WRITE_TOKEN: ${expr}`);
    return lines.join("\n");
  }
  throw new Error(`compose 里第 ${which} 枚 INGEST_TOKEN 未命中＝结构变了，反向样本失效`);
}

const WEB_TOKEN = "${WRITE_TOKEN:?根 .env 必须设置}";
const DS_TOKEN = "${WRITE_TOKEN:?根 .env 必须设置}";
const DS_TOKEN_OTHER_FORM = "${WRITE_TOKEN:-}";

describe("compose 的 WRITE_TOKEN 注入一致性（CR10-9 附项：只加测，不改 compose）", () => {
  it("现值＝两侧都没有 WRITE_TOKEN ⇒ 判**一致**（默认容器态双侧放行＝自洽，不是 401 死）", () => {
    const f = formsOf(COMPOSE);
    expect(f.web).toBeNull();
    expect(f.ds).toBeNull();
    expect(writeTokenDrift(f.web, f.ds)).toEqual([]);
    // 机制本身也钉一行：compose 全文零 env_file: ⇒ 镜像里两侧都读不到宿主机 .env，"未设"档就是这么来的
    expect(COMPOSE).not.toMatch(/^\s*env_file:/m);
  });

  it("🔁 反向样本一＝只注入 web ⇒ 必须判坏形（今天没有任何仪器会红的那一形）", () => {
    const f = formsOf(injectAfterIngest(COMPOSE, 1, WEB_TOKEN));
    const problems = writeTokenDrift(f.web, f.ds);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("单侧注入");
  });

  it("🔁 反向样本二＝只注入 data-service（反向的另一半）⇒ 同样判坏形", () => {
    const f = formsOf(injectAfterIngest(COMPOSE, 2, DS_TOKEN));
    const problems = writeTokenDrift(f.web, f.ds);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("单侧注入");
  });

  it("🔁 反向样本三＝两侧都有但来源不同形（一枚 `:?`、一枚 `:-`）⇒ 判坏形", () => {
    const both = injectAfterIngest(
      injectAfterIngest(COMPOSE, 1, WEB_TOKEN),
      2,
      DS_TOKEN_OTHER_FORM,
    );
    const f = formsOf(both);
    const problems = writeTokenDrift(f.web, f.ds);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("不同形");
  });

  it("好样本＝两侧都注入且同形 ⇒ 判一致（守卫不许把「补上了」读成坏）", () => {
    const both = injectAfterIngest(injectAfterIngest(COMPOSE, 1, WEB_TOKEN), 2, DS_TOKEN);
    const f = formsOf(both);
    expect(f.web).toBe("WRITE_TOKEN:?");
    expect(f.web).toBe(f.ds);
    expect(writeTokenDrift(f.web, f.ds)).toEqual([]);
  });

  it("🔁 造反向样本的那把手也有牙齿：`INGEST_TOKEN` 不在场时会抛，不会静默退化成「两侧都没注入」的假好样本", () => {
    const noAnchor = COMPOSE.split(INGEST_LINE).join("      # 锚点被删掉了");
    expect(() => injectAfterIngest(noAnchor, 2, WEB_TOKEN)).toThrow(/未命中/);
  });

  it("解析器的现值读数＝web 块 12 枚键／data-service 块 12 枚键（compose 改了要一起改这一行）", () => {
    const envs = parseServiceEnvs(COMPOSE);
    expect([...envs.get("web")!.keys()]).toEqual([
      "NODE_ENV",
      "PORT",
      "TZ",
      "DATABASE_URL",
      "DATA_SERVICE_URL",
      "INGEST_TOKEN",
      "LLM_BASE_URL",
      "LLM_API_KEY",
      "LLM_MODEL",
      "TAVILY_API_KEY",
      "SKILLS_DIR",
      "MCP_CONFIG",
    ]);
    expect([...envs.get("data-service")!.keys()]).toEqual([
      "TZ",
      "WEB_BASE_URL",
      "WEB_API_BASE",
      "INGEST_TOKEN",
      "LLM_BASE_URL",
      "LLM_API_KEY",
      "LLM_MODEL",
      "TAVILY_API_KEY",
      "SEARCH_API_KEY",
      "HTTP_PROXY",
      "HTTPS_PROXY",
      "NO_PROXY",
    ]);
  });

  it("登记一条运维事实＝`INGEST_TOKEN` 两侧同形且都是 `:?`（将来给 WRITE_TOKEN 也这么写，根 .env 就得新增该键，否则 compose 当场拒启）", () => {
    const envs = parseServiceEnvs(COMPOSE);
    const web = injectionForm(envs.get("web")?.get("INGEST_TOKEN"));
    const ds = injectionForm(envs.get("data-service")?.get("INGEST_TOKEN"));
    expect(web).toBe("INGEST_TOKEN:?");
    expect(ds).toBe(web);
  });
});
