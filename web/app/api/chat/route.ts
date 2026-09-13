import { NextRequest, NextResponse } from "next/server";

import { LlmNotConfiguredError, type LlmMessage, type LlmToolCall, chatStream } from "@/lib/llm";
import { buildSystemPrompt, executeAgentTool, getAgentTools } from "@/lib/gateway";
import { appendMessage, createSession, getMessages } from "@/lib/chat";
import { startResearch } from "@/lib/research";
import { trimContext } from "@/lib/context-budget";
import { prisma } from "@/lib/prisma";

// 统一 Agent 会话端点（PLAN M4）：SSE 流式输出 + function calling + 会话持久化
// 事件：meta / status（工具状态，R5 透明化）/ delta（正文增量）/ error / done
// P6：工具集与 system prompt 改由 Tool Gateway 提供（内置 + 技能 + MCP）
export const dynamic = "force-dynamic";

const MAX_TOOL_ROUNDS = 4;
const INTENT_RE = /深度分析|深度研究|研报|全面评估/;

export async function POST(req: NextRequest) {
  let body: { sessionId?: string; message?: string };
  try {
    body = (await req.json()) as { sessionId?: string; message?: string };
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const message = String(body.message ?? "").trim();
  if (!message) {
    return NextResponse.json({ error: "message is required" }, { status: 400 });
  }

  // 会话：有 id 校验存在，无 id 新建（标题取首句）
  let sessionId = body.sessionId ?? "";
  if (sessionId) {
    const exists = await prisma.chatSession.findUnique({ where: { id: sessionId } });
    if (!exists) sessionId = "";
  }
  if (!sessionId) {
    const s = await createSession(message);
    sessionId = s.id;
  }
  await appendMessage(sessionId, "user", message);

  const encoder = new TextEncoder();
  const sid = sessionId;

  const stream = new ReadableStream({
    async start(controller) {
      // 代码审查修复：客户端断连（req.signal abort）后 controller 已失效，
      // 此时再 enqueue/close 会抛二次异常并逃出 catch → 未处理异常。
      // 用 closed 标志把收尾路径变成幂等且不抛错的。
      let closed = false;
      const send = (event: string, data: unknown) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        } catch {
          closed = true; // 客户端已断开：静默停止推送
        }
      };
      try {
        // P6：技能命中判定（仅命中技能的正文进上下文，元信息常驻）
        const sys = buildSystemPrompt(message);
        // 工具集：内置（名字不变）+ 已连接的 MCP server 工具（不可用时自动降级为空）
        const tools = await getAgentTools();
        send("meta", { sessionId: sid, skills: sys.activeSkills, toolCount: tools.length });

        // 意图升档（PLAN M4/M5：关键词规则命中 → 真实触发 L2 深度研究）
        if (INTENT_RE.test(message)) {
          // 提取标的：6 位 A股代码优先，其次 3~5 位大写字母美股代码
          const codeMatch = message.match(/\b(\d{6})\b/) ?? message.match(/\b([A-Z]{3,5})\b/);
          if (codeMatch) {
            const code = codeMatch[1];
            const type = /^\d{6}$/.test(code) ? "stock" : "us";
            try {
              const result = await startResearch(type, code, undefined, sid);
              if (result.status === "done") {
                send("intent", {
                  text: `识别到深度分析意图：${code} 今日研报已完成（评级：${result.report.rating}），已可用 get_research_report 获取。`,
                });
              } else if (result.status === "running") {
                send("intent", {
                  text: `已启动深度研究（${code}，约 2~5 分钟）。完成后会在此会话推送研报结果；详情页「深度分析」区也可实时查看。`,
                });
              } else {
                send("intent", { text: `深度研究未启动：${result.reason ?? "未知原因"}` });
              }
            } catch (e) {
              send("intent", {
                text: `深度研究启动失败：${e instanceof Error ? e.message : "unknown"}`,
              });
            }
          } else {
            send("intent", {
              text: "识别到深度分析意图：请提供具体标的代码（A股 6 位数字，如 600519；美股如 AAPL），我将自动启动深度研究。",
            });
          }
        }

        // 组装 LLM 消息（系统提示 + 历史 + 本轮用户消息）
        const history = await getMessages(sid);
        const messages: LlmMessage[] = [
          { role: "system", content: sys.prompt },
          ...history.map((m): LlmMessage => {
            if (m.role === "assistant" && m.toolCalls) {
              return {
                role: "assistant",
                content: m.content || null,
                tool_calls: m.toolCalls as LlmToolCall[],
              };
            }
            if (m.role === "tool") {
              return { role: "tool", content: m.content, tool_call_id: m.toolCallId ?? "call", name: m.name };
            }
            return { role: m.role, content: m.content };
          }),
        ];

        // M1：按字符预算裁剪历史（防长会话撑爆 LLM 上下文）
        const trimmedMessages = trimContext(messages);

        let assistantText = "";
        let lastToolCalls: LlmToolCall[] | undefined;

        // 持久化容错：单条消息写库失败不阻塞对话主流程（R10），但记录诊断
        const safeAppend = async (
          role: "user" | "assistant" | "tool",
          content: string,
          extra?: { toolCalls?: unknown; toolCallId?: string; name?: string },
        ) => {
          try {
            await appendMessage(sid, role, content, extra);
          } catch (e) {
            const sessionExists = await prisma.chatSession.findUnique({
              where: { id: sid },
              select: { id: true },
            });
            console.error(
              `[chat] appendMessage(${role}) failed: ${e instanceof Error ? e.message.slice(0, 120) : e} | sid=${sid} sessionExists=${Boolean(sessionExists)}`,
            );
            // B3：持久化失败对用户可感知（前端显示"该条可能未保存"），不再静默
            send("warn", { message: "消息保存失败（本条可能不会在历史中出现）", role });
          }
        };

        for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
          console.log(`[chat] round ${round} start`);
          let roundText = "";
          const toolCallsThisRound: LlmToolCall[] = [];

          for await (const chunk of chatStream({
            messages: trimmedMessages,
            tools,
            signal: req.signal,
          })) {
            if (chunk.type === "delta") {
              roundText += chunk.content;
              send("delta", { content: chunk.content });
            } else if (chunk.type === "tool_calls") {
              toolCallsThisRound.push(...chunk.toolCalls);
            }
          }

          if (toolCallsThisRound.length === 0) {
            assistantText += roundText;
            console.log(`[chat] round ${round} finished (no tool calls), textLen=${roundText.length}`);
            break;
          }
          console.log(`[chat] round ${round} requested ${toolCallsThisRound.length} tool(s)`);

          // 模型请求工具：记录 assistant 消息 → 逐个执行 → 追加 tool 消息 → 继续下一轮
          assistantText += roundText;
          lastToolCalls = toolCallsThisRound;
          messages.push({
            role: "assistant",
            content: roundText || null,
            tool_calls: toolCallsThisRound,
          });
          await safeAppend("assistant", roundText, { toolCalls: toolCallsThisRound });

          for (const tc of toolCallsThisRound) {
            let args: Record<string, unknown> = {};
            try {
              args = JSON.parse(tc.function.arguments || "{}") as Record<string, unknown>;
            } catch {
              args = {};
            }
            send("status", { name: tc.function.name, args });
            const result = await executeAgentTool(tc.function.name, args);
            send("tool_result", {
              name: tc.function.name,
              ok: result.ok,
              summary: result.summary,
            });
            const toolContent = JSON.stringify(result).slice(0, 4000); // token 经济
            messages.push({
              role: "tool",
              content: toolContent,
              tool_call_id: tc.id,
              name: tc.function.name,
            });
            await safeAppend("tool", toolContent, {
              toolCallId: tc.id,
              name: tc.function.name,
            });
          }
        }

        await safeAppend("assistant", assistantText);
        send("done", { sessionId: sid });
      } catch (e) {
        console.error("[chat] route error:", e instanceof Error ? `${e.name}: ${e.message}` : e);
        if (e instanceof LlmNotConfiguredError) {
          send("error", {
            code: "llm_not_configured",
            message:
              "LLM 未配置：请在 web/.env 设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL（DeepSeek/GLM 等 OpenAI 兼容端点），保存后重启 dev server 生效。会话与消息已保存。",
          });
        } else {
          send("error", { message: e instanceof Error ? e.message : "chat failed" });
        }
      } finally {
        if (!closed) {
          closed = true;
          try {
            controller.close();
          } catch {
            // 客户端已断开导致的关闭异常：忽略
          }
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
