// 产品类型的中文显示名——单一来源（R18，2026-11-01）
//
// 为什么抽出来：自选清单页要按类型分组显示中文类名，而这张表此前在
// `app/search/search-client.tsx` 与 `app/product/[type]/[code]/page.tsx` 各有一份
// 逐字相同的硬写，两处之间**没有任何交叉约束**（各改各的，屏上就分裂）。
// 第三处再抄一份就是把 C5 当年还清的账重新欠一遍——C5 对 `lib/validate.ts` 的处置
// 就是"抽出单一来源、原字面量硬写删除"，此处沿用同一形状。
//
// ⚠️ 键集合必须与 `lib/validate.ts` 的 `QUOTE_TYPES` 同集：少一个键时，界面上那一类
//    会走 `TYPE_LABEL[t] ?? t` 的兜底显示成英文标识（`HK`/`US`），而这条兜底**不会报错**
//    ⇒ 由 `lib/type-label.test.ts` 把两个集合钉在一起。
//
// 纯常量零依赖（不 import 任何运行时模块），客户组件与 Server Component 都能安全引用。

export const TYPE_LABEL: Record<string, string> = {
  stock: "股票",
  fund: "基金",
  bond: "债券",
  crypto: "虚拟币",
  hk: "港股",
  us: "美股",
};
