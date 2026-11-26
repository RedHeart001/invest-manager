"""CR10-49 离线单测：美股完整名单持久化续跑与幂等发布状态机。

覆盖：
- 923 页跨轮/跨重启继续，已完成页不重复请求；
- 页文件先写、manifest 后写（孤儿页回收）与损坏页重采；
- 声明变化废弃 generation，不跨声明拼页；
- 重复代码/短尾/非空穷尽页 fail-closed；
- candidate 只在全部验证通过后出现；
- 发布超时按同一 snapshotId 重试，发布拒绝进 blocked；
- 刷新 partial 不冒充 completed，恢复后收尾；
- 备份运行期间发布让位；
- ensure_running 单飞、启动即 collecting、重启只恢复未收尾任务。

运行（零出网、零 SQLite）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_49_us_list_job.py
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time as _real_time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# CR9-100／CR9-119：测试不许把仓库 runtime/ 或操作者 .env 当输入/落点。
_TMP = tempfile.mkdtemp(prefix="cr1049-job-")
os.environ["LIMITER_STATE_FILE"] = os.path.join(_TMP, "limiter-state.json")
os.environ["US_LIST_JOB_DIR"] = os.path.join(_TMP, "job")
os.environ.pop("US_LIST_PAGES", None)
os.environ.pop("US_LIST_BURST_TIMEOUT_S", None)

import app.config as _cfg  # noqa: E402
from pathlib import Path  # noqa: E402

_cfg._ENV_FILES[:] = [Path(tempfile.mkdtemp(prefix="cr1049-env-")) / "absent.env"]

from app import us_list_job as job  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


JOB_DIR = os.environ["US_LIST_JOB_DIR"]
PAGE_SIZE = 20

# 实测样本（与 CR9-59 同一行形状）：有行业 ⇒ 通过产品口径；无行业 ⇒ 被剔。
NVDA = {
    "name": "NVIDIA Corporation",
    "cname": "英伟达公司",
    "category": "半导体",
    "symbol": "NVDA",
    "price": "233.95",
    "market": "NASDAQ",
}
NO_CATEGORY = dict(NVDA, category=None)


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float = 1.0) -> None:
        self.now += seconds


class FakeTime:
    """只替 `us_list_job.time`：不改真实 time 模块，线程等待不受影响。"""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.monotonic()


class Upstream:
    """可编程的假上游：按声明返回满页，可注入失败/声明漂移/自定义行。"""

    def __init__(self, declared: int, clock: Clock | None = None, advance: float = 1.0) -> None:
        self.declared = declared
        self.clock = clock
        self.advance = advance
        self.calls: list[int] = []
        self.fail_pages: dict[int, int] = {}
        self.declared_override: dict[int, str] = {}
        self.rows_override: dict[int, list[dict]] = {}

    @property
    def required(self) -> int:
        return (self.declared + PAGE_SIZE - 1) // PAGE_SIZE

    def rows(self, page: int) -> list[dict]:
        start = (page - 1) * PAGE_SIZE
        count = min(PAGE_SIZE, max(self.declared - start, 0))
        return [dict(NVDA, symbol=f"S{page:04d}_{i:02d}") for i in range(count)]

    def __call__(self, page: int, session, deadline=None):
        self.calls.append(page)
        if self.clock is not None:
            self.clock.advance(self.advance)
        remaining = self.fail_pages.get(page, 0)
        if remaining > 0:
            self.fail_pages[page] = remaining - 1
            raise RuntimeError(f"synthetic page {page} failure")
        declared = self.declared_override.get(page, str(self.declared))
        if page in self.rows_override:
            return declared, self.rows_override[page]
        if page > self.required:
            return declared, []
        return declared, self.rows(page)


class JobEnv:
    """把假上游、假时钟和突发上限一起装上；退出时逐项还原。"""

    def __init__(
        self,
        upstream: Upstream,
        *,
        burst: float = 1e9,
        pages: int | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.upstream = upstream
        self.burst = burst
        self.pages = pages
        self.clock = clock or Clock()

    def __enter__(self):
        self.prev_time = job.time
        self.prev_fetcher = job.page_fetcher
        self.prev_burst = os.environ.get("US_LIST_BURST_TIMEOUT_S")
        self.prev_pages = os.environ.get("US_LIST_PAGES")
        job.time = FakeTime(self.clock)
        job.page_fetcher = self.upstream
        os.environ["US_LIST_BURST_TIMEOUT_S"] = str(self.burst)
        if self.pages is None:
            os.environ.pop("US_LIST_PAGES", None)
        else:
            os.environ["US_LIST_PAGES"] = str(self.pages)
        return self

    def __exit__(self, *exc):
        job.time = self.prev_time
        job.page_fetcher = self.prev_fetcher
        if self.prev_burst is None:
            os.environ.pop("US_LIST_BURST_TIMEOUT_S", None)
        else:
            os.environ["US_LIST_BURST_TIMEOUT_S"] = self.prev_burst
        if self.prev_pages is None:
            os.environ.pop("US_LIST_PAGES", None)
        else:
            os.environ["US_LIST_PAGES"] = self.prev_pages
        return False


def _no_network(page, session, deadline=None):
    raise AssertionError(f"离线测试试图真出网请求第 {page} 页")


def _unexpected_publish(candidate):
    raise AssertionError("本用例不应发布候选")


def _unexpected_refresh(snapshot_id):
    raise AssertionError("本用例不应刷新行情")


def fresh_job() -> None:
    """停 worker、清目录、把所有外部副作用默认钉成“一调就炸”。"""
    job.shutdown()
    job.reset_for_tests()
    shutil.rmtree(JOB_DIR, ignore_errors=True)
    os.makedirs(JOB_DIR, exist_ok=True)
    job.page_fetcher = _no_network
    job._publish_fn = _unexpected_publish
    job._refresh_fn = _unexpected_refresh


def state() -> dict:
    return job._load_state()


def candidate_of(snapshot_id: str):
    return job._read_json(job._candidate_path(snapshot_id))


def page_files(snapshot_id: str) -> list[str]:
    pages_dir = os.path.join(job._generation_dir(snapshot_id), "pages")
    try:
        return sorted(os.listdir(pages_dir))
    except OSError:
        return []


# ---------- 1. 基本收尾：页检查点 + 候选 + 行业口径 ----------


def test_candidate_checkpoint_and_policy_subset() -> None:
    fresh_job()
    up = Upstream(21)
    up.rows_override[2] = [dict(NO_CATEGORY, symbol="NOINDUSTRY")]
    with JobEnv(up):
        st = job.run_once()

    sid = st.get("snapshotId")
    check("完整采集后进入 candidate_ready（不是 completed）", st.get("state") == "candidate_ready", str(st)[:160])
    check("页检查点：2/2 页已落盘", job.status()["resolvedPages"] == 2 and job.status()["requiredPages"] == 2, str(job.status()))
    check("穷尽页 p3 被请求且为空", up.calls == [1, 2, 3], str(up.calls))
    check("页文件按页号落盘", page_files(sid) == ["000001.json", "000002.json"], str(page_files(sid)))
    manifest = job._load_manifest(sid) or {}
    check("manifest 记录声明与穷尽证明",
          manifest.get("declaredCount") == 21
          and manifest.get("requiredPages") == 2
          and (manifest.get("probe") or {}).get("rows") == 0,
          str(manifest)[:180])

    cand = candidate_of(sid)
    check("candidate 只在全部验证后出现", isinstance(cand, dict) and cand.get("snapshotId") == sid, str(cand)[:120])
    check("candidate 保留完整采集声明（21 行/2 页/穷尽页）",
          cand.get("acquisitionComplete") is True
          and cand.get("declaredCount") == 21
          and cand.get("acquiredCount") == 21,
          str(cand)[:180])
    check("行业口径只剔无行业行：21 原始 → 20 产品",
          cand.get("count") == 20 and len(cand.get("products") or []) == 20,
          f"count={cand.get('count')}")
    check("产品口径子集被显式分账，不冒充上游劣化",
          cand.get("productPolicySubset") is True
          and cand.get("intentionalSubset") is True
          and cand.get("degraded") is True
          and "剔掉 1 行" in (cand.get("note") or ""),
          str(cand)[:200])
    check("候选里的产品字段可直接发布",
          all(p["type"] == "us" and p["code"] and p["name"] for p in cand["products"]))
    check("同一 snapshotId 可从 get_ready_candidate 取回", job.get_ready_candidate() == cand)
    check("status 的进度与候选一致",
          job.status()["snapshotId"] == sid
          and job.status()["pendingPages"] == 0
          and job.status()["publishedCount"] is None,
          str(job.status()))


# ---------- 2. 923 页跨轮 + 跨重启 ----------


def test_923_pages_across_rounds_and_restart() -> None:
    fresh_job()
    declared = 923 * PAGE_SIZE  # 18,460 只 ⇒ 923 页整
    clock = Clock()
    up = Upstream(declared, clock=clock)
    with JobEnv(up, burst=500, clock=clock):
        first = job.run_once()
        first_sid = first.get("snapshotId")
        first_resolved = job.status()["resolvedPages"]
        check("第一轮只跑突发上限，进入 waiting 而不是失败",
              first.get("state") == "waiting" and 400 <= first_resolved < 923,
              f"state={first.get('state')} resolved={first_resolved}")
        check("waiting 时没有 candidate（正式数据零写入）",
              job.get_ready_candidate() is None and candidate_of(first_sid) is None)
        check("waiting 仍保留同一 snapshotId 与页检查点",
              first_sid and job.status()["requiredPages"] == 923
              and len(page_files(first_sid)) == first_resolved,
              str(job.status()))

        # 模拟进程重启：模块内存清空、目录保留；新 worker 从盘上继续。
        job.shutdown()
        job.reset_for_tests()
        up2 = Upstream(declared, clock=clock)
        job.page_fetcher = up2
        second = job.run_once()

    second_sid = second.get("snapshotId")
    check("重启后继续同一 generation，不重新开一轮",
          second_sid == first_sid and second.get("state") == "candidate_ready",
          f"{first_sid} -> {second_sid} / {second.get('state')}")
    check("第二轮补齐 923 页并完成穷尽页",
          job.status()["resolvedPages"] == 923
          and job.status()["requiredPages"] == 923
          and up2.calls[-1] == 924,
          str(job.status()))
    check("跨轮/跨重启没有重复请求已完成页",
          len(up.calls) + len(up2.calls) == 924
          and sorted(up.calls + up2.calls) == list(range(1, 925)),
          f"first={len(up.calls)} second={len(up2.calls)}")
    check("923 页全部落成页文件", len(page_files(second_sid)) == 923, str(len(page_files(second_sid))))
    cand = candidate_of(second_sid)
    check("完整候选 18,460 只、代码唯一",
          cand.get("count") == declared
          and len({p["code"] for p in cand["products"]}) == declared,
          f"count={cand.get('count')}")


# ---------- 3. 页文件先写、manifest 后写；损坏页重采 ----------


def test_orphan_and_corrupt_pages() -> None:
    fresh_job()
    up = Upstream(40)  # 2 页
    with JobEnv(up):
        st = job.run_once()
    sid = st["snapshotId"]
    check("基线：2 页 + 穷尽页完成", st.get("state") == "candidate_ready" and up.calls == [1, 2, 3], str(up.calls))

    # 模拟“页文件已写、manifest 还没登记”的崩溃窗口：把 p2 从 manifest 摘掉，文件保留。
    manifest = job._load_manifest(sid)
    manifest["completedPages"] = [1]
    manifest["pageHashes"] = {"1": manifest["pageHashes"]["1"]}
    job._save_manifest(manifest)
    job._patch_state(state="collecting")
    up.calls.clear()
    with JobEnv(up):
        st = job.run_once()
    check("孤儿页被 manifest 重建回收，不再请求 p2",
          st.get("state") == "candidate_ready" and up.calls == [3],
          f"calls={up.calls} state={st.get('state')}")
    check("回收后 manifest 重新登记 p2",
          job._load_manifest(sid)["completedPages"] == [1, 2],
          str(job._load_manifest(sid)["completedPages"]))

    # 损坏页：内容与 sha256 不符 ⇒ 只丢该页，下一轮重采。
    job._write_json(
        job._page_path(sid, 2),
        {"page": 2, "declaredCount": "40", "rows": [dict(NVDA, symbol="BROKEN")], "sha256": "deadbeef"},
    )
    job._patch_state(state="collecting")
    up.calls.clear()
    with JobEnv(up):
        st = job.run_once()
    check("损坏页被丢弃并重采，其余页不重复请求",
          st.get("state") == "candidate_ready" and up.calls == [2, 3],
          f"calls={up.calls} state={st.get('state')}")

    # 声明不一致的页同样不可信（同页内容可能来自另一代次）。
    job._write_page(sid, 2, "41", up.rows(2))
    job._patch_state(state="collecting")
    up.calls.clear()
    with JobEnv(up):
        st = job.run_once()
    check("页声明与 manifest 不一致 ⇒ 该页重采",
          st.get("state") == "candidate_ready" and up.calls == [2, 3],
          f"calls={up.calls}")


# ---------- 4. 声明变化：废弃 generation，不跨声明拼页 ----------


def test_declaration_change_supersedes() -> None:
    fresh_job()
    up = Upstream(40)
    up.declared_override[2] = "41"
    with JobEnv(up):
        first = job.run_once()
    gens = os.listdir(os.path.join(JOB_DIR, "generations"))
    old_sid = gens[0] if len(gens) == 1 else None
    check("抓取中声明变化 ⇒ waiting + 旧 generation 作废",
          first.get("state") == "waiting"
          and first.get("snapshotId") is None
          and (first.get("lastError") or {}).get("kind") == "declaration_changed",
          str(first)[:220])
    old_manifest = job._load_manifest(old_sid) or {}
    check("旧 manifest 标记 superseded，页文件保留供审计",
          old_manifest.get("superseded") is True
          and page_files(old_sid) == ["000001.json"],
          str(old_manifest)[:160])
    check("声明变化后没有 candidate", job.get_ready_candidate() is None)

    up2 = Upstream(40)
    with JobEnv(up2):
        second = job.run_once()
    new_sid = second.get("snapshotId")
    check("下一轮新开 generation，不复用旧页",
          new_sid and new_sid != old_sid and second.get("state") == "candidate_ready",
          f"{old_sid} -> {new_sid}")
    check("新 generation 从 p1 重采（不跨声明拼页）",
          up2.calls == [1, 2, 3] and page_files(new_sid) == ["000001.json", "000002.json"],
          f"calls={up2.calls}")


# ---------- 5. fail-closed：重复代码 / 短尾 / 非空穷尽页 ----------


def test_fail_closed_shapes() -> None:
    fresh_job()
    up = Upstream(20)
    up.rows_override[1] = [dict(NVDA, symbol="DUP"), dict(NVDA, symbol="DUP")] + [
        dict(NVDA, symbol=f"D{i:02d}") for i in range(18)
    ]
    up.rows_override[2] = []  # 穷尽页为空
    with JobEnv(up):
        st = job.run_once()
    check("原始代码重复 ⇒ blocked，不生成候选",
          st.get("state") == "blocked"
          and "duplicate symbols" in (st.get("blockedReason") or "")
          and job.get_ready_candidate() is None,
          str(st)[:220])

    fresh_job()
    up = Upstream(40)
    up.rows_override[2] = up.rows(2)[:19]  # 短尾
    with JobEnv(up):
        st = job.run_once()
    check("持续短尾 ⇒ waiting，不把 1/2 页当候选",
          st.get("state") == "waiting"
          and "incomplete snapshot" in ((st.get("lastError") or {}).get("message") or "")
          and job.get_ready_candidate() is None,
          str(st)[:220])
    check("短尾请求有界：首轮 3 次 + 两轮修复各 3 次",
          up.calls.count(2) == 9 and up.calls.count(1) == 1,
          str(up.calls))
    up.rows_override.pop(2)
    up.calls.clear()
    with JobEnv(up):
        st = job.run_once()
    check("上游恢复后从缺口续跑，不重采已完成的 p1",
          st.get("state") == "candidate_ready"
          and up.calls == [2, 3]
          and candidate_of(st["snapshotId"]).get("count") == 40,
          f"calls={up.calls}")

    fresh_job()
    up = Upstream(20)
    up.rows_override[2] = [dict(NVDA, symbol="EXTRA")]
    with JobEnv(up):
        st = job.run_once()
    check("穷尽页非空 ⇒ blocked（声明过小，不能交付）",
          st.get("state") == "blocked"
          and "exhaustion probe" in (st.get("blockedReason") or ""),
          str(st)[:200])


# ---------- 6. 页预算 / 首页失败 ----------


def test_budget_and_first_page_failure() -> None:
    fresh_job()
    up = Upstream(60)  # 3 页
    with JobEnv(up, pages=2):
        st = job.run_once()
    check("页预算不足 ⇒ blocked，不交付截断名单",
          st.get("state") == "blocked"
          and "page budget 2 < required 3" in (st.get("blockedReason") or "")
          and up.calls == [1],
          f"calls={up.calls} state={st.get('state')}")

    fresh_job()
    up = Upstream(20)
    up.fail_pages[1] = 99
    with JobEnv(up):
        st = job.run_once()
    check("首页持续失败 ⇒ waiting，不建立声明/不写页文件",
          st.get("state") == "waiting"
          and "first page unresolved" in ((st.get("lastError") or {}).get("message") or "")
          and page_files(st.get("snapshotId")) == [],
          str(st)[:200])
    check("首页同页恢复有界（3 次）", up.calls == [1, 1, 1], str(up.calls))
    up.fail_pages.clear()
    up.calls.clear()
    with JobEnv(up):
        st = job.run_once()
    check("首页恢复后正常建立声明并完成",
          st.get("state") == "candidate_ready" and up.calls == [1, 2],
          f"calls={up.calls}")


# ---------- 7. 发布：未知结果重试同一 snapshotId，刷新 partial 不冒充完成 ----------


def test_publish_retry_and_refresh_partial() -> None:
    fresh_job()
    up = Upstream(20)
    with JobEnv(up):
        st = job.run_once()
    sid = st["snapshotId"]

    published: list[str] = []

    def publish(cand):
        published.append(cand["snapshotId"])
        if len(published) == 1:
            raise job._PublishTransient("ReadTimeout: response lost")
        return {"ok": True, "alreadyPublished": len(published) > 2}

    refreshed: list[str] = []

    def refresh(snapshot_id):
        refreshed.append(snapshot_id)
        if len(refreshed) == 1:
            return {"ok": False, "weakTypes": ["us"]}
        return {"ok": True, "results": [{"type": "us", "failedBatches": 0}]}

    job._publish_fn = publish
    job._refresh_fn = refresh
    try:
        unknown = job.run_once()
        check("发布超时 ⇒ publish_unknown（不是成功、不是 completed）",
              unknown.get("state") == "publish_unknown"
              and unknown.get("snapshotId") == sid
              and unknown.get("backoffS") == 60
              and unknown.get("lastPublishedSnapshotId") is None,
              str(unknown)[:220])
        check("发布未知时 get_ready_candidate 仍可取回同一候选",
              (job.get_ready_candidate() or {}).get("snapshotId") == sid)

        publishing = job.run_once()
        check("重试沿用同一 snapshotId（幂等键不换）",
              publishing.get("state") == "refreshing"
              and published == [sid, sid]
              and publishing.get("lastPublishedSnapshotId") == sid,
              f"published={published} state={publishing.get('state')}")

        partial = job.run_once()
        check("刷新 partial ⇒ refresh_pending，不写 completed",
              partial.get("state") == "refresh_pending"
              and partial.get("refreshOutcome") == "partial_failed"
              and (partial.get("lastError") or {}).get("kind") == "refresh_partial"
              and partial.get("completedDate") is None,
              str(partial)[:220])
        check("刷新 partial 仍指向已发布 snapshot，不重新发布",
              refreshed == [sid] and published == [sid, sid])

        done = job.run_once()
        check("刷新恢复后 completed，且记录发布/刷新账",
              done.get("state") == "completed"
              and done.get("refreshOutcome") == "completed"
              and done.get("completedDate")
              and done.get("publishedCount") == 20,
              str(done)[:220])
        check("刷新重试仍用同一 snapshotId", refreshed == [sid, sid], str(refreshed))
        check("completed 当日 get_ready_candidate 仍返回已发布候选",
              (job.get_ready_candidate() or {}).get("snapshotId") == sid)
    finally:
        job._publish_fn = _unexpected_publish
        job._refresh_fn = _unexpected_refresh


def test_publish_rejected_and_missing_candidate() -> None:
    fresh_job()
    up = Upstream(20)
    with JobEnv(up):
        st = job.run_once()
    sid = st["snapshotId"]

    def reject(cand):
        raise job._PublishRejected("payload shrunk (10 < 20 的 70%)，已保留现有数据")

    job._publish_fn = reject
    try:
        blocked = job.run_once()
    finally:
        job._publish_fn = _unexpected_publish
    check("Web 明确拒绝 ⇒ blocked，不无限重试同一份",
          blocked.get("state") == "blocked"
          and "payload shrunk" in (blocked.get("blockedReason") or "")
          and (blocked.get("lastError") or {}).get("kind") == "publish_rejected",
          str(blocked)[:200])
    check("发布拒绝后没有刷新副作用",
          blocked.get("refreshOutcome") is None and job.get_ready_candidate() is None)

    fresh_job()
    job._patch_state(state="candidate_ready", snapshotId="missing-candidate")
    st = job.run_once()
    check("candidate 文件缺失 ⇒ blocked（本地状态矛盾不反复提交）",
          st.get("state") == "blocked"
          and "candidate file missing" in (st.get("blockedReason") or ""),
          str(st)[:180])


# ---------- 8. 备份让位 ----------


def test_publish_yields_to_backup() -> None:
    fresh_job()
    up = Upstream(20)
    with JobEnv(up):
        st = job.run_once()
    sid = st["snapshotId"]

    published: list[str] = []

    def publish(cand):
        published.append(cand["snapshotId"])
        return {"ok": True}

    def refresh(snapshot_id):
        return {"ok": True, "results": [{"type": "us", "failedBatches": 0}]}

    original_backup = job._backup_running
    job._backup_running = lambda: True
    job._publish_fn = publish
    job._refresh_fn = refresh
    try:
        deferred = job.run_once()
        check("03:30 备份运行中 ⇒ 发布让位，仍停在 candidate_ready",
              deferred.get("state") == "candidate_ready"
              and deferred.get("nextAttemptAt")
              and (deferred.get("lastError") or {}).get("kind") == "backup"
              and published == [],
              str(deferred)[:220])
        job._backup_running = lambda: False
        resumed = job.run_once()
        check("备份结束后发布恢复，不丢候选",
              resumed.get("state") == "refreshing" and published == [sid],
              f"state={resumed.get('state')} published={published}")
    finally:
        job._backup_running = original_backup
        job._publish_fn = _unexpected_publish
        job._refresh_fn = _unexpected_refresh


# ---------- 9. 单飞 / 启动即 collecting / 重启恢复 ----------


class _AliveThread:
    def is_alive(self) -> bool:
        return True


def test_single_flight_and_startup_resume() -> None:
    fresh_job()
    job._thread = _AliveThread()
    result = job.ensure_running("manual")
    check("已有 worker ⇒ 单飞，不重复买页",
          result.get("started") is False and result.get("reason") == "already-running",
          str(result)[:160])
    job.reset_for_tests()

    # 起跑前先把状态置为 collecting：调用方在 worker 跑第一页之前读 status 不能看到 idle。
    fresh_job()
    seen: list[str] = []
    started = threading.Event()
    original_worker = job._worker

    def fake_worker():
        seen.append(job.status().get("state"))
        started.set()

    job._worker = fake_worker
    try:
        result = job.ensure_running("daily")
        started.wait(2.0)
        check("ensure_running 起跑前已置 collecting",
              result.get("started") is True
              and result.get("status", {}).get("state") == "collecting"
              and seen == ["collecting"]
              and state().get("state") == "collecting",
              f"result={result} seen={seen}")
    finally:
        job._worker = original_worker
        job.shutdown()

    today = job.beijing_today()
    fresh_job()
    job._patch_state(state="completed", completedDate=today, snapshotId="s1")
    result = job.ensure_running("daily")
    check("当日已完成 ⇒ 不重复起跑", result.get("started") is False and result.get("reason") == "completed-today", str(result)[:160])

    job._patch_state(state="blocked", blockedDate=today, blockedReason="x")
    result = job.ensure_running("daily")
    check("当日 blocked ⇒ 不自动重试", result.get("started") is False and result.get("reason") == "blocked-today", str(result)[:160])

    fresh_job()
    result = job.resume_on_startup()
    check("重启恢复：idle 不凭空开新一轮",
          result.get("started") is False and result.get("reason") == "no-unfinished-job",
          str(result)[:160])

    job._patch_state(state="waiting", snapshotId="s2", nextAttemptAt=None)
    started.clear()
    seen.clear()
    job._worker = fake_worker
    try:
        result = job.resume_on_startup()
        started.wait(2.0)
        check("重启恢复：waiting 任务继续（同 snapshotId）",
              result.get("started") is True and state().get("snapshotId") == "s2",
              str(result)[:160])
    finally:
        job._worker = original_worker
        job.shutdown()

    fresh_job()
    job._patch_state(state="completed", completedDate=today, snapshotId="s3")
    result = job.resume_on_startup()
    check("重启恢复：已收尾任务不再跑", result.get("started") is False, str(result)[:160])

    fresh_job()
    worker_seen = threading.Event()

    def waiting_worker():
        worker_seen.set()
        job._stop.wait(5.0)

    job._worker = waiting_worker
    try:
        job.ensure_running("manual")
        worker_seen.wait(2.0)
        thread = job._thread
        job.shutdown()
        check("shutdown 通知并回收 worker", thread is not None and not thread.is_alive())
    finally:
        job._worker = original_worker
        job.reset_for_tests()


# ---------- 10. 状态观测 / 候选生命周期 ----------


def test_status_and_candidate_lifecycle() -> None:
    fresh_job()
    clock = Clock()
    up = Upstream(80, clock=clock)  # 4 页
    with JobEnv(up, burst=2, clock=clock):
        st = job.run_once()
    check("部分采集的 status 可读：resolved/required/pending",
          st.get("state") == "waiting"
          and job.status()["resolvedPages"] == 3
          and job.status()["requiredPages"] == 4
          and job.status()["pendingPages"] == 1,
          str(job.status())[:200])
    check("部分采集没有 candidate", job.get_ready_candidate() is None)

    up.calls.clear()
    with JobEnv(up, burst=1e9, clock=clock):
        st = job.run_once()
    sid = st["snapshotId"]
    check("补齐后 status 归零 pending",
          st.get("state") == "candidate_ready"
          and job.status()["pendingPages"] == 0
          and job.status()["declaredCount"] == 80,
          str(job.status())[:200])
    check("候选生命周期：candidate_ready 可取回", job.get_ready_candidate() is not None)

    job._patch_state(state="completed", completedDate="2000-01-01")
    check("昨日 completed 不重复交付（避免重启后二次发布）", job.get_ready_candidate() is None)
    job._patch_state(state="blocked", blockedReason="x")
    check("blocked 不交付候选", job.get_ready_candidate() is None)
    check("blocked 的 status 保留原因",
          job.status()["blockedReason"] == "x" and job.status()["state"] == "blocked")


# ---------- 11. 声明恢复 / 退避 / 环境上限 ----------


def test_manifest_recovery_and_backoff() -> None:
    fresh_job()
    sid = "20260101-000000-abc123"
    rows = Upstream(40).rows(1)
    job._write_page(sid, 1, "40", rows)  # 页文件已写
    job._write_json(
        job._manifest_path(sid),
        {
            "schemaVersion": 1,
            "snapshotId": sid,
            "source": "sina-us-category-list",
            "declaredCount": None,  # manifest 还没登记声明
            "requiredPages": None,
            "completedPages": [],
            "pageHashes": {},
            "createdAt": "2026-01-01T00:00:00+08:00",
            "lastProgressAt": "2026-01-01T00:00:00+08:00",
            "attemptsByPage": {},
            "failuresByPage": {},
            "probe": None,
            "superseded": False,
        },
    )
    job._save_state({**job._default_state(), "state": "collecting", "snapshotId": sid, "trigger": "test"})
    up = Upstream(40)
    with JobEnv(up):
        st = job.run_once()
    check("manifest 丢声明时从 p1 页文件恢复，不重采 p1",
          st.get("state") == "candidate_ready" and up.calls == [2, 3],
          f"calls={up.calls}")
    check("恢复后的声明/页义务正确",
          (job._load_manifest(sid) or {}).get("declaredCount") == 40
          and (job._load_manifest(sid) or {}).get("requiredPages") == 2,
          str(job._load_manifest(sid))[:180])

    check("退避序列：无进展 60→120→300→600 封顶",
          job._next_backoff({}, False) == 60
          and job._next_backoff({"backoffS": 60}, False) == 120
          and job._next_backoff({"backoffS": 120}, False) == 300
          and job._next_backoff({"backoffS": 300}, False) == 600
          and job._next_backoff({"backoffS": 600}, False) == 600)
    check("有成功页立即回到最短等待", job._next_backoff({"backoffS": 600}, True) == 60)

    prev = os.environ.get("US_LIST_BURST_TIMEOUT_S")
    try:
        os.environ["US_LIST_BURST_TIMEOUT_S"] = "12.5"
        check("突发上限可由 env 覆盖（不是整任务最终期限）", job._burst_timeout_s() == 12.5)
        os.environ["US_LIST_BURST_TIMEOUT_S"] = "abc"
        check("非法突发上限回落默认", job._burst_timeout_s() == job.US_LIST_WHOLE_TIMEOUT_S)
        os.environ.pop("US_LIST_BURST_TIMEOUT_S", None)
        check("未配置时用默认 1500s 单轮上限", job._burst_timeout_s() == job.US_LIST_WHOLE_TIMEOUT_S)
    finally:
        if prev is None:
            os.environ.pop("US_LIST_BURST_TIMEOUT_S", None)
        else:
            os.environ["US_LIST_BURST_TIMEOUT_S"] = prev


# ---------- 12. 采集阶段零 SQLite 依赖 ----------


def test_collection_has_no_sqlite_dependency() -> None:
    source = open(job.__file__, encoding="utf-8").read()
    check("持久化任务不 import sqlite/prisma（采集只写检查点）",
          "import sqlite3" not in source and "from prisma" not in source)
    check("发布账本的权威表名不在 DS 侧出现（幂等由 Web SQLite 事务负责）",
          "Product_snapshot_publication" not in source)


if __name__ == "__main__":
    test_candidate_checkpoint_and_policy_subset()
    test_923_pages_across_rounds_and_restart()
    test_orphan_and_corrupt_pages()
    test_declaration_change_supersedes()
    test_fail_closed_shapes()
    test_budget_and_first_page_failure()
    test_publish_retry_and_refresh_partial()
    test_publish_rejected_and_missing_candidate()
    test_publish_yields_to_backup()
    test_single_flight_and_startup_resume()
    test_status_and_candidate_lifecycle()
    test_manifest_recovery_and_backoff()
    test_collection_has_no_sqlite_dependency()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
