// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HotspotFeed from "./HotspotFeed";
import type { DigestRow } from "@/lib/hotspots";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

function digest(id: string, title: string, date = "2026-11-13"): DigestRow {
  return {
    id, date, title, summary: "", boardTags: [], sourceUrls: [], related: [],
    newsSources: [], engine: null, degraded: false, note: null,
    createdAt: "2026-11-13T01:00:00.000Z",
  };
}

function response(body: unknown, ok = true): Response {
  return { ok, statusText: ok ? "OK" : "Bad Request", json: async () => body } as Response;
}

class EventSourceMock {
  static instances: EventSourceMock[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(public url: string) {
    EventSourceMock.instances.push(this);
  }

  addEventListener(name: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(name, listener);
  }

  emitDigest(body: unknown) {
    this.listeners.get("digest")?.({ data: JSON.stringify(body) } as MessageEvent);
  }

  close() { this.closed = true; }
}

const initialRows = [digest("initial", "初始热点", "2026-11-12")];
let requests: { url: string; signal?: AbortSignal }[];

beforeEach(() => {
  EventSourceMock.instances = [];
  requests = [];
  vi.stubGlobal("EventSource", EventSourceMock);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("HotspotFeed 请求生命周期（CR10-29）", () => {
  it("较晚完成的旧刷新不能覆盖新刷新", async () => {
    const older = deferred<Response>();
    const newer = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      requests.push({ url, signal: init?.signal ?? undefined });
      return requests.length === 1 ? older.promise : newer.promise;
    }));
    render(<HotspotFeed initialDate="2026-11-12" initialRows={initialRows} />);
    const es = EventSourceMock.instances[0];
    await act(async () => { es.onopen?.(); });
    // 刷新 pending 时按钮禁用；重连 onopen 是现实存在的第二个刷新入口。
    await act(async () => { es.onopen?.(); });
    expect(requests).toHaveLength(2);
    expect(requests[0].signal?.aborted).toBe(true);

    await act(async () => {
      newer.resolve(response({ date: "2026-11-14", rows: [digest("new", "新日期热点", "2026-11-14")] }));
      await newer.promise;
    });
    expect(screen.getByText("新日期热点")).toBeTruthy();
    await act(async () => {
      older.resolve(response({ date: "2026-11-13", rows: [digest("old", "旧日期热点")] }));
      await older.promise;
    });
    expect(screen.queryByText("旧日期热点")).toBeNull();
    expect(screen.getByText("新日期热点")).toBeTruthy();
    expect(screen.getByText("数据日期：2026-11-14")).toBeTruthy();
  });

  it("同日期 digest 按 id 去重增量插入", async () => {
    const { container } = render(<HotspotFeed initialDate="2026-11-13" initialRows={[digest("old", "旧热点")]} />);
    await act(async () => {
      EventSourceMock.instances[0].emitDigest({
        date: "2026-11-13",
        rows: [digest("new", "新热点"), digest("old", "重复旧热点")],
      });
    });
    expect(screen.getByText("数据日期：2026-11-13")).toBeTruthy();
    expect(screen.getByText("新热点")).toBeTruthy();
    expect(screen.getAllByText("旧热点")).toHaveLength(1);
    expect(screen.queryByText("重复旧热点")).toBeNull();
    expect(container.querySelectorAll("li")).toHaveLength(2);
  });

  it("跨日期 digest 自动切换日期并整表替换", async () => {
    const { container } = render(<HotspotFeed initialDate="2026-11-12" initialRows={[digest("old", "昨日热点", "2026-11-12")]} />);
    await act(async () => {
      EventSourceMock.instances[0].emitDigest({ date: "2026-11-13", rows: [digest("new", "今日热点")] });
    });
    expect(screen.getByText("数据日期：2026-11-13")).toBeTruthy();
    expect(screen.getByText("今日热点")).toBeTruthy();
    expect(screen.queryByText("昨日热点")).toBeNull();
    expect(container.querySelectorAll("li")).toHaveLength(1);
  });

  it("空行的跨日期 digest 也切换日期并清空旧行", async () => {
    const { container } = render(<HotspotFeed initialDate="2026-11-12" initialRows={[digest("old", "昨日热点", "2026-11-12")]} />);
    await act(async () => {
      EventSourceMock.instances[0].emitDigest({ date: "2026-11-13", rows: [] });
    });
    expect(screen.getByText("数据日期：2026-11-13")).toBeTruthy();
    expect(screen.queryByText("昨日热点")).toBeNull();
    expect(container.querySelectorAll("li")).toHaveLength(0);
  });

  it("全重复的跨日期 digest 不沿用旧行内容", async () => {
    const { container } = render(<HotspotFeed initialDate="2026-11-12" initialRows={[digest("same", "昨日热点", "2026-11-12")]} />);
    await act(async () => {
      EventSourceMock.instances[0].emitDigest({ date: "2026-11-13", rows: [digest("same", "次日同 id 热点")] });
    });
    expect(screen.getByText("数据日期：2026-11-13")).toBeTruthy();
    expect(screen.getByText("次日同 id 热点")).toBeTruthy();
    expect(screen.queryByText("昨日热点")).toBeNull();
    expect(container.querySelectorAll("li")).toHaveLength(1);
  });

  it("SSE 重连补拉遵守同一刷新代次，新 digest 作废在途旧快照", async () => {
    const older = deferred<Response>();
    const newer = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => {
      requests.push({ url: _url, signal: init?.signal ?? undefined });
      return requests.length === 1 ? older.promise : newer.promise;
    }));
    render(<HotspotFeed initialDate="2026-11-12" initialRows={initialRows} />);
    const es = EventSourceMock.instances[0];
    await act(async () => { es.onopen?.(); });
    await act(async () => { es.onopen?.(); });
    expect(requests).toHaveLength(2);
    expect(requests[0].signal?.aborted).toBe(true);

    await act(async () => {
      es.emitDigest({ date: "2026-11-15", rows: [digest("sse", "推送热点", "2026-11-15")] });
    });
    expect(requests[1].signal?.aborted).toBe(true);
    await act(async () => {
      older.resolve(response({ date: "2026-11-13", rows: [digest("old", "旧补拉")] }));
      newer.resolve(response({ date: "2026-11-14", rows: [digest("late", "迟到快照")] }));
      await Promise.all([older.promise, newer.promise]);
    });
    expect(screen.getByText("推送热点")).toBeTruthy();
    expect(screen.queryByText("旧补拉")).toBeNull();
    expect(screen.queryByText("迟到快照")).toBeNull();
    expect(screen.getByText("数据日期：2026-11-15")).toBeTruthy();
  });

  it("卸载中止 POST 和等待计时器，不再发起状态轮询", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      requests.push({ url, signal: init?.signal ?? undefined });
      return response({ accepted: true });
    }));
    const view = render(<HotspotFeed initialDate="2026-11-12" initialRows={initialRows} />);
    fireEvent.click(screen.getByRole("button", { name: "立即抓取热点" }));
    await act(async () => { await Promise.resolve(); });
    expect(requests.map((r) => r.url)).toEqual(["/api/hotspots/run"]);

    view.unmount();
    expect(requests[0].signal?.aborted).toBe(true);
    expect(EventSourceMock.instances[0].closed).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(requests.map((r) => r.url)).toEqual(["/api/hotspots/run"]);
  });

  it("StrictMode 重建后仍可刷新；accepted:false 保留原有提示", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      requests.push({ url });
      if (url === "/api/hotspots/run") return response({ accepted: false });
      return response({ date: "2026-11-13", rows: initialRows });
    }));
    render(<StrictMode><HotspotFeed initialDate="2026-11-12" initialRows={initialRows} /></StrictMode>);
    const live = EventSourceMock.instances.at(-1)!;
    await act(async () => { live.onopen?.(); });
    expect(requests.some((r) => r.url.startsWith("/api/hotspots?"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "立即抓取热点" }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("已有热点任务在执行中")).toBeTruthy();
    expect(requests.filter((r) => r.url === "/api/hotspots/run")).toHaveLength(1);
  });
});
