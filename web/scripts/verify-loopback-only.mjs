// 仅供 verify-isolated 子进程使用：拒绝非回环网络连接，防止验收误触真实上游。
// Node 的模块加载钩子在 Next dev server 初始化前安装，http/https/fetch 均覆盖。
import net from "node:net";
import tls from "node:tls";

const loopback = new Set(["127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"]);
const violations = [];
const originalConnect = net.Socket.prototype.connect;

function guard(args, kind) {
  // Node 26 在 Windows 会把 options 规范化成 [[options, normalizedArgs]]。
  // 其余版本仍可能是 (options)、(port, host) 或 (port, options)。
  const flat = args.length === 1 && Array.isArray(args[0]) ? args[0] : args;
  const first = flat[0];
  const options = typeof first === "object" && first !== null ? first
    : typeof flat[1] === "object" && flat[1] !== null ? flat[1] : null;
  const host = options ? options.host ?? options.hostname
    : typeof flat[1] === "string" ? flat[1] : undefined;
  const normalized = String(host ?? "").replace(/^\[|\]$/g, "").toLowerCase();
  if (!loopback.has(normalized)) {
    const violation = `[verify-loopback-only] blocked ${kind} host=${normalized || "<empty>"}`;
    violations.push(violation);
    console.error(violation);
    const error = new Error(violation);
    error.code = "VERIFY_NON_LOOPBACK_BLOCKED";
    throw error;
  }
  return args;
}

net.Socket.prototype.connect = function (...args) {
  return originalConnect.apply(this, guard(args, "tcp"));
};
tls.connect = new Proxy(tls.connect, {
  apply(target, thisArg, args) {
    return Reflect.apply(target, thisArg, guard(args, "tls"));
  },
});

// Node 内置 fetch、http/https 与常见 HTTP 客户端最终都经 net/tls；因此无需替换
// Next 的 fetch，也不会把合成响应误当成真实上游。

process.on("exit", () => {
  if (violations.length > 0) {
    console.error(`[verify-loopback-only] ${violations.length} non-loopback attempt(s) blocked`);
  }
});
