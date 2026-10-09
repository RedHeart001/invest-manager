// 来路（provenance）——产品详情页的导航高亮与返回入口共用的单一数据源。
//
// 为什么需要它：`/product/**` 实测有四个入口、分属三个一级（搜索列表行、首页相关产品
// chips、首页「去分析」、聊天里的研报链接）。用 URL 前缀给它派一个"父级"必然谎报
// ——旧实现把 `/product` 并入「搜索」，主人因此把"点去分析"误判成"跳到了搜索页"。
// 来路是**每次访问**的属性，不是路由的静态属性，只能由入口显式带过来。

export const FROM_KEYS = ["search", "home", "chat"] as const;
export type FromKey = (typeof FROM_KEYS)[number];

export const FROM_LABEL: Record<FromKey, string> = {
  search: "搜索",
  home: "首页",
  chat: "智能助手",
};

/**
 * 会话存储键：**只**服务顶部导航的高亮兜底（主人 10-01 选 (i)）。
 * 返回按钮的目标不再读它——10-09 主人手测「一旦先访问过搜索页，返回永远都是那一页」，
 * 因为会话残留永不过期，而裸 URL 把它当成了"上一次的来路"。
 */
const STORE_KEY = "product.from";

/** 白名单解析：URL 参数是外部输入，非白名单值一律当作"没有来路"。 */
export function parseFrom(raw: string | null | undefined): FromKey | null {
  return (FROM_KEYS as readonly string[]).includes(raw ?? "") ? (raw as FromKey) : null;
}

export function readStoredFrom(): FromKey | null {
  if (typeof window === "undefined") return null;
  try {
    return parseFrom(window.sessionStorage.getItem(STORE_KEY));
  } catch {
    return null; // 隐私模式下 sessionStorage 本身会抛
  }
}

export function storeFrom(from: FromKey): void {
  try {
    window.sessionStorage.setItem(STORE_KEY, from);
  } catch {
    // 存不下就不兜底，下次仍是"无来路"——不影响带 from 的正常路径
  }
}

/** 无可回退历史时（直接敲 URL／新标签）由来路推导的返回目标。 */
export function hrefForFrom(from: FromKey, q: string | null): string {
  if (from === "search") return q ? `/search?q=${encodeURIComponent(q)}` : "/search";
  return from === "chat" ? "/chat" : "/";
}

/**
 * #56 甲（10-08 主人手测「粘贴链接后点返回没反应」）：返回按钮的**文案与目标必须取同一个键**。
 * 旧实现文案按 `from`、行为按 `window.history.length > 1`，而历史条目数会把 about:blank、
 * 新标签、同一 URL 重复回车都算成"可回退" ⇒ 出现"承诺回首页、实际回上一条历史"的错位。
 *
 * 10-09 主人第二轮手测又挖出两形，这一版把它们一起断掉：
 * - **裸 URL 不许继承会话残留**：没有 `?from=` 就是"没有来路"，目标一律首页（旧实现按
 *   `sessionStorage['product.from']` 推导 ⇒ 一旦搜索过，之后每次粘贴都掉回那个搜索页）。
 * - **URL 带 `from` 不等于"应用内进入"**：`from` 是地址栏里可粘贴的外部输入，它声明的是
 *   **意图**，不是浏览器历史的事实。旧实现只要见到 `from` 就 `back()`，于是同一标签里
 *   粘贴 `?from=home` 会 back 到上一条历史（往往是搜索页）＝"承诺回首页、实际回搜索页"。
 *   现在 `back()` 只由下面的**本文档路由轨迹**批准。
 */
export type BackPlan = {
  readonly label: string;
  readonly href: string;
};

export function planBack(rawFrom: string | null | undefined, q: string | null): BackPlan {
  const from = parseFrom(rawFrom);
  if (from) return { label: `← 返回${FROM_LABEL[from]}`, href: hrefForFrom(from, q) };
  return { label: "← 返回", href: "/" };
}

// ---------- 本文档内的路由轨迹（back() 的唯一许可证） ----------
// 模块级状态＝每次整页加载自动归零，而这恰好就是"是不是应用内走进来"的判据：
// 地址栏粘贴／新标签／重复回车都是一次整页加载 ⇒ 轨迹为空 ⇒ 不许 `back()`。
// 应用内的 `Link`/`router.push` 不换文档 ⇒ 轨迹里留着上一页，`back()` 才真能回到它，
// CR8-6 那条"带回落后的搜索现场（type/sort/page/滚动）"也因此没被这刀牺牲掉。

let currentPath: string | null = null;
let previousPath: string | null = null;

/** 轨迹用的键＝路径＋查询。不含 hash：同一页换锚点不是一次"进入"，但会进历史条目。 */
export function routeKey(pathname: string, params: URLSearchParams): string {
  const qs = params.toString();
  return qs ? `${pathname}?${qs}` : pathname;
}

/** 由 `Nav`（布局级、每条路由都挂）在路由变化时调用；同一路径重复观察是 no-op。 */
export function observePath(path: string): void {
  if (path === currentPath) return;
  previousPath = currentPath;
  currentPath = path;
}

/**
 * 现在这一页是不是"从本文档里的另一页推进来的"。
 * 要同时满足：轨迹的最新一条就是我（说明观察已经跟着这次导航走过来了），且前一条存在且不是我。
 * 任一条件不成立（整页加载／轨迹还没跟上）都退化成 push 推导目标＝安全侧。
 */
export function canBackToOrigin(selfPath: string): boolean {
  return currentPath === selfPath && previousPath !== null && previousPath !== selfPath;
}

/** 测试用：轨迹是模块级状态，用例之间必须能归零（否则控制组不成立）。 */
export function resetPathTrace(): void {
  previousPath = null;
  currentPath = null;
}
