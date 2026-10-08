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

/** 兜底用的会话存储键：裸 URL／新标签打开时沿用上一次的来路（主人 10-01 选 (i)）。 */
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
 * #56 甲（10-08 主人手测「粘贴链接后点返回没反应」）：返回按钮的**文案与行为必须取同一个键**。
 * 旧实现文案按 `from`、行为按 `window.history.length > 1`，而历史条目数会把 about:blank、
 * 新标签、同一 URL 重复回车都算成"可回退" ⇒ 出现"承诺回首页、实际回上一条历史"的错位。
 *
 * 判据＝URL 自己带来路（`?from=`，白名单内）＝应用内进入 ⇒ 那条历史必然存在 ⇒ 才敢 `back()`。
 * `sessionStorage` 里的来路只用来选**推导目标**，不参与文案（它可能是上一次访问留下的）。
 */
export type BackPlan = {
  readonly label: string;
  readonly useHistoryBack: boolean;
  readonly fallbackHref: string;
};

export function planBack(
  rawFrom: string | null | undefined,
  q: string | null,
  stored: FromKey | null,
): BackPlan {
  const from = parseFrom(rawFrom);
  if (from) {
    return {
      label: `← 返回${FROM_LABEL[from]}`,
      useHistoryBack: true,
      fallbackHref: hrefForFrom(from, q),
    };
  }
  return { label: "← 返回", useHistoryBack: false, fallbackHref: hrefForFrom(stored ?? "home", q) };
}
