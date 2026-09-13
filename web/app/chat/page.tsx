import ChatUI from "./ChatUI";

// 智能助手（PLAN M4：统一会话入口 /chat，流式输出 + function calling）
export const dynamic = "force-dynamic";

export default function ChatPage() {
  return (
    <main className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight">智能助手</h1>
      <p className="mt-1 text-sm text-zinc-500">
        支持自然语言查行情、搜产品、看热点与阶段分析（L1 工具）；回答基于真实数据，不构成投资建议
      </p>

      <div className="mt-6">
        <ChatUI />
      </div>

      <p className="mt-6 text-xs text-zinc-400">
        助手回复由 AI 生成，行情数据来自外部数据源（可能延迟）；内容仅供参考，不构成投资建议。
      </p>
    </main>
  );
}
