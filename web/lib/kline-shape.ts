// CR9-42：OHLC 序列是否"无信息量"——每根 bar 的开/高/低/收四值全相等。
// 命中时该序列实际只携带收盘价，画 K 线会让每根实体高度为 0、渲染成一堆散点。
// 判据沿用 lib/kline.ts 日线缓存里原有的 `every(open===close===high===low)`，
// 此处提为单一来源，让"净值型品种"与"仅有分钟收盘价的降级源"共用同一条规则。
// 取"全部相等"而非"多数相等"：只要有一根 bar 带真实区间，就仍是合法的 K 线。

type Ohlc = { open: number; high: number; low: number; close: number };

export function isFlatOhlcSeries(candles: Ohlc[]): boolean {
  return (
    candles.length > 0 &&
    candles.every(
      (c) => c.open === c.close && c.high === c.close && c.low === c.close,
    )
  );
}
