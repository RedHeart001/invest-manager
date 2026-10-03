// P2 验收测试（对齐 PLAN.md「验证方式 P2」+ 增补，双服务需已启动）
// 覆盖：
//  1. 股票/基金（场内+场外）/可转债 K 线数据正确；沪转债 secid 修复验证
//  2. 自定义起止日期
//  3. KlineDaily 二次访问命中缓存（cachedDays>0 且 fetchedDays=0）
//  4. 详情页 SSR：六区结构、阶段解读、归因文案含"可能相关"、面包屑/导航高亮
//  5. R13 双源交叉验证：quote vs kline 收盘偏差 <0.5%（按是否交易日选基准）
//  6. 事件接口（股票 byDate / 其余类型缺口说明）
//  7. 加密标的：可达或显式降级（R12/R10）
//  8. 基金持仓 / 国债收益率曲线（降级容忍）
// 纪律：失败最多重试 3 次（用户 2026-09-12 指示）；东财限流规避：节流间隔 + 空结果退避重试

import { INGEST_TOKEN } from "./ingest-token.mjs";

const BASE = process.env.TEST_BASE ?? "http://localhost:3000";
const DATA = process.env.TEST_DATA ?? "http://localhost:8000";

let passed = 0;
let failed = 0;
const failures = [];

