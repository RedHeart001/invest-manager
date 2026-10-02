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

/** 某个 UTC 瞬间的北京墙上时间（"YYYY-MM-DD HH:mm"）——状态位与说明文案用，
 *  不再各处自己 `+8*3600_000` 拼一遍（B4 的口径：一把尺，一处定义）。 */
export function beijingStamp(at: Date): string {
  return new Date(at.getTime() + 8 * 3600_000).toISOString().slice(0, 16).replace("T", " ");
}

/** 某个 UTC 瞬间落在北京的哪一天（YYYY-MM-DD）
 *
 * 库里的 `updatedAt` / `snapshotAt` 存的是 UTC 瞬间，而"这一类今天同步过没有"必须按
 * **北京日界**算（CR9-16 同族：不得拿宿主机的本地时区当日界）。#23 的幂等闸门与
 * #22(b)／#25 的陈旧说明共用这一个函数 ⇒ 两处判据不会因"谁自己 parse 了一次"而分叉。
 */
export function beijingDateOf(at: Date): string {
  return beijingStamp(at).slice(0, 10);
}
