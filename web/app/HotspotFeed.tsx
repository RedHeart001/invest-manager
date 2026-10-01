"use client";

// 热点卡片流（P3 / M1：dashboard + SSE 实时推送 + 手动触发）
// R5：所有等待均有可见状态；降级状态在页头显式标注一次（R12/R10，CR8-1 起不再逐卡重复）

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import type { DigestRow } from "@/lib/hotspots";

// 北京时间 HH:mm（代码审查修复）：此前直接 slice(11,16) 解析 ISO（UTC），
// 显示比北京时间早 8 小时。
const BEIJING_TIME_FMT = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function beijingTimeOf(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "--:--" : BEIJING_TIME_FMT.format(d);
}

// 外部新闻链接协议白名单（安全）：sourceUrls 来自抓取的第三方内容，
// 未过滤时 `javascript:` / `data:` 链接会在本页执行脚本。
function isSafeUrl(u: string): boolean {
  try {
    const parsed = new URL(u);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

const SOURCE_LABEL: Record<string, string> = {
  tavily: "Tavily 搜索",
  cls: "财联社电报",
  "eastmoney-news": "东财快讯",
  none: "无来源",
};

const ENGINE_LABEL: Record<string, string> = {
  llm: "LLM 结构化",
  keyword: "关键词规则",
  none: "未结构化",
};

// CR8-8：单卡 related 实测最多 16 个（`lib/hotspots.ts` 的 `out.slice(0, 16)`），
// 全渲染时一张卡占 4 行、长基金名（"广发创新药ETF联接A 012737"）把版面撑散。
// 默认只出前 6 个、其余收进「+N 更多」⇒ 信息不丢（可展开）但密度可控。
// 截断放在前端还有一层意义：**历史批次已落库的 16 个不必重写也会立刻变干净**。
const RELATED_SHOWN = 6;

function RelatedChips({ related }: { related: DigestRow["related"] }) {
  const [open, setOpen] = useState(false);
  const extra = related.length - RELATED_SHOWN;
  const shown = open ? related : related.slice(0, RELATED_SHOWN);

  return (
    <div className="mt-3">
      <p className="text-[11px] text-zinc-400">相关产品（板块成分映射 / 板块名基金匹配）</p>
      <div className="mt-1.5 flex flex-wrap gap-2">
        {shown.map((p) => (
          <Link
            key={`${p.type}:${p.code}`}
            href={`/product/${p.type}/${p.code}?from=home`}
            className="rounded border border-zinc-200 px-2 py-1 text-xs text-zinc-700 hover:border-zinc-400 hover:bg-zinc-50"
          >
            {p.name}
            <span className="ml-1 text-zinc-400">{p.code}</span>
            {p.type === "fund" && (
              <span className="ml-1 text-[10px] text-blue-500">基金</span>
            )}
          </Link>
        ))}
        {extra > 0 && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="rounded border border-dashed border-zinc-300 px-2 py-1 text-xs text-zinc-500 hover:border-zinc-500 hover:text-zinc-800"
          >
            {open ? "收起" : `+${extra} 更多`}
          </button>
        )}
      </div>
    </div>
  );
}

export default function HotspotFeed({
  initialDate,
  initialRows,
}: {
  initialDate: string | null;
  initialRows: DigestRow[];
}) {
  const [rows, setRows] = useState<DigestRow[]>(initialRows);
  const [date, setDate] = useState<string | null>(initialDate);
  const [connected, setConnected] = useState(false);
  const [pending, setPending] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  // CR4（P3）：触发轮询期间的卸载取消标志
  const pollAliveRef = useRef(true);
  useEffect(() => () => {
    pollAliveRef.current = false;
  }, []);

  const refresh = useCallback(async () => {
    setPending(true);
    setError(null);
    try {
      const res = await fetch(`/api/hotspots?date=${date ?? ""}&limit=30`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? res.statusText);
      setRows((body.rows ?? []) as DigestRow[]);
      setDate((body.date ?? null) as string | null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "刷新失败");
    } finally {
      setPending(false);
    }
  }, [date]);

  // ref 保存最新 refresh：SSE 订阅 effect 不因 refresh 变化重建（避免反复断连）
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  // SSE 订阅：新 digest 实时插入（去重）
  useEffect(() => {
    const es = new EventSource("/api/hotspots/stream");
    esRef.current = es;
    es.addEventListener("digest", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as {
          date: string;
          rows: DigestRow[];
        };
        setRows((prev) => {
          const seen = new Set(prev.map((r) => r.id));
          const fresh = (data.rows ?? []).filter((r) => !seen.has(r.id));
          if (fresh.length === 0) return prev;
          return [...fresh, ...prev];
        });
        // 副作用移出 state updater（代码审查修复）：updater 必须纯，
        // StrictMode 双调用会触发重复的 flash / 日期抖动
        setDate(data.date);
        setFlash("收到新热点");
      } catch {
        // 忽略坏消息
      }
    });
    // 断线重连后补拉（代码审查修复）：此前 onopen 只置连接状态，断线期间的
    // digest 会漏掉，与 /api/hotspots/stream 的注释承诺不符
    es.onopen = () => {
      setConnected(true);
      void refreshRef.current?.();
    };
    es.onerror = () => setConnected(false);
    return () => {
      es.close();
      esRef.current = null;
    };
  }, []);

  const trigger = useCallback(async () => {
    setTriggering(true);
    setError(null);
    setFlash(null);
    try {
      // 代码审查修复：改走 BFF 代理（此前浏览器直连 data-service，而 P7 容器化
      // 后 data-service 故意不发布端口 → 按钮必然失效）
      // M4：后端改为异步执行——POST 立即返回 accepted，进度经 status 轮询
      const res = await fetch("/api/hotspots/run", { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? body.error ?? res.statusText);
      if (body.accepted === false) {
        setFlash("已有热点任务在执行中");
        setTriggering(false);
        return;
      }
      setFlash("已提交后台抓取，执行中…");

      // 轮询调度状态：running=true → false 即完成（上限 4 分钟）
      const startedAt = Date.now();
      let sawRunning = false;
      for (;;) {
        // CR4（P3）：卸载后停止轮询（此前循环在组件卸载后仍每 3s 请求直到上限）
        if (!pollAliveRef.current) break;
        if (Date.now() - startedAt > 240_000) {
          setFlash("抓取超时（仍在后台执行，可稍后刷新查看）");
          break;
        }
        await new Promise((r) => setTimeout(r, 3000));
        const st = await fetch("/api/hotspots/status");
        if (!st.ok) continue;
        const sb = (await st.json()) as {
          running?: boolean;
          lastResult?: { topics?: number; ingested?: number; newsSource?: string; note?: string; error?: string } | null;
        };
        if (sb.running) {
          sawRunning = true;
          continue;
        }
        // CR5-P5（2026-09-17 review）：只在观测到 running 后才给"完成"文案——
        // sawRunning 为 false 时 lastResult 可能是**上一次**运行的残留，用它会误报。
        if (sawRunning) {
          const lr = sb.lastResult ?? {};
          if (lr.error) {
            setError(`抓取失败：${lr.error}`);
          } else {
            setFlash(
              `抓取完成：${lr.topics ?? 0} 条热点 · 来源 ${lr.newsSource ?? "-"}${lr.note ? ` · ${String(lr.note).slice(0, 80)}` : ""}`,
            );
          }
        } else {
          // 未观测到 running（任务极快或已被其他触发完成）：不谎报完成态，只提示已刷新
          setFlash("已刷新热点列表");
        }
        // 但无论是否观测到 running 都要拉一次：任务可能在首个 3s 轮询前就已完成
        // （sawRunning 恒 false），此前会直接 break 导致界面停留在"已提交"。
        await refresh();
        break;
      }
    } catch (e) {
      setError(
        `触发失败：${e instanceof Error ? e.message : "unknown"}（请确认 data-service 已启动）`,
      );
    } finally {
      setTriggering(false);
    }
  }, [refresh]);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 8000);
    return () => clearTimeout(t);
  }, [flash]);

  // CR8-1：② 引擎退化 / ① 新闻源降级收进页头，一批只显示一次（旧版逐卡重复 N 条）。
  // 存量行的 note 仍可能含 ③ 板块名未命中——读侧不靠文案猜成因，下一次真跑起才干净。
  const batchNotes = Array.from(
    new Set(
      rows
        .filter((r) => r.degraded)
        .map((r) => r.note)
        .filter((n): n is string => Boolean(n)),
    ),
  );

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              connected ? "bg-green-500" : "bg-zinc-300"
            }`}
          />
          {connected ? "实时推送已连接" : "实时推送未连接（自动重连中）"}
        </span>
        <span>·</span>
        <span>{date ? `数据日期：${date}` : "暂无数据"}</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={refresh}
            disabled={pending || triggering}
            className="rounded border border-zinc-300 px-3 py-1 hover:bg-zinc-50 disabled:opacity-50"
          >
            {pending ? "刷新中…" : "刷新"}
          </button>
          <button
            onClick={trigger}
            disabled={pending || triggering}
            className="rounded bg-zinc-900 px-3 py-1 text-white hover:bg-zinc-700 disabled:opacity-50"
          >
            {triggering ? "抓取中…" : "立即抓取热点"}
          </button>
        </div>
      </div>

      {batchNotes.length > 0 && (
        <p className="mt-2 text-[11px] text-zinc-400" title={batchNotes.join(" / ")}>
          产出说明：{batchNotes.slice(0, 2).join(" / ")}
          {batchNotes.length > 2 ? ` 等 ${batchNotes.length} 条` : ""}
        </p>
      )}

      {flash && <p className="mt-2 text-xs text-blue-600">{flash}</p>}
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      {rows.length === 0 ? (
        <div className="mt-6 rounded-xl border border-dashed border-zinc-300 bg-white/50 p-10 text-center">
          <p className="text-sm text-zinc-500">今日暂无热点数据</p>
          <p className="mt-2 text-xs text-zinc-400">
            点击「立即抓取热点」手动触发（自动任务：工作日盘前 08:30 / 盘后 16:30）
          </p>
        </div>
      ) : (
        <ul className="mt-4 space-y-4">
          {rows.map((r) => (
            <li
              key={r.id}
              className="rounded-xl border border-zinc-200 bg-white p-5"
            >
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-base font-semibold tracking-tight text-zinc-900">
                  {r.title}
                </h2>
                <div className="shrink-0 text-right text-[11px] text-zinc-400">
                  <div>{beijingTimeOf(r.createdAt)}</div>
                  <div>
                    {SOURCE_LABEL[r.newsSource ?? ""] ?? r.newsSource ?? "-"} ·{" "}
                    {ENGINE_LABEL[r.engine ?? ""] ?? r.engine ?? "-"}
                  </div>
                </div>
              </div>

              {r.summary && (
                <p className="mt-2 text-sm leading-relaxed text-zinc-600">{r.summary}</p>
              )}

              {r.boardTags.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {r.boardTags.map((t) => (
                    <Link
                      key={t}
                      href={`/search?q=${encodeURIComponent(t)}`}
                      className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-600 hover:bg-blue-100"
                    >
                      {t}
                    </Link>
                  ))}
                </div>
              )}

              {r.related.length > 0 && <RelatedChips related={r.related} />}

              <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
                {(r.related ?? []).length > 0 ? (
                  <Link
                    href={`/product/${r.related[0].type}/${r.related[0].code}?from=home#research`}
                    className="rounded bg-zinc-900 px-3 py-1 font-medium text-white hover:bg-zinc-700"
                  >
                    {/* CR8-2：原名「深度解读」名不副实——它只是跳 related[0] 详情页的
                        #research 锚点，不触发分析、不带这条热点的上下文。拍板＝只改名，
                        把目标标的写进按钮，接口与跳转一律不动。 */}
                    去分析 {r.related[0].name}
                  </Link>
                ) : (
                  <button
                    disabled
                    title="无相关产品，无法定位标的"
                    className="rounded bg-zinc-100 px-3 py-1 text-zinc-400"
                  >
                    去分析
                  </button>
                )}
                {/* CR8-1：逐卡「降级产出」横幅已删。旧契约把三类不相干成因 OR 成一条
                    note 并复制到每张卡（同批次互相重复），③ 板块名未命中这类纯噪声
                    因此满屏可见。现在 ①② 收进页头小字显示一次、③ 不再进落库契约。 */}
              </div>

              {/* CR8-3：来源链接独立成行，用标题而不是三个无差别的「原文」。
                  存量行没有标题（老契约只存 URL）⇒ 回退显示「原文」，不是回归。 */}
              {r.sourceUrls.filter((s) => isSafeUrl(s.url)).length > 0 && (
                <div className="mt-3">
                  <p className="text-[11px] text-zinc-400">相关文章</p>
                  <ul className="mt-1.5 space-y-1">
                    {r.sourceUrls
                      .filter((s) => isSafeUrl(s.url))
                      .slice(0, 3)
                      .map((s) => (
                        <li key={s.url} className="min-w-0">
                          <a
                            href={s.url}
                            target="_blank"
                            rel="noreferrer"
                            title={s.title || s.url}
                            className="block truncate text-xs text-blue-600 hover:underline"
                          >
                            {s.title || "原文"}
                          </a>
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
