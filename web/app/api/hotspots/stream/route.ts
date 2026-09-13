import { NextRequest } from "next/server";

import { clientCount, registerClient, unregisterClient } from "@/lib/sse";

// SSE 流（P3 补强：通用基础设施，P4 流式对话复用）
// 心跳 15s；客户端断线由浏览器 EventSource 自动重连（retry 3000ms）
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const encoder = new TextEncoder();
  const id = crypto.randomUUID();

  const stream = new ReadableStream({
    start(controller) {
      const send = (chunk: string) => controller.enqueue(encoder.encode(chunk));
      send(`retry: 3000\n\n`);
      send(
        `event: hello\ndata: ${JSON.stringify({ ok: true, clients: clientCount() + 1 })}\n\n`,
      );
      registerClient(id, send);

      const heartbeat = setInterval(() => {
        try {
          send(`: hb ${Date.now()}\n\n`);
        } catch {
          clearInterval(heartbeat);
          unregisterClient(id);
        }
      }, 15_000);

      req.signal.addEventListener("abort", () => {
        clearInterval(heartbeat);
        unregisterClient(id);
        try {
          controller.close();
        } catch {
          // 已关闭
        }
      });
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
