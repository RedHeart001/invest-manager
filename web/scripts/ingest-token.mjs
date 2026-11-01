// 写接口/写回调的共享口令：容器态由 compose 注入 process.env，本地开发态在 web/.env（ds 也读这份）。
// 值只用于请求头，任何分支都不得打印它。
//   · INGEST_TOKEN  ＝ ds→web 的落库回调（CR9-51 立的契约：开守卫时集成脚本自己带）
//   · WRITE_TOKEN   ＝ ds→web 的两条写腿 POST /api/sync 与 /api/market/refresh（CR10-7 同族）
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const INGEST_TOKEN = process.env.INGEST_TOKEN || readFromEnvFile("INGEST_TOKEN");
export const WRITE_TOKEN = process.env.WRITE_TOKEN || readFromEnvFile("WRITE_TOKEN");

function readFromEnvFile(wanted) {
  const path = join(dirname(fileURLToPath(import.meta.url)), "..", ".env");
  try {
    for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const [key, ...rest] = line.split("=");
      if (key.trim() !== wanted) continue;
      let value = rest.join("=").trim();
      const quoted = value.length >= 2 && (value[0] === '"' || value[0] === "'");
      if (quoted && value.at(-1) === value[0]) value = value.slice(1, -1);
      return value;
    }
  } catch {
    // 读不到文件＝未配置，与 web 侧 `if (expected && …)` 的 fail-open 同形
  }
  return "";
}
