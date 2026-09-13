// 北京时间工具（B4：全站统一，替换此前 4 处手写 `Date.now() + 8*3600_000`）
// 约定（PLAN）：时间显示与调度一律 Asia/Shanghai（UTC+8）。

/** 当前北京时间（Date 对象，内部用 UTC+8 偏移构造） */
export function beijingNow(): Date {
  return new Date(Date.now() + 8 * 3600_000);
}

/** 今天（北京时间，YYYY-MM-DD） */
export function beijingToday(): string {
  return beijingNow().toISOString().slice(0, 10);
}

/** 今天往前偏移 N 天（北京时间，YYYY-MM-DD） */
export function beijingShiftDays(days: number): string {
  return new Date(Date.now() + 8 * 3600_000 + days * 86_400_000).toISOString().slice(0, 10);
}
