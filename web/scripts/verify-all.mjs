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
  // 20→23（10-01 来路驱动）：原来那条"页面里存在 aria-current"换成按**点亮的是哪一项**
  // 逐来路判——搜索页／from=search／from=home／无来路四种各一条（旧写法在导航把
  // /product 谎报成搜索子页时照样绿）。
  "test-p1.mjs": 23,
  // 40 = 加密主数据缺失/BTC 不可达日（第 7 段只断"可达或显式降级"一条）；
  // 41 = BTC K 线可达时多一条 `valueOnly` 标注断言（CR9-26② 09-27 配好 HTTPS_PROXY 后到货）。
  // 两档都由数据形态决定、都是合法状态 ⇒ 按 CR9-36 登记成数组而不是挑一个数写死。
  // +8（10-01 刀 2/#22(c)(d)）：新增第 [10] 段"守卫与状态位"——health 的 db 位／
  // sync 的白名单与跨站 403／market/refresh 的白名单与跨站 403／不存在标的的
  // 「HTTP 200 ＋正文 not-found」成对两条（把"404 只能按正文判"钉成契约）／
  // 研报 ingest 未知标的 400。**全部零出网**（守卫在出网前就拒），故不新增额度档。
  // 48|49→54|55（10-03 主人"现在能执行的直接做"轮／#22(d) 的 watchlist 那条）：
  // 新增第 [11] 段"自选回环"6 条＝测试内 POST→GET→DELETE（合成 code、收尾必删、
  // leftover 自证）＋ upsert 幂等 ＋ 非法 type/code 的 400 且不写库。
  // 判的是 HTTP 层——`app/api/watchlist/route.test.ts` 那 6 条是 prisma mock，两者不互相替代。
  // 全段零出网（该路由只碰库），所以两档之差仍由 BTC 那一条决定，不新增额度档。
  // 54|55→59|60（10-03 深夜轮／#22(d) 的最后一条）：新增第 [12] 段「双源核对 BFF」5 条
  // ＝`/api/quote/verify` 此前零集成断言（CR7-3/B1 交付的路由）。三条主断言写成**蕴含式**
  // （200 必带机器可读三态 ⇔ 非 200 必带显式 error；三态与 `crossChecked` 两个方向都不许
  // 自相矛盾；没有第二源时必须说话）⇒ 上游全挂时落在"显式 error"那一支，不因外部态假红。
  // 两条守卫零出网（断的是 400 的**措辞**，能区分 BFF 白名单拒的与 ds 拒的）。
  // ⚠️ 额度档：主断言只发**一次** BFF 请求＝10-03 22:5x 实测 **3 次上游尝试**（东财主源失败
  // → 腾讯成功 → 比对时再打东财一次），"两个源＝两次请求"的估算在降级链上不成立。
  "test-p2.mjs": [59, 60],
  // 27→30（10-01 批次二）：CR8-1「逐卡降级产出不再出现」＋ CR8-3「相关文章区随链接
  // 存在而渲染」＋ CR8-3「读侧归一化：存量裸字符串也拿到 {url,title}」。
  // 30→34（10-01 刀 2/#22(e)）：「产出说明」页头此前零断言。合成一条 degraded 行 ⇒
  // 正面证明横幅能显示 ＋ note 原文上屏（两条），删完合成行后 🔁 两条：横幅出现
  // **必须等价于**最新批次还有 degraded 行，且逐卡「降级产出」没被打回原形。
  "test-p3.mjs": 34,
  // CR9-38（09-27）：p4 的第 4 段从"两条 LLM 措辞断言"换成三条结构化断言（两轮走完／
  // 会话历史四条／指代按工具入参或正文判定）⇒ 应跑数 19→20。
  // 09-28：门禁外的 `b2-chain.mjs` 并入为第 5 段「组合链」3 条（一轮内 ≥2 次工具调用／
  // 热点族+行情族各被调用／走完）⇒ 20→23。LLM 未配置时第 2、5 段整段跳过。
  "test-p4.mjs": 23,
  // 24→25（10-03 F6＝M7 已知优化点 2 闭环）：`namespaces.mcp.probeTimeoutS` 这条观测位
  // 上集成层——面板要自证"探测最多等几秒"活在这个进程里，而不是等某个 server 挂起时由人猜。
  // 零出网（stdio server 在本地，探测不打外网）。
  "test-p6.mjs": 25,
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
const failedSuites = [];
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
  if (r.status !== 0) failedSuites.push(`${s}：exit=${r.status}（断言 ${ran}/${shapes.join("|")}）`);
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
if (failedSuites.length) {
  console.log(`\n!!! 套件非零退出：\n  - ${failedSuites.join("\n  - ")}`);
}
// #28（10-03 主人点头）：缺口与失败**必须编码进退出码**。此前这里无条件打完 `ALL DONE` 就
// exit 0 ⇒ 门槛④ 历次拿来当凭据的那个 `verify_all_exit=0`，在"某套 exit=1、断言 0/23"的
// 日子里照样是 0（10-03 01:1x 的 p4 就是这么被糊过去的，靠人逐行读 `exit=` 才发现）。
// 属假绿的第三种形态：CR9-25 是"条件跳过仍 exit 0"，CR9-36 是"多档计数"，这次是
// **缺口已经被打印出来、却没被编码**。多档形态仍按 PLANNED 数组判（CR9-36 不变）。
const bad = gaps.length + failedSuites.length;
if (bad) {
  console.log(`\nGATE FAILED（${bad} 项）：详见上面 !!! 段落；这次读数不得记作"④ 全绿"`);
  process.exit(1);
}
console.log("ALL DONE");

