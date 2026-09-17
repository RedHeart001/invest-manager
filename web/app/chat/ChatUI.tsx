"use client";

// 智能助手聊天界面（PLAN M4）：会话列表 + 流式回复（Markdown 渲染）+ 工具状态透明化（R5）
// LLM 未配置时展示明确指引（llm_not_configured 错误事件）

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type ChatItem = {
  id: number;
  role: "user" | "assistant" | "tool";
  content: string;
  chips?: string[];
};

// B5：稳定 key——每条消息创建时分配递增 id，流式追加不再靠数组下标定位
let msgSeq = 0;
function mkMsg(role: ChatItem["role"], content: string, extra?: { chips?: string[] }): ChatItem {
  return { id: msgSeq++, role, content, ...extra };
}

type SessionItem = { id: string; title: string; messageCount: number };

const TOOL_LABEL: Record<string, string> = {
  search_products: "搜索产品",
  get_quote: "查询行情",
  get_kline: "查询走势",
  get_hotspots: "查询热点",
  get_fund_holdings: "查询基金重仓",
  get_phase_analysis: "阶段分析",
};

// Markdown 渲染样式（表格/列表/代码的工整呈现）
const mdComponents = {
  table: (props: React.ComponentProps<"table">) => (
    <div className="my-3 overflow-x-auto">
      <table
        className="w-full border-collapse overflow-hidden rounded-lg text-[13px]"
        {...props}
      />
    </div>
  ),
  th: (props: React.ComponentProps<"th">) => (
    <th
      className="border border-zinc-200 bg-zinc-100 px-3 py-1.5 text-left font-medium text-zinc-700"
      {...props}
    />
  ),
  td: (props: React.ComponentProps<"td">) => (
    <td className="border border-zinc-200 px-3 py-1.5 text-zinc-700" {...props} />
  ),
  p: (props: React.ComponentProps<"p">) => (
    <p className="my-1.5 first:mt-0 last:mb-0" {...props} />
  ),
  ul: (props: React.ComponentProps<"ul">) => (
    <ul className="my-1.5 list-disc space-y-1 pl-5" {...props} />
  ),
  ol: (props: React.ComponentProps<"ol">) => (
    <ol className="my-1.5 list-decimal space-y-1 pl-5" {...props} />
  ),
  li: (props: React.ComponentProps<"li">) => <li className="leading-relaxed" {...props} />,
  strong: (props: React.ComponentProps<"strong">) => (
    <strong className="font-semibold text-zinc-900" {...props} />
  ),
  code: (props: React.ComponentProps<"code">) => (
    <code className="rounded bg-zinc-200/70 px-1 py-0.5 font-mono text-[12px]" {...props} />
  ),
  a: (props: React.ComponentProps<"a">) => (
    <a className="text-blue-600 hover:underline" target="_blank" rel="noreferrer" {...props} />
  ),
  h1: (props: React.ComponentProps<"h1">) => (
    <h1 className="my-2 text-base font-semibold" {...props} />
  ),
  h2: (props: React.ComponentProps<"h2">) => (
    <h2 className="my-2 text-[15px] font-semibold" {...props} />
  ),
  h3: (props: React.ComponentProps<"h3">) => (
    <h3 className="my-1.5 text-sm font-semibold" {...props} />
  ),
  blockquote: (props: React.ComponentProps<"blockquote">) => (
    <blockquote
      className="my-2 border-l-2 border-zinc-300 pl-3 text-zinc-500"
      {...props}
    />
  ),
};

