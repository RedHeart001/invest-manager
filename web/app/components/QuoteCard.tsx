"use client";

import { useEffect, useState } from "react";

type Quote = {
  type: string;
  code: string;
  name?: string;
  price: number | null;
  change?: number | null;
  changePct?: number | null;
  source?: string;
  timestamp?: string | null;
};

export default function QuoteCard({
  type,
  code,
  name,
}: {
  type: string;
  code: string;
  name: string;
}) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetch(`/api/quote?type=${type}&code=${code}`)
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.error ?? res.statusText);
        return body as Quote;
      })
      .then((q) => {
        if (alive) setQuote(q);
      })
      .catch((e: Error) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [type, code]);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex items-baseline justify-between">
        <div>
          <span className="text-lg font-semibold">{name}</span>
          <span className="ml-2 text-sm text-zinc-400">{code}</span>
        </div>
        <span className="rounded bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500">
          {type}
        </span>
      </div>

      <div className="mt-4">
        {loading ? (
          <p className="text-sm text-zinc-400">加载中…</p>
        ) : error ? (
          <p className="text-sm text-red-500">{error}</p>
        ) : quote ? (
          <div className="flex items-baseline gap-4">
            <span className="text-3xl font-bold tabular-nums">
              {quote.price?.toFixed(2) ?? "--"}
            </span>
            {quote.changePct != null && (
              <span
                className={`text-sm font-medium ${
                  quote.changePct >= 0 ? "text-red-600" : "text-green-600"
                }`}
              >
                {quote.changePct >= 0 ? "+" : ""}
                {quote.changePct.toFixed(2)}%
              </span>
            )}
          </div>
        ) : null}
      </div>

      {quote?.source && (
        <p className="mt-3 text-xs text-zinc-400">
          来源：{quote.source}
          {quote.timestamp ? ` · ${quote.timestamp}` : ""}
        </p>
      )}
    </div>
  );
}
