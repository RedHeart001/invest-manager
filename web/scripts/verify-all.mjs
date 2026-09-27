// 状态确认：串行跑全部 web 集成套件并汇总
import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const suites = ["test-db.mjs", "test-p1.mjs", "test-p2.mjs", "test-p3.mjs", "test-p4.mjs", "test-p6.mjs", "test-p5.mjs"];

// CR9-39（2026-09-27）：子进程路径与产物**一律相对本文件所在工程目录**解析。
// 此前用 `spawn(node, ["scripts/xxx.mjs"], {cwd: process.cwd()})`，而门槛里的权威命令是
// 从仓库根跑的 `node web/scripts/verify-all.mjs` ⇒ 7 个套件全部 `Cannot find module`，
// 且那行错误被下面的 tail 过滤正则吃掉，输出只剩"exit=1 断言 0/18"——今天就是这样
// 白跑了一轮才查明。跑哪个目录都该得到同一结果，这是门禁可复现性的底线（CR9-34 同族）。
const WEB_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");

// CR9-25：这些套件过去只打印"通过 X"，而 X = **实际执行到的断言数**——被条件分支跳过的
// 断言既不失败也不计数，于是"全绿"≠"全跑"（09-26 实证：test-p5 串行 17、单跑 21，
// 差 4 条仍 exit=0）。这里显式声明每个套件的应跑断言数，跑完对比并公开缺口。
// 维护契约：**改动任何套件的断言条数时同步改这张表**（数值来源 = 单独跑该套件的实际数）。
// CR9-36：值可以是**数组**，表示该套件按设计有多档断言数（自适应跳过的段落）。
// 多档仍要登记，否则"跑少了"和"跑错了"在输出里长得一样；不在任一档内即算缺口。
const PLANNED = {
  "test-db.mjs": 18,
  "test-p1.mjs": 20,
  // 40 = 加密主数据缺失/BTC 不可达日（第 7 段只断"可达或显式降级"一条）；
  // 41 = BTC K 线可达时多一条 `valueOnly` 标注断言（CR9-26② 09-27 配好 HTTPS_PROXY 后到货）。
  // 两档都由数据形态决定、都是合法状态 ⇒ 按 CR9-36 登记成数组而不是挑一个数写死。
  "test-p2.mjs": [40, 41],
  "test-p3.mjs": 27,
  // CR9-38（09-27）：p4 的第 4 段从"两条 LLM 措辞断言"换成三条结构化断言（两轮走完／
  // 会话历史四条／指代按工具入参或正文判定）⇒ 应跑数 19→20。
  "test-p4.mjs": 20,
  "test-p6.mjs": 24,
  // 17 = 当日尚无已完成研报（[1][2] 两段结构断言按设计跳过）；21 = 当日已有已完成研报。
  // 09-27 实测：串行批次里 17（研报还没跑完），单独复跑 21 —— 两档都真实存在。
  "test-p5.mjs": [17, 21],
};

/** 两种汇总格式都要认：`===== N/M 通过 =====`（db/p1）与 `结果：N 通过 / M 失败 ==`（p2–p6）。
 *  都没匹配到 = 套件在打印汇总之前就退出（崩溃/超时），按 0 计，让缺口显式暴露。 */
function executedCount(out) {
  const ds = out.match(/=====\s*(\d+)\/(\d+)\s*通过\s*=====/);
  if (ds) return Number(ds[2]);
  const ledger = out.match(/结果：\s*(\d+)\s*通过\s*\/\s*(\d+)\s*失败/);
  if (ledger) return Number(ledger[1]) + Number(ledger[2]);
  return 0;
}

const lines = [];
const gaps = [];
for (const s of suites) {
  const started = Date.now();
  const r = spawnSync(process.execPath, [join(WEB_DIR, "scripts", s)], {
    cwd: WEB_DIR,
    encoding: "utf8",
    timeout: 20 * 60 * 1000,
    env: { ...process.env, TEST_BASE: "http://localhost:3000", WEB_URL: "http://localhost:3000" },
  });
  const out = `${r.stdout ?? ""}\n${r.stderr ?? ""}`;
  // tail 必须保住"跳过"解释行，否则缺口只剩一个数字（CR9-36）；
  // CR9-39：还要保住"根本没跑起来"那类错误行（Cannot find module / SyntaxError …）。
  const tail = out
    .split("\n")
    .filter((l) => /=====|通过|失败|跳过|OK|NG|PASS|FAIL|Error|Cannot find|code E[0-9]/i.test(l))
    .slice(-14)
    .join("\n");
  const ran = executedCount(out, s);
  const plan = PLANNED[s] ?? 0;
  const shapes = Array.isArray(plan) ? plan : [plan];
  const hit = shapes.includes(ran);
  // 两个方向都不许静默：缺跑是 CR9-25 的原始形态，"表未同步"是它的镜像
  const mark = hit
    ? shapes.length > 1
      ? `（多档形态 ${shapes.join("/")}，本次 ${ran}）`
      : ""
    : ` ⚠️ 实跑 ${ran} 不在登记形态 ${shapes.join("/")} 内（CR9-25/36）`;
  if (!hit) gaps.push(`${s}：应跑形态 ${shapes.join(" 或 ")}，实跑 ${ran}`);
  lines.push(
    `\n########## ${s} — exit=${r.status} 用时 ${Math.round((Date.now() - started) / 1000)}s 断言 ${ran}/${shapes.join("|")}${hit ? "" : " ⚠️"} ##########\n${tail}`,
  );
  console.log(`${s}: exit=${r.status} 断言 ${ran}/${shapes.join("|")}${mark}`);
}
writeFileSync(join(WEB_DIR, "verify-suites.txt"), lines.join("\n"), "utf8");
if (gaps.length) {
  // 不静默：绿色数字里混着"根本没跑"的断言，正是 CR9-25 要消灭的假闭环
  console.log(`\n!!! 断言缺口（全绿不等于全跑）：\n  - ${gaps.join("\n  - ")}`);
}
console.log("ALL DONE");