export default function ChatUI() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // 研报推送按发起会话过滤（代码审查修复）：用 ref 避免订阅 effect 随会话重建
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const res = await fetch("/api/chat/sessions");
      const body = await res.json();
      setSessions((body.sessions ?? []) as SessionItem[]);
    } catch {
      // 忽略
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  // 研报完成推送（P5：SSE 广播 → 会话内提示，PLAN"任务完成后在同一会话推送"）
  useEffect(() => {
    const es = new EventSource("/api/hotspots/stream");
    es.addEventListener("research", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as {
          type: string;
          code: string;
          failed?: boolean;
          error?: string;
          rating?: string;
          summary?: string;
          sessionIds?: string[];
        };
        // 只认领自己会话的推送（代码审查修复：跨会话串消息）
        const sid = sessionIdRef.current;
        if (!sid || !data.sessionIds?.includes(sid)) return;
        // CR5-2（2026-09-17 review）：失败分支此前不判别，一律走下方成功渲染 →
        // rating 缺失回落"中性"、summary 为空，把"研究失败"显示成"已完成·中性"。
        // 服务端失败广播带 failed=true（lib/research.ts 的 else 分支）。
        if (data.failed) {
          setItems((prev) => [
            ...prev,
            mkMsg(
              "assistant",
              `⚠️ 深度研究未能完成（**${data.code}**）：${data.error ?? "未知原因"}\n\n可稍后在详情页「深度分析」区重试。`,
            ),
          ]);
          return;
        }
        setItems((prev) => [
          ...prev,
          mkMsg(
            "assistant",
            `📄 深度研究报告已完成：**${data.code}** 评级「${data.rating ?? "中性"}」\n\n${data.summary ?? ""}\n\n[查看完整研报 →](/product/${data.type}/${data.code}#research)`,
          ),
        ]);
      } catch {
        // 忽略坏消息
      }
    });
    return () => es.close();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, statusText]);

  const openSession = useCallback(async (id: string) => {
    setSessionId(id);
    setStatusText(null);
    setError(null);
    try {
      const res = await fetch(`/api/chat/sessions/${id}`);
      const body = await res.json();
      const msgs = (body.messages ?? []) as {
        role: string;
        content: string;
        name?: string;
      }[];
      const view: ChatItem[] = [];
      for (const m of msgs) {
        if (m.role === "tool") {
          const label = TOOL_LABEL[m.name ?? ""] ?? m.name ?? "工具";
          view.push(mkMsg("tool", "", { chips: [`${label} 完成`] }));
        } else {
          view.push(mkMsg(m.role as "user" | "assistant", m.content));
        }
      }
      setItems(view);
    } catch {
      setError("加载会话失败");
    }
  }, []);

  const newSession = useCallback(() => {
    setSessionId(null);
    setItems([]);
    setStatusText(null);
    setError(null);
  }, []);

  const removeSession = useCallback(
    async (id: string) => {
      await fetch(`/api/chat/sessions/${id}`, { method: "DELETE" });
      if (sessionId === id) newSession();
      void loadSessions();
    },
    [sessionId, loadSessions, newSession],
  );

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || streaming) return;
      setStreaming(true);
      setError(null);
      setStatusText("思考中…");
      setItems((prev) => [...prev, mkMsg("user", content)]);
      setInput("");

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sessionId: sessionId ?? undefined, message: content }),
        });
        if (!res.ok || !res.body) {
          throw new Error(`请求失败（${res.status}）`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let assistantStarted = false;

        const handleEvent = (event: string, dataRaw: string) => {
          let data: Record<string, unknown> = {};
          try {
            data = JSON.parse(dataRaw) as Record<string, unknown>;
          } catch {
            return;
          }
          if (event === "meta") {
            setSessionId(data.sessionId as string);
          } else if (event === "delta") {
            const c = data.content as string;
            setItems((prev) => {
              const last = prev[prev.length - 1];
              if (assistantStarted && last?.role === "assistant") {
                return [...prev.slice(0, -1), { ...last, content: last.content + c }];
              }
              assistantStarted = true;
              return [...prev, mkMsg("assistant", c)];
            });
          } else if (event === "status") {
            const name = String(data.name ?? "");
            setStatusText(`正在调用「${TOOL_LABEL[name] ?? name}」…`);
            setItems((prev) => {
              // 合并为单条工具状态行（调用 → 完成原地更新）
              const last = prev[prev.length - 1];
              if (last?.role === "tool") {
                return [
                  ...prev.slice(0, -1),
                  mkMsg("tool", "", { chips: [...(last.chips ?? []), `调用 ${TOOL_LABEL[name] ?? name}`] }),
                ];
              }
              return [...prev, mkMsg("tool", "", { chips: [`调用 ${TOOL_LABEL[name] ?? name}`] })];
            });
          } else if (event === "tool_result") {
            const ok = Boolean(data.ok);
            const name = String(data.name ?? "");
            const label = TOOL_LABEL[name] ?? name;
            const resultText = `${label} ${ok ? "完成" : "失败"}：${String(data.summary ?? "")}`;
            setStatusText(null);
            setItems((prev) => {
              // 原地把对应的「调用 X」chip 更新为「X 完成」
              for (let i = prev.length - 1; i >= 0; i--) {
                const it = prev[i];
                if (it.role !== "tool" || !it.chips) continue;
                const idx = it.chips.findIndex((c) => c === `调用 ${label}`);
                if (idx >= 0) {
                  const chips = [...it.chips];
                  chips[idx] = resultText;
                  return [...prev.slice(0, i), { ...it, chips }, ...prev.slice(i + 1)];
                }
              }
              return [...prev, mkMsg("tool", "", { chips: [resultText] })];
            });
          } else if (event === "intent") {
            setItems((prev) => [
              ...prev,
              mkMsg("assistant", `ℹ️ ${String(data.text ?? "")}`),
            ]);
          } else if (event === "warn") {
            // B3：服务端持久化失败等告警必须对用户可感知（此前该事件被丢弃）
            setItems((prev) => [
              ...prev,
              mkMsg("assistant", `⚠️ ${String(data.message ?? "该条消息可能未保存")}`),
            ]);
          } else if (event === "error") {
            setStatusText(null);
            setError(String(data.message ?? "发生错误"));
          } else if (event === "done") {
            setStatusText(null);
            void loadSessions();
          }
        };

        // 单一持续 read（race 超时不丢弃 in-flight 数据块）
        let pendingRead: Promise<ReadableStreamReadResult<Uint8Array>> | null = null;
        const readChunk = async (): Promise<ReadableStreamReadResult<Uint8Array> | null> => {
          if (!pendingRead) pendingRead = reader.read();
          const winner = await Promise.race([
            pendingRead.then((r) => ({ r }) as { r: ReadableStreamReadResult<Uint8Array> }),
            new Promise<null>((resolve) => setTimeout(() => resolve(null), 500)),
          ]);
          if (winner) {
            pendingRead = null;
            return winner.r;
          }
          return null;
        };

        let terminated = false;
        const deadline = Date.now() + 180_000;
        while (Date.now() < deadline && !terminated) {
          const rr = await readChunk();
          if (rr) {
            const { value, done } = rr;
            if (done) break;
            if (value) buffer += decoder.decode(value, { stream: true });
          }
          while (true) {
            const evIdx = buffer.indexOf("event:");
            if (evIdx < 0) break;
            const dataIdx = buffer.indexOf("data:", evIdx);
            if (dataIdx < 0) break;
            const evEnd = buffer.indexOf("\n", evIdx);
            const dataEnd = buffer.indexOf("\n", dataIdx);
            if (evEnd < 0 || dataEnd < 0 || dataEnd < evEnd) break;
            const ev = buffer.slice(evIdx + 6, evEnd).trim();
            const dataRaw = buffer.slice(dataIdx + 5, dataEnd).trim();
            buffer = buffer.slice(dataEnd + 1);
            handleEvent(ev, dataRaw);
          }
        }
        // 超时退出循环时释放流连接（2026-09-13 code review：否则连接滞留至服务端超时）
        try {
          reader.cancel();
        } catch {
          // 已关闭
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "发送失败");
      } finally {
        setStreaming(false);
        setStatusText(null);
      }
    },
    [sessionId, streaming, loadSessions],
  );

  return (
    <div className="flex gap-6">
      {/* 会话列表 */}
      <aside className="w-52 shrink-0">
        <button
          onClick={newSession}
          className="w-full rounded-lg border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-50"
        >
          + 新会话
        </button>
        <ul className="mt-3 space-y-1">
          {sessions.map((s) => (
            <li key={s.id} className="group flex items-center gap-1">
              <button
                onClick={() => openSession(s.id)}
                className={`flex-1 truncate rounded-lg px-2.5 py-1.5 text-left text-xs ${
                  sessionId === s.id
                    ? "bg-zinc-900 text-white"
                    : "text-zinc-600 hover:bg-zinc-100"
                }`}
                title={s.title}
              >
                {s.title}
                <span className="ml-1 opacity-60">{s.messageCount}</span>
              </button>
              <button
                onClick={() => removeSession(s.id)}
                className="px-1 text-xs text-zinc-300 opacity-0 transition group-hover:opacity-100 hover:text-red-500"
                title="删除会话"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* 对话区 */}
      <div className="flex min-h-[480px] flex-1 flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="max-h-[520px] flex-1 space-y-4 overflow-y-auto p-5">
          {items.length === 0 && (
            <div className="py-14 text-center">
              <p className="text-sm text-zinc-400">试试问我：</p>
              <div className="mt-3 flex flex-wrap justify-center gap-2">
                {["贵州茅台现在多少钱？", "最近有什么热点？", "110022 重仓了哪些股票？"].map(
                  (q) => (
                    <button
                      key={q}
                      onClick={() => void send(q)}
                      className="rounded-full border border-zinc-200 px-3 py-1.5 text-xs text-zinc-600 hover:border-zinc-400 hover:bg-zinc-50"
                    >
                      {q}
                    </button>
                  ),
                )}
              </div>
            </div>
          )}
          {items.map((m, i) =>
            m.role === "tool" ? (
              <div key={m.id} className="flex flex-wrap gap-1.5">
                {m.chips?.map((c, j) => (
                  <span
                    key={j}
                    className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] ${
                      c.includes("失败")
                        ? "border-red-200 bg-red-50 text-red-600"
                        : c.startsWith("调用 ")
                          ? "border-zinc-200 bg-zinc-50 text-zinc-500"
                          : "border-emerald-200 bg-emerald-50 text-emerald-700"
                    }`}
                  >
                    🔧 {c}
                  </span>
                ))}
              </div>
            ) : m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[75%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-blue-600 px-4 py-2.5 text-sm leading-relaxed text-white">
                  {m.content}
                </div>
              </div>
            ) : (
              <div key={m.id} className="flex">
                <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-zinc-100 bg-zinc-50 px-4 py-3 text-sm leading-relaxed text-zinc-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                    {m.content || "…"}
                  </ReactMarkdown>
                </div>
              </div>
            ),
          )}
          {statusText && (
            <div className="flex items-center gap-2 pl-1 text-xs text-zinc-400">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
              {statusText}
            </div>
          )}
          {error && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-700">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form
          className="flex gap-2 border-t border-zinc-200 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入问题…（Enter 发送）"
            className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {streaming ? "…" : "发送"}
          </button>
        </form>
      </div>
    </div>
  );
}
