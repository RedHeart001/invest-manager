// ChatUI SSE 流退出形态判定（CR7-5，2026-09-24）
//
// 背景：ChatUI 的 while 循环此前有一个从未被赋值的 `terminated` 死守卫；
// deadline 到点退出后直接 cancel reader——用户看到的是**一半的回答被当作
// 正常结束**（R17：长时运行态必须如实呈现且可退出）。
//
// 四种退出形态：
// - done = 正常完成
// - 服务端已发 error = 已有权威原因（CR9-2：不得被通用文案覆盖）
// - 未 done+到期 = deadline 中断（回答可能不完整，须提示并给重发出口）
// - 未 done+未到期 = 异常退出（流被服务端掐断等）
//
// 本模块保持**零依赖**以便单测（与 research-stale.ts 同套路：客户端组件
// 不得 import 牵连 prisma 的模块）。

export type StreamExitInput = { gotDone: boolean; expired: boolean; sawError?: boolean };

export type StreamExitKind = "completed" | "errored" | "interrupted" | "abnormal";

export function classifyStreamExit({
  gotDone,
  expired,
  sawError = false,
}: StreamExitInput): StreamExitKind {
  if (gotDone) return "completed";
  // CR9-2（2026-09-26）：服务端 error 事件已给出可行动原因（如"LLM 未配置…重启生效"），
  // 此处必须让调用方跳过通用文案，否则真因被"连接中断"覆盖（R16 违例）。
  if (sawError) return "errored";
  return expired ? "interrupted" : "abnormal";
}
