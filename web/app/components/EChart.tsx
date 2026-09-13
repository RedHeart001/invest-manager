"use client";

// 通用 ECharts 包装：SSR 构建好 option 传入，客户端渲染（明细区静态图用）
import { useEffect, useRef } from "react";

import type { EChartsOption } from "echarts";

export default function EChart({
  option,
  height = 260,
}: {
  option: EChartsOption;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let chart: import("echarts").ECharts | null = null;
    let disposed = false;
    import("echarts").then((echarts) => {
      if (disposed || !ref.current) return;
      chart = echarts.init(ref.current);
      chart.setOption(option);
    });
    return () => {
      disposed = true;
      chart?.dispose();
    };
  }, [option]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
