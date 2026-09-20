import { NextRequest, NextResponse } from "next/server";

import { LlmNotConfiguredError, type LlmMessage, type LlmToolCall, chatStream } from "@/lib/llm";
import { buildSystemPrompt, executeAgentTool, getAgentTools } from "@/lib/gateway";
import { appendMessage, createSession, getMessages } from "@/lib/chat";
import { repairToolPairing } from "@/lib/chat-history";
import { startResearch } from "@/lib/research";
import { extractResearchTarget } from "@/lib/research-target";
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
  // CR5-P3（2026-09-17 review）：入参长度上限——message 直接入库并送 LLM，
  // 无界会让超长输入撑爆上下文与库。
  const message = String(body.message ?? "").trim().slice(0, 4000);
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
          // 提取标的（见 lib/research-target.ts：6 位 A股优先，美股排除常规缩写）
          const target = extractResearchTarget(message);
          if (target) {
            const { code, type } = target;
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
        // CR-01（本轮 code review）：历史条目可能因"取最近 200 条"窗口切割、
        // 或 safeAppend 单条失败而出现**孤立 tool 消息 / tool_calls 无回应**，
        // OpenAI 兼容端点会一律 400 且该会话此后不可用。故先做配对修复。
        const history = repairToolPairing(await getMessages(sid));
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
              // 修复后仍走到这里的 tool 消息必带 toolCallId（否则已被丢弃）；
              // 兜底不再写常量 "call"（那会与 assistant 声明的 id 不匹配 → 400）。
              return { role: "tool", content: m.content, tool_call_id: m.toolCallId ?? "", name: m.name };
            }
            return { role: m.role, content: m.content };
          }),
        ];

        // M1：按字符预算裁剪历史（防长会话撑爆 LLM 上下文）
        // 注意：裁剪在**每轮工具循环内**执行（见下），此处不再预先计算一次性快照

        let lastToolCalls: LlmToolCall[] | undefined;
        let finishedByNatural = false; // CR4（P2-1）：自然结束（某轮无工具调用）与否

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
          if (process.env.LLM_DEBUG === "1") console.log(`[chat] round ${round} start`);
          let roundText = "";
          const toolCallsThisRound: LlmToolCall[] = [];

          // 修复（2026-09-13 code review）：必须在**每轮**重新裁剪——
          // 此前只在循环外算一次，超预算时 trimContext 返回新数组，
          // 之后 push 进 messages 的工具结果不会出现在发给 LLM 的数组里
          // → 模型看不到工具输出，多轮 function calling 静默失效。
          for await (const chunk of chatStream({
            messages: trimContext(messages),
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
            // CR4（P2-2）：最终答案只在此处落库一次——此前循环结束又 write
            // 历轮累加的 assistantText，导致中间轮文本在 DB 存两遍。此处
            // 无工具调用，整段 roundText 即最终回答。
            await safeAppend("assistant", roundText);
            finishedByNatural = true;
            if (process.env.LLM_DEBUG === "1")
              console.log(`[chat] round ${round} finished (no tool calls), textLen=${roundText.length}`);
            break;
          }
          if (process.env.LLM_DEBUG === "1")
            console.log(`[chat] round ${round} requested ${toolCallsThisRound.length} tool(s)`);

          // 模型请求工具：记录 assistant 消息 → 逐个执行 → 追加 tool 消息 → 继续下一轮
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

        // CR4（P2-1）：工具循环跑满 MAX_TOOL_ROUNDS 仍以工具调用结束时，最后一轮
        // 工具结果从未发给 LLM 总结 → 用户看到工具都跑了却没有最终回答。追加一次
        // 不带 tools 的收尾调用，强制模型基于已有结果作答。
        if (!finishedByNatural && lastToolCalls && lastToolCalls.length > 0) {
          if (process.env.LLM_DEBUG === "1")
            console.log("[chat] tool rounds exhausted, running final summary call");
          let tail = "";
          for await (const chunk of chatStream({
            messages: trimContext(messages),
            signal: req.signal,
          })) {
            if (chunk.type === "delta") {
              tail += chunk.content;
              send("delta", { content: chunk.content });
            }
          }
          if (tail.trim()) {
            await safeAppend("assistant", tail);
          } else {
            send("warn", { message: "已达工具调用上限且未生成最终回答，部分结果可能不完整" });
          }
        }
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
