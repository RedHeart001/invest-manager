import { PrismaClient } from "@prisma/client";

// CR-04（本轮 code review）：SQLite 单文件库 + Prisma 连接池，
// `busy_timeout` 是**连接级**参数——只在执行它的那条连接生效，
// 其余连接遇写锁立即 SQLITE_BUSY（正是下方 WAL 想消除的问题）。
// 对策：强制 `connection_limit=1`，使连接池只有一条连接，启动时的 PRAGMA
// 覆盖全池。经 `datasourceUrl` 注入（而非改 .env），dev（file:./dev.db）与
// 容器（file:/app/data/dev.db）两种 DATABASE_URL 都统一生效；已显式配置
// connection_limit 时不覆盖，尊重用户设置。
export function datasourceUrl(raw = process.env.DATABASE_URL): string | undefined {
  if (!raw) return undefined;
  if (/[?&]connection_limit=/.test(raw)) return raw;
  return raw.includes("?") ? `${raw}&connection_limit=1` : `${raw}?connection_limit=1`;
}

const globalForPrisma = globalThis as unknown as {
  prisma?: PrismaClient;
};

const dsUrl = datasourceUrl();
export const prisma = globalForPrisma.prisma ?? new PrismaClient(dsUrl ? { datasourceUrl: dsUrl } : undefined);

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;

// CR-04（本轮 code review）：SQLite 默认 journal_mode=delete，写事务会阻塞读。
// 本应用**每个页面渲染都读库**，当同步/快照刷新/研报落库与页面请求并发时，
// 读请求会遭遇 SQLITE_BUSY。此处启用 WAL + busy_timeout：
//   - journal_mode 是**持久属性**（一次写入库文件，后续连接沿用）；
//   - busy_timeout 是**连接级**：配合上方 connection_limit=1 后覆盖唯一连接。
// 实测（Prisma 6 + SQLite）：PRAGMA 必须走 $queryRawUnsafe——
//   $executeRawUnsafe 会以 "Execute returned results, which is not allowed in SQLite" 报错。
// 幂等、失败不阻断启动（WAL 失败仅降级为原 delete 模式，不应让应用起不来）。
const PRAGMA_READY_KEY = Symbol.for("invest-manager.prisma.pragmaReady");
type PragmaBox = { current: Promise<boolean> | null };
const pragmaBox: PragmaBox = ((
  globalThis as unknown as Record<symbol, PragmaBox | undefined>
)[PRAGMA_READY_KEY] ??= { current: null });

/**
 * 应用 SQLite PRAGMA（幂等）。
 * CR-04 附带修复：**失败不缓存**——此前把失败结果也缓存进 globalThis，
 * 使 WAL/busy_timeout 永久停留在降级态、不再重试。改为成功后缓存、
 * 失败清空，后续调用（如 health 探活）可再次尝试。
 */
export function ensureSqlitePragmas(): Promise<boolean> {
  if (pragmaBox.current) return pragmaBox.current;
  const p = (async (): Promise<boolean> => {
    try {
      await prisma.$queryRawUnsafe("PRAGMA journal_mode=WAL;");
      await prisma.$queryRawUnsafe("PRAGMA busy_timeout=5000;");
      return true;
    } catch (e) {
      console.warn(
        "[prisma] 启用 WAL/busy_timeout 失败（已降级，稍后可重试）:",
        e instanceof Error ? e.message : e,
      );
      return false;
    }
  })();
  pragmaBox.current = p;
  // 失败 → 清空缓存，允许下次重试
  void p.then((ok) => {
    if (!ok) pragmaBox.current = null;
  });
  return p;
}

void ensureSqlitePragmas();