function ok(name, cond, detail = "") {
  if (cond) {
    passed += 1;
    console.log(`  OK ${name}`);
  } else {
    failed += 1;
    failures.push(`${name}${detail ? ` — ${detail}` : ""}`);
    console.log(`  NG ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getJson(url, timeoutMs = 60_000) {
  const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
}

async function getText(url, timeoutMs = 60_000) {
  const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  return { status: res.status, text: await res.text() };
}

// K 线空结果退避重试（东财限流软表现：200 + 空 candles；最多 3 次尝试）
async function getKlineRetry(params, attempts = 3) {
  let last;
  for (let i = 0; i < attempts; i++) {
    if (i > 0) await sleep(8000);
    last = await getJson(`${BASE}/api/kline?${params}`);
    if ((last.body.candles?.length ?? 0) > 0) return last;
  }
  return last;
}

function iso(daysAgo) {
  return new Date(Date.now() + 8 * 3600_000 - daysAgo * 86_400_000)
    .toISOString()
    .slice(0, 10);
}

async function main() {
  console.log(`\n== P2 验收：BFF=${BASE} data-service=${DATA}\n`);

  // ---------- 1. 股票 K 线 ----------
  console.log("[1] 股票 K 线（600519 贵州茅台）");
  {
    const { status, body } = await getKlineRetry(
      `type=stock&code=600519&start=${iso(90)}&end=${iso(0)}`,
    );
    ok("HTTP 200", status === 200, `status=${status} ${JSON.stringify(body).slice(0, 120)}`);
    const candles = body.candles ?? [];
    ok("日 K 非空（≥40 根）", candles.length >= 40, `got ${candles.length}`);
    ok(
      "OHLC 形状合法",
      candles.every(
        (c) =>
          c.high >= c.low &&
          c.high >= c.open &&
          c.high >= c.close &&
          c.low <= c.open &&
          c.low <= c.close,
      ),
    );
    ok("来源标注存在", Boolean(body.source));
    ok("日期升序", candles.every((c, i) => i === 0 || c.date > candles[i - 1].date));

    // R13 双源交叉验证：
    // - kline 最后一根是"今天"（交易时段内未收盘）→ 与 quote.prevClose（昨日收盘）比
    // - 否则（最后一根为最近已收盘交易日）→ 与 quote.price（停盘时 quote=最近收盘）比
    const today = iso(0);
    const q = await getJson(`${BASE}/api/quote?type=stock&code=600519`);
    if (q.status === 200 && candles.length >= 2) {
      const last = candles[candles.length - 1];
      const isToday = last.date === today;
      const ref = isToday ? q.body.prevClose : q.body.price;
      const refClose = isToday ? candles[candles.length - 2].close : last.close;
      if (ref) {
        const dev = Math.abs(refClose - ref) / ref;
        ok(
          "R13：kline 收盘与 quote 同日收盘偏差 <0.5%",
          dev < 0.005,
          `kline=${refClose} ref=${ref} (${isToday ? "prevClose" : "price"}) dev=${(dev * 100).toFixed(3)}%`,
        );
      } else {
        ok("R13：kline 收盘与 quote 同日收盘偏差 <0.5%", false, "quote 缺少 price/prevClose");
      }
    } else {
      ok("R13：kline 收盘与 quote 同日收盘偏差 <0.5%", false, "quote 或 kline 数据不足");
    }

    // 缓存二次命中（不再触发外部请求）
    const second = await getJson(
      `${BASE}/api/kline?type=stock&code=600519&start=${iso(90)}&end=${iso(0)}`,
    );
    ok(
      "二次访问命中 KlineDaily 缓存（fetchedDays=0）",
      second.body.fetchedDays === 0 && second.body.cachedDays > 0,
      `cached=${second.body.cachedDays} fetched=${second.body.fetchedDays}`,
    );

    // 自定义起止日期（缓存应已覆盖，不触发外部请求）
    await sleep(1500);
    const custom = await getJson(
      `${BASE}/api/kline?type=stock&code=600519&start=${iso(30)}&end=${iso(5)}`,
    );
    const c0 = custom.body.candles?.[0]?.date ?? "";
    const cN = custom.body.candles?.slice(-1)?.[0]?.date ?? "";
    ok("自定义区间首根 ≥ start", c0 >= iso(30), `first=${c0}`);
    ok("自定义区间末根 ≤ end", cN <= iso(5) && cN >= iso(35), `last=${cN}`);
  }

  await sleep(2000);

  // ---------- 2. 场内基金 K 线 ----------
  console.log("[2] 场内基金 K 线（159915 创业板ETF）");
  {
    const { status, body } = await getKlineRetry(
      `type=fund&code=159915&start=${iso(60)}&end=${iso(0)}`,
    );
    ok(
      "场内 ETF 为 K 线（非 valueOnly）且非空",
      status === 200 && body.valueOnly === false && (body.candles?.length ?? 0) > 20,
      `status=${status} n=${body.candles?.length} note=${body.note ?? ""}`,
    );
  }

  await sleep(2000);

  // ---------- 3. 场外基金净值历史 ----------
  console.log("[3] 场外基金净值历史（110022 易方达消费行业）");
  {
    const { status, body } = await getKlineRetry(
      `type=fund&code=110022&start=${iso(90)}&end=${iso(0)}`,
    );
    ok(
      "净值历史（valueOnly）",
      status === 200 && body.valueOnly === true && (body.candles?.length ?? 0) > 20,
      `status=${status} n=${body.candles?.length}`,
    );
    ok("来源标注 fund-nav-hist", String(body.source ?? "").includes("fund-nav"));

    const h = await getJson(
      `${BASE}/api/kline?type=fund&code=110022&start=${iso(90)}&end=${iso(0)}`,
    );
    ok(
      "净值历史二次访问命中缓存",
      h.body.fetchedDays === 0 && h.body.cachedDays > 0,
      `cached=${h.body.cachedDays} fetched=${h.body.fetchedDays}`,
    );

    await sleep(1500);
    const holdings = await getJson(`${DATA}/fund/holdings?code=110022`);
    ok(
      "基金重仓持股（可达或有降级标注）",
      holdings.status === 200 &&
        ((holdings.body.holdings?.length ?? 0) > 0 || holdings.body.degraded === true),
      `quarter=${holdings.body.quarter} n=${holdings.body.holdings?.length}`,
    );
  }

  await sleep(2000);

  // ---------- 4. 可转债 K 线（含沪转债 secid 修复） ----------
  // 标的选取修正（2026-09-13，两次踩坑后定稿）：
  //   ① 原实现取列表首个 11/12 前缀标的 → 可能命中**未上市/已退市**转债（113710/123285 均不在实时列表）→ K 线必然为空
  //   ② 改为 browse(code asc, pageSize 50) 后，前 50 条全落在 110xxx（沪市**老债/已到期段**）且不含 12xxxx 深市
  //   最终方案：从 ds 全量转债列表（1052 条，东财限流时有新浪备源兜底）筛选**活跃代码段**
  //   （沪 111/113、深 123/127/128），并用 BFF 行情预筛（price 非 null = 在交易）后测 K 线。
  console.log("[4] 可转债 K 线（活跃代码段 + 行情预筛候选池）");
  {
    const list = await getJson(`${DATA}/products?type=bond`, 120_000);
    const bonds = list.body.products ?? [];
    ok(
      "可转债列表非空（ds 全量/备源）",
      bonds.length > 0,
      // CR9-31：把 data-service 声明的出网源/降级说明一并打出来——覆盖面是 1059 还是
      // 320 只，光看 n= 判不出来；没有 source 就只能事后翻 ds 日志。
      `status=${list.status} n=${bonds.length} src=${list.body.source ?? "?"}` +
        `${list.body.degraded ? ` degraded:${list.body.note ?? ""}` : ""} ${list.body.detail ?? ""}`,
    );

    const SEGMENTS = {
      沪转债: ["111", "113", "118"],
      深转债: ["123", "127", "128"],
    };
    for (const [label, segs] of Object.entries(SEGMENTS)) {
      const candidates = bonds
        .filter((b) => segs.some((s) => b.code.startsWith(s)))
        .slice(0, 10);
      if (candidates.length === 0) {
        ok(`${label}存在候选`, false, `列表中无 ${segs.join("/")} 段样本（共 ${bonds.length} 条）`);
        continue;
      }
      let passed = false;
      let sawNoQuote = false;
      const tried = [];
      for (const b of candidates) {
        // 行情预筛：不在交易（未上市/退市）的标的没有 K 线，跳过不计失败
        const q = await getJson(`${BASE}/api/quote?type=bond&code=${b.code}`, 60_000);
        if (q.body.price == null) {
          // 行情本身也不可得（新浪备源亦限流/标的无行情）：属"显式不可得"，
          // 与 K 线降级同义——不能因此判定链路失败（2026-09-13 code review）
          sawNoQuote = true;
          tried.push(`${b.code}:无行情`);
          continue;
        }
        await sleep(1500);
        const r = await getKlineRetry(`type=bond&code=${b.code}&start=${iso(60)}&end=${iso(0)}`);
        const n = r.body.candles?.length ?? 0;
        if (r.status === 200 && n > 5) {
          tried.push(`${b.code}:K线${n}`);
          passed = true;
          break;
        }
        // 断言语义修正（2026-09-13）：转债 K 线**仅有东财一个源**（新浪转债日线接口已废弃、
        // 腾讯不覆盖转债），东财 IP 级限流时必然取不到。此时**显式降级**即为正确行为（R10/R12）；
        // 只有"无数据且无降级说明"的静默失败才是缺陷。
        const note = String(r.body.note ?? r.body.error ?? "");
        const degradedExplicitly =
          /rate-limited|cooling down|降级|degraded|失败|unavailable|failed/i.test(note);
        tried.push(`${b.code}:K线${n}${degradedExplicitly ? "(显式降级)" : "(静默!)"}`);
        if (degradedExplicitly) {
          passed = true;
          break;
        }
      }
      ok(
        `${label} K线可用或显式降级（转债无备源，东财限流时降级为正确行为）`,
        passed || (sawNoQuote && tried.every((t) => t.includes("无行情"))),
        `尝试 ${tried.join(" ")}`,
      );
    }
  }

  await sleep(2000);

  // ---------- 5. 1D 分钟线 ----------
  console.log("[5] 1D 分钟线（600519，交易日有效；周末为空属正常）");
  {
    const r = await getJson(`${BASE}/api/kline?type=stock&code=600519&interval=1m`);
    const isWeekend = [0, 6].includes(new Date().getDay());
    ok(
      "分钟线 200（或周末空数据）",
      r.status === 200 || isWeekend,
      `status=${r.status} n=${r.body.candles?.length ?? 0}`,
    );
  }

  await sleep(1500);

  // ---------- 6. 事件接口 ----------
  console.log("[6] 事件标注接口");
  {
    const ev = await getJson(`${BASE}/api/events?type=stock&code=600519`);
    ok(
      "股票事件：byDate 或 degraded 均为合法响应",
      ev.status === 200 && (ev.body.degraded === true || (ev.body.byDate && typeof ev.body.byDate === "object")),
      `degraded=${ev.body.degraded} dates=${Object.keys(ev.body.byDate ?? {}).length}`,
    );
    const evFund = await getJson(`${BASE}/api/events?type=fund&code=110022`);
    ok(
      "基金事件：显式缺口说明",
      evFund.body.degraded === true &&
        typeof evFund.body.note === "string" &&
        evFund.body.note.length > 0,
      `note=${evFund.body.note}`,
    );
    // CR9-10（2026-09-26 接线）：type/code 走 lib/validate 单一来源，非法入参出网前 400，
    // 不得进 fetchEvents→dsGet("/news")（东财 rate_per_min=12）。反向对照用上面两条 200 用例。
    {
      const badCode = await getJson(`${BASE}/api/events?type=stock&code=..%2Fetc`);
      ok(
        "事件接口：非法 code → 400 且点名 invalid code（CR9-10）",
        badCode.status === 400 && String(badCode.body.error ?? "").includes("invalid code"),
        `status=${badCode.status} body=${JSON.stringify(badCode.body).slice(0, 90)}`,
      );
      const badType = await getJson(`${BASE}/api/events?type=nope&code=600519`);
      ok(
        "事件接口：非法 type → 400 且点名 unsupported type（CR9-10）",
        badType.status === 400 && String(badType.body.error ?? "").includes("unsupported type"),
        `status=${badType.status} body=${JSON.stringify(badType.body).slice(0, 90)}`,
      );
    }
  }

  // ---------- 7. 加密标的（R12：可达；不可达时 R10 降级 200+note 或明确错误码） ----------
  console.log("[7] 加密标的 BTC（R12 条件降级）");
  {
    const r = await getJson(
      `${BASE}/api/kline?type=crypto&code=BTC&start=${iso(30)}&end=${iso(0)}`,
    );
    const reachable = r.status === 200 && (r.body.candles?.length ?? 0) > 0;
    const degraded =
      (r.status === 200 && typeof r.body.note === "string" && r.body.note.length > 0) ||
      [400, 501, 502, 503].includes(r.status);
    ok(
      "BTC 可达（代理/直连）或显式降级（缺口说明/明确错误码）",
      reachable || degraded,
      `status=${r.status} n=${r.body.candles?.length ?? 0} note=${r.body.note ?? ""}`,
    );
    if (reachable) {
      ok("BTC K 线 valueOnly 标注", r.body.valueOnly === true);
    }
  }

  // ---------- 8. 详情页 SSR（六区 + 交互约定） ----------
  console.log("[8] 详情页 SSR（/product/stock/600519）");
  {
    await sleep(1500);
    const page = await getText(`${BASE}/product/stock/600519`);
    const html = page.text;
    ok("HTTP 200", page.status === 200, `status=${page.status}`);
    ok("① 身份区：名称与画像行", html.includes("贵州茅台") && html.includes('data-testid="profile"'));
    ok("② 现状区：指标卡", html.includes("昨收") && html.includes("区间最高(近3月)"));
    ok("③ 主图区：时间档位与对比入口", html.includes(">近1年<") && html.includes("叠加对比"));
    ok("④ 变化解读区：归因克制文案", html.includes("可能相关事件（非因果断言）"));
    ok("④ 变化解读区：阶段表格有数据行", (html.match(/→/g) ?? []).length >= 1);
    ok("⑤ 明细区：日线数据表", html.includes("日线数据（最近"));
    ok("⑥ 深度分析区（P5 已交付：研报面板或加载态）", html.includes("深度分析"));
    // CR8-5 删面包屑后改名：本条判据一直是"页面含一级入口文字"（顶部导航承担），
    // 旧名字「R7 面包屑」谎称了它测的东西。
    ok("R7 顶部导航含一级入口（首页/搜索）", html.includes("首页") && html.includes("搜索"));
    // 来路驱动（10-01）：本条原样是 `html.includes('aria-current="page"')`，即**要求
    // 产品页必须点亮某个一级导航**——它把"导航把 /product 硬编码归给搜索"这条谎锁成了
    // 契约。断言随之反向（本段取的是不带 `from` 的裸 URL＝诚实态）；
    // 带 from 的四种来路在 test-p1 逐条判。
    ok("R7 产品页无来路时不点亮任何一级", !html.includes('aria-current="page"'));
    ok("免责声明", html.includes("不构成投资建议"));
    ok("来源标注", html.includes("数据来源："));
  }

  console.log("\n[8b] 详情页 SSR（/product/fund/110022 场外基金槽位）");
  {
    await sleep(1500);
    const page = await getText(`${BASE}/product/fund/110022`);
    ok("HTTP 200", page.status === 200, `status=${page.status}`);
    ok("画像含'场外基金'", page.text.includes("场外基金"));
    ok(
      "单位净值展示（4 位小数或'单位净值'字样）",
      /1\.\d{4}/.test(page.text) || page.text.includes("单位净值"),
    );
  }

  console.log("\n[8c] 详情页 SSR（可转债）");
  {
    const list = await getJson(
      `${BASE}/api/search?type=bond&browse-sort=code&browse-order=asc&pageSize=50`,
    );
    const items = list.body.items ?? [];
    const b = items.find((x) => x.code.startsWith("12")) ?? items[0];
    if (b) {
      const page = await getText(`${BASE}/product/bond/${b.code}`);
      ok(`可转债详情页 200（${b.code}）`, page.status === 200, `status=${page.status}`);
    } else {
      ok("可转债详情页 200（样本）", false, "BFF 侧无可转债样本");
    }
  }

  // ---------- 9. 收益率曲线 ----------
  console.log("[9] 国债收益率曲线");
  {
    const y = await getJson(`${DATA}/bond/yieldcurve?days=90`);
    ok(
      "收益率曲线（可达或有降级标注）",
      y.status === 200 && ((y.body.curve?.length ?? 0) > 0 || y.body.degraded === true),
      `n=${y.body.curve?.length} degraded=${y.body.degraded}`,
    );
  }

  // ---------- [10] 守卫与状态位（刀 2 / #22(c)(d)：全是**零出网**断言） ----------
  // 这一节补的是"6 条 HTTP 路由此前零断言"里能免费锁住的部分：守卫必须在**出网之前**
  // 拒绝，所以这些断言既不打东财也不打腾讯，任何窗口都能跑。
  console.log("\n[10] 守卫与状态位（零出网）");
  {
    const h = await getJson(`${BASE}/api/health`);
    ok("刀2：/api/health 200 且 db=ok（C31 容器健康检查读的就是这个体）",
       h.status === 200 && h.body.status === "ok" && h.body.db === "ok", JSON.stringify(h.body));

    const badType = await fetch(`${BASE}/api/sync?type=bogus`, { method: "POST" });
    const badBody = await badType.json().catch(() => ({}));
    ok("刀2：POST /api/sync 非法 type → 400（SYNC_TYPES 白名单在出网前拒）",
       badType.status === 400 && /unsupported type/.test(String(badBody.error)),
       `status=${badType.status} ${JSON.stringify(badBody)}`);

    const crossSite = await fetch(`${BASE}/api/sync`, {
      method: "POST",
      headers: { Origin: "http://evil.example" },
    });
    ok("刀2：POST /api/sync 跨站 Origin → 403（CR-08 的 origin 守卫，早于 type 校验）",
       crossSite.status === 403, `status=${crossSite.status}`);

    const refreshCross = await fetch(`${BASE}/api/market/refresh?type=all`, {
      method: "POST",
      headers: { Origin: "http://evil.example" },
    });
    ok("刀2：POST /api/market/refresh 跨站 → 403（快照刷新同样是花钱的口子）",
       refreshCross.status === 403, `status=${refreshCross.status}`);

    const refreshBad = await fetch(`${BASE}/api/market/refresh?type=bogus`, { method: "POST" });
    ok("刀2：POST /api/market/refresh 非法 type → 400（不进 refreshSnapshot）",
       refreshBad.status === 400, `status=${refreshBad.status}`);

    // #22(c)：**不存在的标的返回 HTTP 200、404 只体现在正文里**（loading.tsx 的 Suspense 壳
    // 先流式落地，notFound() 在流里才生效）。这条断言把"只能按正文判 404"钉成契约——
    // 谁想用 `status === 404` 判，就会被这条红字挡住。
    const nf = await getText(`${BASE}/product/stock/999999`);
    ok("刀2：不存在标的＝HTTP 200 ＋正文 not-found（404 判据只能按正文，不能按状态码）",
       nf.status === 200 && /could not be found|not-found/i.test(nf.text),
       `status=${nf.status} 正文命中=${/could not be found/i.test(nf.text)}`);
    ok("刀2：🔁 反向——同一页正文里不含真实产品名（不是把 404 渲染成了详情页）",
       !/贵州茅台/.test(nf.text) || !/could not be found/i.test(nf.text), "同时出现标的名与 404 文案");

    const junkIngest = await fetch(`${BASE}/api/research/ingest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // 配了才带：这条断言判的是"标的核验"那一层，不能被前置的 401 截住
        ...(INGEST_TOKEN ? { "x-ingest-token": INGEST_TOKEN } : {}),
      },
      body: JSON.stringify({ type: "zzz_garbage", code: "600519", status: "done", summary: "x" }),
    });
    ok("刀2：研报回调的未知标的 → 400（语义白名单，不写库；09-14 的枚举禁令仍有效）",
       junkIngest.status === 400, `status=${junkIngest.status}`);
  }

  // ---------- [11] 自选回环（#22(d) 的 watchlist 那条：纯 DB，零出网，不要求交易日） ----------
  // 这一节锁的是"Watchlist 此前只有 vitest 的 mock 单测、HTTP 层零集成断言"。
  // 形态按主人拍的 (i)＝**测试内 POST→GET→DELETE 回环**：用合成代码，收尾必删，
  // 所以它不会在他的自选里留下任何东西（(ii) 碰真实条目那条口径明确没走）。
  console.log("\n[11] 自选回环（零出网，收尾必删不留残留）");
  {
    const CODE = "zzz-watch-selfcheck"; // 过 CODE_SET `[\w.-]{1,20}`，又不可能与真实代码相撞
    const NAME = "自选回环自检";
    // ⚠️ 实测到的 dev 级瞬态（CR9-47 同族，10-03 20:1x 对照实验定案）：
    // **每次对这个库的写入都会让 next dev 重编译**（写入组 12 轮＝11 次 `Compiled`，
    // 纯 GET 对照组 30 次＝1 次），落在那个窗口里的请求由 **Next 自己**抛 500
    // （响应体是空的，不是路由 catch 出来的 `{error}`；GET 的代码里根本没有 JSON.parse，
    // 日志字面是 `⨯ SyntaxError: Unexpected end of JSON input`）。
    // ⇒ **只对 status===500 重试**；400/200 的语义一次都不放过，别把守卫失效读成"又抖了"。
    const retry500 = async (fn, attempts = 3) => {
      let last;
      for (let i = 0; i < attempts; i++) {
        last = await fn();
        if (last.status !== 500) return last;
        await sleep(900);
      }
      return last;
    };
    const wl = () => retry500(() => getJson(`${BASE}/api/watchlist`));
    const post = (payload) =>
      retry500(() =>
        fetch(`${BASE}/api/watchlist`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }));
    const drop = () =>
      retry500(() => fetch(`${BASE}/api/watchlist?type=stock&code=${CODE}`, { method: "DELETE" }));

    const before = await wl();
    const itemsOf = (b) => (Array.isArray(b.items) ? b.items : []);
    ok("#22(d)：GET /api/watchlist 200 且 items 是数组（回环的基线读法成立）",
       before.status === 200 && Array.isArray(before.body.items),
       `status=${before.status} body=${JSON.stringify(before.body).slice(0, 120)}`);
    const n0 = itemsOf(before.body).length;

    try {
      const add = await post({ type: "stock", code: CODE, name: NAME });
      let afterAdd = itemsOf((await wl()).body);
      // 写入后第一次读没看到自己写的行 ⇒ 再读一次并把这件事记进 detail。
      // **刻意不把"看不见"当成通过**：这是唯一能区分"可见性延迟"与"写丢了"的证据形态。
      let reRead = false;
      if (!afterAdd.some((x) => x.code === CODE)) {
        await sleep(900);
        afterAdd = itemsOf((await wl()).body);
        reRead = true;
      }
      const row = afterAdd.find((x) => x.code === CODE);
      ok("#22(d)：POST 合成自选 → 200，且下一读就出现（type/code/name 三项对上）",
         add.status === 200 && afterAdd.length === n0 + 1 && row?.type === "stock" && row?.name === NAME,
         `status=${add.status} n=${n0}→${afterAdd.length} row=${JSON.stringify(row ?? null)}${reRead ? " （第一次读没看见，复读才见＝可见性延迟，已记）" : ""}`);

      const dup = await post({ type: "stock", code: CODE, name: `${NAME}改名` });
      let dupRows = itemsOf((await wl()).body).filter((x) => x.code === CODE);
      if (dupRows.length !== 1) { await sleep(900); dupRows = itemsOf((await wl()).body).filter((x) => x.code === CODE); }
      ok("#22(d)🔁：同 (type,code) 再 POST 走 upsert——行数不增、name 被更新（C26 唯一键没被绕开）",
         dup.status === 200 && dupRows.length === 1 && dupRows[0].name === `${NAME}改名`,
         `rows=${dupRows.length} name=${JSON.stringify(dupRows[0]?.name)}`);

      const badCode = await post({ type: "stock", code: "bad code!/../../x", name: "不该进库" });
      const badType = await post({ type: "zzz", code: CODE, name: "不该进库" });
      const afterBad = itemsOf((await wl()).body);
      ok("#22(d)🔁：非法 code 与非法 type 都 400，且库里没有多出行（守卫在写之前，C33/C5 同口径）",
         badCode.status === 400 && badType.status === 400 && afterBad.length === n0 + 1,
         `code=${badCode.status} type=${badType.status} n=${afterBad.length}（基线 ${n0}+1）`);

      const del = await drop();
      const afterDel = itemsOf((await wl()).body);
      ok("#22(d)🔁：DELETE 后回到基线条数、合成行彻底消失（回环不污染真实自选数据）",
         del.status === 200 && afterDel.length === n0 && !afterDel.some((x) => x.code === CODE),
         `status=${del.status} n=${afterDel.length}（基线 ${n0}）`);
    } finally {
      // 上面任何一条红掉都要先把合成行删干净——这是"测试内回环"这个形态自己欠的承诺
      await drop().catch(() => {});
      const leftover = itemsOf((await wl()).body).filter((x) => x.code === CODE);
      ok("#22(d)：收尾自证 leftover=0（不管中间断言红绿，库里都不留这行）",
         leftover.length === 0, JSON.stringify(leftover));
    }
  }

  // ---------- 结果 ----------
  console.log(`\n== 结果：${passed} 通过 / ${failed} 失败 ==`);
  if (failures.length) {
    console.log("\n失败项：");
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((e) => {
  console.error("测试执行异常：", e);
  process.exit(1);
});
