"use client";

// CR7-3/B1（2026-09-24 拍板方案 ①）：详情页「双源核对」按钮。
// R13 的交付形态——按需触发（不默认调用，不放大外部请求），主源与备源
// 各取一次同一指标做交叉比对，差异超阈值时**显式标注来源与偏差**。
// R16：备源不可用/核对失败如实展示 note，不静默装作一致。

import { useState } from "react";

type VerifiedResp = {
  price?: number | null;
  source?: string;
  note?: string | null;
  crossChecked?: boolean;
  error?: string;
};

export default function VerifyQuoteButton({ type, code }: { type: string; code: string }) {
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<VerifiedResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setPending(true);
    setError(null);
    try {
      const res = await fetch(`/api/quote/verify?type=${encodeURIComponent(type)}&code=${encodeURIComponent(code)}`);
      const b = (await res.json()) as VerifiedResp;
      if (!res.ok) {
        setError(b.error ?? `核对失败（${res.status}）`);
        setResult(null);
      } else {
        setResult(b);
      }
    } catch {
      setError("核对请求失败（网络/服务不可达）");
    } finally {
      setPending(false);
    }
  };

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={run}
        disabled={pending}
        className="rounded-lg border border-zinc-300 px-2.5 py-1 text-xs text-zinc-600 transition hover:border-zinc-400 hover:text-zinc-800 disabled:opacity-50"
      >
        {pending ? "核对中…" : "双源核对"}
      </button>
      {result && (
        <span
          className={`text-xs ${result.note?.includes("偏差") ? "text-amber-600" : "text-zinc-500"}`}
          data-testid="verify-note"
        >
          {result.note ??
            (result.crossChecked
              ? "双源一致（无备注）"
              : "无双源可比对（备源不可用或该类型无备源）")}
        </span>
      )}
      {error && <span className="text-xs text-red-500">{error}</span>}
    </span>
  );
}
