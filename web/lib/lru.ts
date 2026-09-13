// 微型 LRU（M3/O2）：给进程内缓存统一容量上限，防止长期运行内存无界增长
// 实现基于 Map 的插入序（最近访问移到末尾），淘汰最旧条目

export class Lru<K, V> {
  private map = new Map<K, V>();

  constructor(private readonly capacity: number) {
    if (capacity <= 0) throw new Error("Lru capacity must be > 0");
  }

  get size(): number {
    return this.map.size;
  }

  has(key: K): boolean {
    return this.map.has(key);
  }

  get(key: K): V | undefined {
    const v = this.map.get(key);
    if (v !== undefined) {
      // 访问即提升到末尾（最近使用）
      this.map.delete(key);
      this.map.set(key, v);
    }
    return v;
  }

  set(key: K, value: V): void {
    if (this.map.has(key)) this.map.delete(key);
    this.map.set(key, value);
    while (this.map.size > this.capacity) {
      const oldest = this.map.keys().next().value;
      if (oldest === undefined) break;
      this.map.delete(oldest);
    }
  }

  delete(key: K): void {
    this.map.delete(key);
  }

  keys(): IterableIterator<K> {
    return this.map.keys();
  }
}
