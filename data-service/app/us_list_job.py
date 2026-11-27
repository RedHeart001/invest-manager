"""CR10-49：美股完整名单的持久化采集任务。

目标不是“让一次 HTTP 请求跑得更久”，而是把 923 页拆成可跨轮、跨重启继续的检查点：

- 每成功一页先原子落页文件，再更新 manifest；
- 1500s 只是单轮突发上限，到期进入 waiting，下一轮从缺口继续；
- 声明变化废弃当前 generation，绝不跨声明拼页；
- 完整候选通过页义务、去重、穷尽空页和映射验证后才写 candidate；
- candidate 由 Web 按 snapshotId 幂等发布，发布成功后才刷新 us 行情；
- 采集阶段只写 runtime 检查点，不写 SQLite，03:30 备份不被慢采集堵住。

状态机：idle → collecting ⇄ waiting → candidate_ready → publishing →
publish_unknown → refreshing ⇄ refresh_pending → completed；不可恢复的本地验证
矛盾进入 blocked，不反复提交同一份不合法候选。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from .providers.akshare_provider import (
    US_LIST_REPAIR_ROUNDS,
    US_LIST_SHORT_PAGE_RETRIES,
    US_LIST_WHOLE_TIMEOUT_S,
    _us_expected_rows,
    _us_list_pages,
    _us_page_count,
    map_us_snapshot,
    request_us_page,
    validate_us_snapshot,
    UsSnapshotChanged,
)
from .utils.http import direct_proxies, direct_session
from .utils.timeutil import beijing_today

log = logging.getLogger("us.list.job")

TZ = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = 1
SOURCE = "sina-us-category-list"

# 退避序列：普通轮间等待 60s；连续无进展才逐级抬到 600s。有成功页立即回到 60s。
_BACKOFF_SEQUENCE = (60, 120, 300, 600)
_PUBLISH_TIMEOUT_S = 300.0
_REFRESH_TIMEOUT_S = 2400.0
_BACKUP_YIELD_S = 60.0
_SUPERSEDE_RECHECK_S = 5.0

_lock = threading.RLock()
_thread: threading.Thread | None = None
_stop = threading.Event()

# 测试注入点：默认走 provider 的真实单页请求；测试可替换为纯内存假实现。
page_fetcher = request_us_page
_publish_fn = None
_refresh_fn = None


# ---------- 路径与原子读写 ----------


def _job_dir() -> str:
    env = os.environ.get("US_LIST_JOB_DIR", "")
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "runtime", "us-list-job")


def _state_path() -> str:
    return os.path.join(_job_dir(), "state.json")


def _generation_dir(snapshot_id: str) -> str:
    return os.path.join(_job_dir(), "generations", snapshot_id)


def _manifest_path(snapshot_id: str) -> str:
    return os.path.join(_generation_dir(snapshot_id), "manifest.json")


def _page_path(snapshot_id: str, page: int) -> str:
    return os.path.join(_generation_dir(snapshot_id), "pages", f"{page:06d}.json")


def _candidate_path(snapshot_id: str) -> str:
    return os.path.join(_generation_dir(snapshot_id), "candidate.json")


def _now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _future_iso(seconds: float) -> str:
    return (datetime.now(TZ) + timedelta(seconds=max(0.0, seconds))).isoformat(timespec="seconds")


def _seconds_until(value: str | None) -> float | None:
    if not value:
        return None
    try:
        target = datetime.fromisoformat(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=TZ)
        return max(0.0, (target - datetime.now(TZ)).total_seconds())
    except (TypeError, ValueError):
        return None


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def _rows_hash(rows: list[dict]) -> str:
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------- 状态 ----------


def _default_state() -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "idle",
        "snapshotId": None,
        "trigger": None,
        "createdAt": None,
        "updatedAt": None,
        "lastProgressAt": None,
        "nextAttemptAt": None,
        "backoffS": 0,
        "lastError": None,
        "lastPublishedSnapshotId": None,
        "lastPublishedAt": None,
        "lastCompletedAt": None,
        "completedDate": None,
        "blockedReason": None,
        "blockedDate": None,
        "pagesResolved": 0,
        "requiredPages": 0,
        "declaredCount": 0,
        "publishedCount": None,
        "refreshOutcome": None,
    }


def _load_state() -> dict:
    data = _read_json(_state_path())
    if not isinstance(data, dict):
        return _default_state()
    return {**_default_state(), **data}


def _save_state(state: dict) -> dict:
    state = {**state, "schemaVersion": SCHEMA_VERSION, "updatedAt": _now_iso()}
    _write_json(_state_path(), state)
    return state


def _patch_state(**changes) -> dict:
    with _lock:
        state = _load_state()
        state.update(changes)
        return _save_state(state)


# ---------- generation / 页文件 ----------


def _new_snapshot_id() -> str:
    return datetime.now(TZ).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def _new_generation(trigger: str | None) -> dict:
    snapshot_id = _new_snapshot_id()
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "snapshotId": snapshot_id,
        "source": SOURCE,
        "declaredCount": None,
        "requiredPages": None,
        "completedPages": [],
        "pageHashes": {},
        "createdAt": _now_iso(),
        "lastProgressAt": _now_iso(),
        "attemptsByPage": {},
        "failuresByPage": {},
        "probe": None,
        "superseded": False,
    }
    _write_json(_manifest_path(snapshot_id), manifest)
    state = _load_state()
    state.update(
        {
            "state": "collecting",
            "snapshotId": snapshot_id,
            "trigger": trigger,
            "createdAt": manifest["createdAt"],
            "lastProgressAt": manifest["lastProgressAt"],
            "nextAttemptAt": None,
            "backoffS": 0,
            "lastError": None,
            "blockedReason": None,
            "blockedDate": None,
            "pagesResolved": 0,
            "requiredPages": 0,
            "declaredCount": 0,
            "publishedCount": None,
            "refreshOutcome": None,
        }
    )
    _save_state(state)
    return manifest


def _load_manifest(snapshot_id: str | None) -> dict | None:
    if not snapshot_id:
        return None
    data = _read_json(_manifest_path(snapshot_id))
    return data if isinstance(data, dict) else None


def _save_manifest(manifest: dict) -> None:
    manifest["lastProgressAt"] = _now_iso()
    _write_json(_manifest_path(manifest["snapshotId"]), manifest)


def _read_page(snapshot_id: str, page: int) -> dict | None:
    data = _read_json(_page_path(snapshot_id, page))
    if not isinstance(data, dict):
        return None
    rows = data.get("rows")
    if not isinstance(rows, list) or data.get("page") != page:
        return None
    if data.get("sha256") != _rows_hash(rows):
        return None
    return data


def _write_page(snapshot_id: str, page: int, declared: str, rows: list[dict]) -> str:
    digest = _rows_hash(rows)
    _write_json(
        _page_path(snapshot_id, page),
        {
            "schemaVersion": SCHEMA_VERSION,
            "page": page,
            "declaredCount": str(declared),
            "rows": rows,
            "sha256": digest,
            "savedAt": _now_iso(),
        },
    )
    return digest


_PAGE_FILE_RE = re.compile(r"^(\d{6})\.json$")


def _verify_generation(manifest: dict) -> tuple[dict, dict[int, list[dict]]]:
    """按页文件内容重建可信页集合。

    页文件先写、manifest 后写，所以目录里可能已有未登记的页；也可能有半截/被手改的
    页。这里逐页核对页号、声明和 SHA-256：合格页补登记，损坏页只丢该页（下一轮重采）。
    """
    snapshot_id = manifest["snapshotId"]
    declared = manifest.get("declaredCount")
    pages_dir = os.path.join(_generation_dir(snapshot_id), "pages")
    pages: dict[int, list[dict]] = {}
    hashes: dict[str, str] = {}
    try:
        names = os.listdir(pages_dir)
    except OSError:
        names = []
    for name in names:
        match = _PAGE_FILE_RE.match(name)
        if not match:
            continue
        page = int(match.group(1))
        data = _read_page(snapshot_id, page)
        if data is None:
            continue
        if declared is not None and str(data.get("declaredCount")) != str(declared):
            continue
        pages[page] = data["rows"]
        hashes[str(page)] = data["sha256"]
    completed = sorted(pages)
    changed = completed != manifest.get("completedPages") or hashes != manifest.get("pageHashes")
    manifest["completedPages"] = completed
    manifest["pageHashes"] = hashes
    if 1 in pages and declared is None:
        first_declared = str(_read_page(snapshot_id, 1).get("declaredCount"))
        if first_declared.isdigit():
            manifest["declaredCount"] = int(first_declared)
            manifest["requiredPages"] = _us_page_count(int(first_declared))
            changed = True
    if changed:
        _save_manifest(manifest)
    return manifest, pages


def _update_progress(manifest: dict, resolved: int) -> dict:
    state = _load_state()
    previous = int(state.get("pagesResolved") or 0)
    state.update(
        {
            "pagesResolved": resolved,
            "requiredPages": manifest.get("requiredPages") or 0,
            "declaredCount": manifest.get("declaredCount") or 0,
            "lastProgressAt": _now_iso(),
        }
    )
    if resolved > previous:
        state["backoffS"] = 0
        state["lastError"] = None
    return _save_state(state)


def _next_backoff(state: dict, progressed: bool) -> int:
    if progressed:
        return _BACKOFF_SEQUENCE[0]
    current = int(state.get("backoffS") or 0)
    for value in _BACKOFF_SEQUENCE:
        if value > current:
            return value
    return _BACKOFF_SEQUENCE[-1]


def _wait(manifest: dict, reason: str, *, progressed: bool, error_kind: str = "network") -> dict:
    state = _load_state()
    delay = _next_backoff(state, progressed)
    state.update(
        {
            "state": "waiting",
            "snapshotId": manifest.get("snapshotId") or state.get("snapshotId"),
            "pagesResolved": len(manifest.get("completedPages") or []),
            "requiredPages": manifest.get("requiredPages") or state.get("requiredPages") or 0,
            "declaredCount": manifest.get("declaredCount") or state.get("declaredCount") or 0,
            "nextAttemptAt": _future_iso(delay),
            "backoffS": delay,
            "lastError": {"kind": error_kind, "message": reason, "at": _now_iso()},
        }
    )
    log.warning("us list job waiting %ss: %s", delay, reason)
    return _save_state(state)


def _block(manifest: dict, reason: str) -> dict:
    state = _load_state()
    state.update(
        {
            "state": "blocked",
            "snapshotId": manifest.get("snapshotId") or state.get("snapshotId"),
            "pagesResolved": len(manifest.get("completedPages") or []),
            "requiredPages": manifest.get("requiredPages") or state.get("requiredPages") or 0,
            "declaredCount": manifest.get("declaredCount") or state.get("declaredCount") or 0,
            "nextAttemptAt": None,
            "blockedReason": reason,
            "blockedDate": beijing_today(),
            "lastError": {"kind": "validation", "message": reason, "at": _now_iso()},
        }
    )
    log.error("us list job blocked: %s", reason)
    return _save_state(state)


def _supersede(manifest: dict, reason: str) -> dict:
    manifest["superseded"] = True
    manifest["supersededReason"] = reason
    _save_manifest(manifest)
    state = _load_state()
    state.update(
        {
            "state": "waiting",
            "snapshotId": None,
            "pagesResolved": 0,
            "requiredPages": 0,
            "declaredCount": 0,
            "nextAttemptAt": _future_iso(_SUPERSEDE_RECHECK_S),
            "backoffS": 0,
            "lastError": {"kind": "declaration_changed", "message": reason, "at": _now_iso()},
        }
    )
    log.warning("us list generation superseded: %s", reason)
    return _save_state(state)


# ---------- 单轮采集 ----------


def _burst_timeout_s() -> float:
    try:
        return float(os.environ.get("US_LIST_BURST_TIMEOUT_S", str(US_LIST_WHOLE_TIMEOUT_S)))
    except ValueError:
        return float(US_LIST_WHOLE_TIMEOUT_S)


def _request_declared(
    page: int,
    session,
    deadline: float,
    manifest: dict | None = None,
    expected_rows: int | None = None,
) -> tuple[str, list[dict]]:
    """同页有界恢复；声明变化立即上抛，不吞进失败页账本。

    `expected_rows` 让短页与网络/解析异常共用同一份同页次数预算——这与
    `collect_us_snapshot` 的 `request_obligation` 是同一个上限，不额外放宽。
    """
    last: Exception | None = None
    for attempt in range(US_LIST_SHORT_PAGE_RETRIES + 1):
        if time.monotonic() > deadline:
            raise RuntimeError("us list burst deadline reached")
        try:
            declared, rows = page_fetcher(page, session, deadline)
            if manifest is not None and manifest.get("declaredCount") is not None:
                if str(declared) != str(manifest["declaredCount"]):
                    raise UsSnapshotChanged(
                        f"us list declaration changed during snapshot: "
                        f"{manifest['declaredCount']} -> {declared}"
                    )
            if expected_rows is not None and len(rows) != expected_rows:
                raise ValueError(f"expected {expected_rows} rows, got {len(rows)}")
            return str(declared), rows
        except UsSnapshotChanged:
            raise
        except Exception as exc:  # noqa: BLE001 每页同页有界恢复
            last = exc
            log.warning(
                "us list page %s attempt %s/%s unresolved: %s",
                page,
                attempt + 1,
                US_LIST_SHORT_PAGE_RETRIES + 1,
                exc,
            )
    raise RuntimeError(
        f"us list page {page} unresolved after {US_LIST_SHORT_PAGE_RETRIES + 1} attempts: {last}"
    )


def _request_page(
    page: int, session, deadline: float, manifest: dict, declared: int
) -> list[dict]:
    expected = _us_expected_rows(page, declared)
    page_declared, rows = _request_declared(
        page, session, deadline, manifest, expected_rows=expected
    )
    if str(page_declared) != str(declared):
        raise UsSnapshotChanged(
            f"us list declaration changed during snapshot: {declared} -> {page_declared}"
        )
    return rows


def _collect_once(trigger: str | None = None) -> dict:
    state = _load_state()
    manifest = _load_manifest(state.get("snapshotId"))
    if manifest is None or manifest.get("superseded"):
        manifest = _new_generation(trigger or state.get("trigger") or "manual")
    manifest, pages = _verify_generation(manifest)
    snapshot_id = manifest["snapshotId"]

    declared_value = manifest.get("declaredCount")
    declared = int(declared_value) if declared_value else 0
    required = int(manifest.get("requiredPages") or 0) if declared else 0
    deadline = time.monotonic() + _burst_timeout_s()
    progressed = False
    session = direct_session(requests) if hasattr(requests, "Session") else requests

    try:
        if not declared:
            # 首页同时建立声明与页义务；短页也在同一页有界恢复，不能一发即弃。
            first_rows: list[dict] | None = None
            for attempt in range(US_LIST_SHORT_PAGE_RETRIES + 1):
                if time.monotonic() > deadline:
                    return _wait(manifest, "burst deadline before first page", progressed=False)
                try:
                    declared_raw, rows = page_fetcher(1, session, deadline)
                    total = int(declared_raw)
                    required = _us_page_count(total)
                    budget = _us_list_pages()
                    if required > budget:
                        return _block(
                            manifest,
                            f"us list page budget {budget} < required {required}; "
                            "truncated snapshots are not publishable",
                        )
                    expected = _us_expected_rows(1, total)
                    if len(rows) != expected:
                        raise ValueError(f"expected {expected} rows, got {len(rows)}")
                    declared = total
                    first_rows = rows
                    break
                except Exception as exc:  # noqa: BLE001 首页同页有界恢复
                    log.warning(
                        "us list first page attempt %s/%s unresolved: %s",
                        attempt + 1,
                        US_LIST_SHORT_PAGE_RETRIES + 1,
                        exc,
                    )
            if first_rows is None:
                return _wait(manifest, "us list first page unresolved; no snapshot candidate", progressed=False)
            manifest["declaredCount"] = declared
            manifest["requiredPages"] = required
            digest = _write_page(snapshot_id, 1, str(declared), first_rows)
            manifest["completedPages"] = [1]
            manifest["pageHashes"] = {"1": digest}
            _save_manifest(manifest)
            pages[1] = first_rows
            progressed = True
            _update_progress(manifest, len(pages))
        else:
            if 1 in pages:
                first_declared = str(_read_page(snapshot_id, 1).get("declaredCount"))
                if first_declared != str(declared):
                    return _supersede(
                        manifest,
                        f"us list declaration changed while resuming: {declared} -> {first_declared}",
                    )

        failures: dict[int, str] = {}
        for page in range(1, required + 1):
            if page in pages:
                continue
            if time.monotonic() > deadline:
                return _wait(manifest, f"burst deadline with {len(pages)}/{required} pages resolved", progressed=progressed)
            try:
                rows = _request_page(page, session, deadline, manifest, declared)
            except UsSnapshotChanged as exc:
                return _supersede(manifest, str(exc))
            except Exception as exc:  # noqa: BLE001 单页失败留待集中修复
                failures[page] = str(exc)
                continue
            digest = _write_page(snapshot_id, page, str(declared), rows)
            pages[page] = rows
            manifest["completedPages"] = sorted(pages)
            manifest["pageHashes"][str(page)] = digest
            manifest["attemptsByPage"][str(page)] = int(manifest.get("attemptsByPage", {}).get(str(page), 0)) + 1
            _save_manifest(manifest)
            progressed = True
            _update_progress(manifest, len(pages))

        # 首轮失败的页不丢弃、不拼成子集；最多再做两轮集中修复。
        for repair_round in range(US_LIST_REPAIR_ROUNDS):
            if not failures:
                break
            if time.monotonic() > deadline:
                return _wait(
                    manifest,
                    f"burst deadline with {len(failures)} pages pending repair",
                    progressed=progressed,
                )
            log.info("us list repair round %s: %s pages", repair_round + 1, len(failures))
            repair_session = direct_session(requests) if hasattr(requests, "Session") else requests
            try:
                for page in sorted(failures):
                    if time.monotonic() > deadline:
                        return _wait(
                            manifest,
                            f"burst deadline during repair with {len(failures)} pages pending",
                            progressed=progressed,
                        )
                    try:
                        rows = _request_page(page, repair_session, deadline, manifest, declared)
                    except UsSnapshotChanged as exc:
                        return _supersede(manifest, str(exc))
                    except Exception as exc:  # noqa: BLE001 修复轮仍有界
                        failures[page] = str(exc)
                        continue
                    digest = _write_page(snapshot_id, page, str(declared), rows)
                    pages[page] = rows
                    manifest["completedPages"] = sorted(pages)
                    manifest["pageHashes"][str(page)] = digest
                    manifest["attemptsByPage"][str(page)] = int(manifest.get("attemptsByPage", {}).get(str(page), 0)) + 1
                    failures.pop(page, None)
                    _save_manifest(manifest)
                    progressed = True
                    _update_progress(manifest, len(pages))
            finally:
                close = getattr(repair_session, "close", None)
                if close:
                    close()

        if failures:
            manifest["failuresByPage"] = {str(page): reason for page, reason in sorted(failures.items())}
            _save_manifest(manifest)
            return _wait(
                manifest,
                f"us list incomplete snapshot: {len(pages)}/{required} pages resolved",
                progressed=progressed,
            )

        # 声明范围之外必须为空，防止声明过小而漏掉仍存在的后续名单。
        probe_page = required + 1
        try:
            probe_declared, probe_rows = _request_declared(probe_page, session, deadline, manifest)
        except UsSnapshotChanged as exc:
            return _supersede(manifest, str(exc))
        except Exception as exc:  # noqa: BLE001 穷尽证明本身也必须可恢复
            return _wait(
                manifest,
                f"us list exhaustion probe p{probe_page} unresolved: {exc}",
                progressed=progressed,
            )
        if str(probe_declared) != str(declared):
            return _supersede(
                manifest,
                f"us list declaration changed at exhaustion probe: {declared} -> {probe_declared}",
            )
        if probe_rows:
            return _block(
                manifest,
                f"us list exhaustion probe p{probe_page} returned {len(probe_rows)} rows",
            )
        manifest["probe"] = {
            "page": probe_page,
            "declaredCount": str(declared),
            "rows": 0,
            "probedAt": _now_iso(),
        }
        _save_manifest(manifest)

        try:
            raw_rows = validate_us_snapshot(
                pages, declared, required, str(probe_declared), probe_rows, probe_page
            )
            products, meta = map_us_snapshot(raw_rows, declared, required, probe_page)
        except UsSnapshotChanged as exc:
            return _supersede(manifest, str(exc))
        except Exception as exc:  # noqa: BLE001 完整性矛盾不进入发布
            return _block(manifest, str(exc))

        candidate = {
            "snapshotId": snapshot_id,
            "count": len(products),
            "products": products,
            **meta,
        }
        _write_json(_candidate_path(snapshot_id), candidate)
        state = _load_state()
        state.update(
            {
                "state": "candidate_ready",
                "snapshotId": snapshot_id,
                "pagesResolved": required,
                "requiredPages": required,
                "declaredCount": declared,
                "publishedCount": None,
                "nextAttemptAt": None,
                "lastProgressAt": _now_iso(),
                "lastError": None,
            }
        )
        _save_state(state)
        log.info("us list candidate ready: %s (%s products)", snapshot_id, len(products))
        return state
    finally:
        close = getattr(session, "close", None)
        if close:
            close()


# ---------- 发布 / 刷新 ----------


class _PublishRejected(Exception):
    """Web 明确拒绝候选（完整性/缩水闸/结构），重试同一份没有意义。"""


class _PublishTransient(Exception):
    """网络、超时、5xx：结果未知，按 snapshotId 幂等重试。"""


def _web_base() -> str:
    # 与 sync_scheduler 同口径：localhost 会先试 ::1，web 只监听 IPv4 ⇒ 白白多一次连接等待。
    return os.environ.get("WEB_BASE_URL", "http://127.0.0.1:3000")


def _write_headers() -> dict[str, str]:
    token = os.environ.get("WRITE_TOKEN", "")
    return {"x-write-token": token} if token else {}


def _post_publish(candidate: dict) -> dict:
    try:
        response = requests.post(
            f"{_web_base()}/api/sync/us-snapshot",
            json=candidate,
            timeout=_PUBLISH_TIMEOUT_S,
            headers=_write_headers(),
            proxies=direct_proxies(),
        )
    except Exception as exc:  # noqa: BLE001 连接失败/超时都按“结果未知”重试
        raise _PublishTransient(f"{type(exc).__name__}: {exc}") from exc
    body: dict = {}
    try:
        parsed = response.json()
        body = parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001 非 JSON 响应按状态码判定
        body = {}
    if response.status_code >= 500:
        raise _PublishTransient(f"HTTP {response.status_code}: {response.text[:300]}")
    if response.status_code >= 300 or body.get("ok") is False or body.get("error"):
        raise _PublishRejected(
            f"HTTP {response.status_code}: {body.get('error') or response.text[:300]}"
        )
    return body


def _backup_running() -> bool:
    try:
        from . import backup_scheduler

        return bool(backup_scheduler._state.get("running"))
    except Exception:  # noqa: BLE001 观测不到备份不阻断发布；SQLite 在线备份仍保证一致性
        return False


def _publish_once() -> dict:
    state = _load_state()
    snapshot_id = state.get("snapshotId")
    candidate = _read_json(_candidate_path(snapshot_id)) if snapshot_id else None
    if not isinstance(candidate, dict) or not isinstance(candidate.get("products"), list):
        return _block(
            _load_manifest(snapshot_id) or {"snapshotId": snapshot_id, "completedPages": []},
            "candidate file missing or invalid",
        )
    if _backup_running():
        state.update(
            {
                "state": "candidate_ready",
                "nextAttemptAt": _future_iso(_BACKUP_YIELD_S),
                "lastError": {"kind": "backup", "message": "backup running; publish deferred", "at": _now_iso()},
            }
        )
        return _save_state(state)
    state.update({"state": "publishing", "nextAttemptAt": None})
    _save_state(state)
    try:
        if _publish_fn is not None:
            result = _publish_fn(candidate)
        else:
            result = _post_publish(candidate)
    except _PublishRejected as exc:
        state.update(
            {
                "state": "blocked",
                "blockedReason": str(exc),
                "blockedDate": beijing_today(),
                "nextAttemptAt": None,
                "lastError": {"kind": "publish_rejected", "message": str(exc), "at": _now_iso()},
            }
        )
        log.error("us list publish rejected: %s", exc)
        return _save_state(state)
    except Exception as exc:  # noqa: BLE001 网络/超时/5xx：结果未知
        delay = _next_backoff(state, False)
        state.update(
            {
                "state": "publish_unknown",
                "nextAttemptAt": _future_iso(delay),
                "backoffS": delay,
                "lastError": {"kind": "publish_unknown", "message": f"{type(exc).__name__}: {exc}", "at": _now_iso()},
            }
        )
        log.warning("us list publish result unknown: %s", exc)
        return _save_state(state)

    if not isinstance(result, dict):
        result = {"ok": True}
    state.update(
        {
            "state": "refreshing",
            "lastPublishedSnapshotId": snapshot_id,
            "lastPublishedAt": _now_iso(),
            "publishedCount": candidate.get("count"),
            "nextAttemptAt": None,
            "backoffS": 0,
            "lastError": None,
        }
    )
    log.info("us list published: %s", snapshot_id)
    return _save_state(state)


def _post_refresh(snapshot_id: str) -> dict:
    response = requests.post(
        f"{_web_base()}/api/market/refresh?type=us&runId=us-{snapshot_id}",
        timeout=_REFRESH_TIMEOUT_S,
        headers=_write_headers(),
        proxies=direct_proxies(),
    )
    if response.status_code >= 300:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    body = response.json() or {}
    results = body.get("results") or []
    weak = [
        str(item.get("type"))
        for item in results
        if isinstance(item, dict) and int(item.get("failedBatches") or 0) > 0
    ]
    if not results and body.get("error"):
        raise RuntimeError(str(body.get("error")))
    return {"ok": not weak, "results": results, "weakTypes": weak}


def _refresh_once() -> dict:
    state = _load_state()
    snapshot_id = state.get("snapshotId")
    state.update({"state": "refreshing", "nextAttemptAt": None})
    _save_state(state)
    try:
        if _refresh_fn is not None:
            result = _refresh_fn(snapshot_id)
        else:
            result = _post_refresh(snapshot_id)
    except Exception as exc:  # noqa: BLE001 行情刷新失败不回滚名单
        delay = _next_backoff(state, False)
        state.update(
            {
                "state": "refresh_pending",
                "nextAttemptAt": _future_iso(delay),
                "backoffS": delay,
                "refreshOutcome": "pending",
                "lastError": {"kind": "refresh", "message": f"{type(exc).__name__}: {exc}", "at": _now_iso()},
            }
        )
        log.warning("us list refresh pending: %s", exc)
        return _save_state(state)

    result = result if isinstance(result, dict) else {}
    weak = result.get("weakTypes") or []
    if result.get("ok") is False or weak:
        delay = _next_backoff(state, False)
        state.update(
            {
                "state": "refresh_pending",
                "nextAttemptAt": _future_iso(delay),
                "backoffS": delay,
                "refreshOutcome": "partial_failed",
                "lastError": {
                    "kind": "refresh_partial",
                    "message": f"failed batches: {', '.join(str(x) for x in weak) or 'unknown'}",
                    "at": _now_iso(),
                },
            }
        )
        log.warning("us list refresh partially failed: %s", weak)
        return _save_state(state)

    state.update(
        {
            "state": "completed",
            "completedDate": beijing_today(),
            "lastCompletedAt": _now_iso(),
            "nextAttemptAt": None,
            "backoffS": 0,
            "refreshOutcome": "completed",
            "lastError": None,
        }
    )
    log.info("us list job completed: %s", snapshot_id)
    return _save_state(state)


# ---------- 调度入口 ----------


def run_once() -> dict:
    """执行状态机的一个可中断步骤；测试与 worker 共用。"""
    state = _load_state()
    phase = state.get("state")
    if phase == "idle":
        _new_generation(state.get("trigger") or "manual")
        return _collect_once(state.get("trigger") or "manual")
    if phase in ("collecting", "waiting"):
        return _collect_once(state.get("trigger") or "manual")
    if phase in ("candidate_ready", "publishing", "publish_unknown"):
        return _publish_once()
    if phase in ("refreshing", "refresh_pending"):
        return _refresh_once()
    return state


def _worker() -> None:
    global _thread
    try:
        while not _stop.is_set():
            state = run_once()
            phase = state.get("state")
            if phase in ("completed", "blocked", "idle"):
                break
            delay = _seconds_until(state.get("nextAttemptAt"))
            if delay is None:
                if phase in ("candidate_ready", "publishing", "publish_unknown", "refreshing", "refresh_pending"):
                    delay = 0.0
                else:
                    delay = 1.0
            if _stop.wait(delay):
                break
    except Exception as exc:  # noqa: BLE001 worker 崩溃要留痕，不能静默
        log.exception("us list job worker crashed: %s", exc)
        try:
            _patch_state(
                lastError={
                    "kind": "worker_crash",
                    "message": f"{type(exc).__name__}: {exc}",
                    "at": _now_iso(),
                }
            )
        except Exception:  # noqa: BLE001 状态写不进也不能再抛
            pass
    finally:
        with _lock:
            _thread = None


def ensure_running(trigger: str = "manual", force: bool = False) -> dict:
    """启动或恢复任务；已有 worker 时单飞，不重复买页。"""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return {"started": False, "reason": "already-running", "status": status()}
        state = _load_state()
        today = beijing_today()
        if state.get("state") == "completed" and state.get("completedDate") == today and not force:
            return {"started": False, "reason": "completed-today", "status": status()}
        if state.get("state") == "blocked" and state.get("blockedDate") == today and not force:
            return {"started": False, "reason": "blocked-today", "status": status()}
        if state.get("state") in ("completed", "blocked"):
            # force 或跨日重跑：旧 generation 已收尾，清掉终态再开新一轮。
            state.update(
                {
                    "snapshotId": None,
                    "completedDate": None,
                    "blockedReason": None,
                    "blockedDate": None,
                    "nextAttemptAt": None,
                    "backoffS": 0,
                    "refreshOutcome": None,
                }
            )
        if state.get("state") in ("idle", "completed", "blocked"):
            # 先把状态置为 collecting 再起 worker：调用方（_execute）会在 worker 真正
            # 跑第一页之前读 status()，停在 idle 会被误判成“没接活”。
            state["state"] = "collecting"
        state["trigger"] = trigger
        _save_state(state)
        _stop.clear()
        worker = threading.Thread(target=_worker, name="us-list-job", daemon=True)
        _thread = worker
        worker.start()
        return {"started": True, "status": status()}


def resume_on_startup() -> dict:
    """DS 重启后只恢复未收尾任务；不在非调度时刻凭空开新一轮。"""
    state = _load_state()
    if state.get("state") in (
        "collecting",
        "waiting",
        "candidate_ready",
        "publishing",
        "publish_unknown",
        "refreshing",
        "refresh_pending",
    ):
        return ensure_running(state.get("trigger") or "startup-resume")
    return {"started": False, "reason": "no-unfinished-job", "status": status()}


def shutdown() -> None:
    """停 worker；当前 HTTP 仍受单页 20s 上限，已确认页不会丢。"""
    global _thread
    _stop.set()
    with _lock:
        worker = _thread
    if worker is not None and worker.is_alive():
        worker.join(timeout=5.0)


def status() -> dict:
    state = _load_state()
    snapshot_id = state.get("snapshotId")
    manifest = _load_manifest(snapshot_id)
    if manifest is not None:
        resolved = len(manifest.get("completedPages") or [])
        required = int(manifest.get("requiredPages") or state.get("requiredPages") or 0)
        declared = int(manifest.get("declaredCount") or state.get("declaredCount") or 0)
    else:
        resolved = int(state.get("pagesResolved") or 0)
        required = int(state.get("requiredPages") or 0)
        declared = int(state.get("declaredCount") or 0)
    return {
        "state": state.get("state") or "idle",
        "snapshotId": snapshot_id,
        "resolvedPages": resolved,
        "requiredPages": required,
        "pendingPages": max(required - resolved, 0),
        "declaredCount": declared,
        "lastProgressAt": state.get("lastProgressAt") or (manifest or {}).get("lastProgressAt"),
        "nextAttemptAt": state.get("nextAttemptAt"),
        "backoffS": state.get("backoffS") or 0,
        "lastError": state.get("lastError"),
        "lastPublishedSnapshotId": state.get("lastPublishedSnapshotId"),
        "lastPublishedAt": state.get("lastPublishedAt"),
        "lastCompletedAt": state.get("lastCompletedAt"),
        "completedDate": state.get("completedDate"),
        "blockedReason": state.get("blockedReason"),
        "publishedCount": state.get("publishedCount"),
        "refreshOutcome": state.get("refreshOutcome"),
        "progress": {"resolvedPages": resolved, "requiredPages": required},
    }


def get_ready_candidate() -> dict | None:
    """返回当天可交给 Web 的完整候选；昨日 completed 不重复发布。"""
    state = _load_state()
    snapshot_id = state.get("snapshotId")
    phase = state.get("state")
    if not snapshot_id or phase not in (
        "candidate_ready",
        "publishing",
        "publish_unknown",
        "refreshing",
        "refresh_pending",
        "completed",
    ):
        return None
    if phase == "completed" and state.get("completedDate") != beijing_today():
        return None
    candidate = _read_json(_candidate_path(snapshot_id))
    if not isinstance(candidate, dict) or not isinstance(candidate.get("products"), list):
        return None
    return candidate


def reset_for_tests() -> None:
    """离线测试复位：停 worker、清注入点、保留环境变量指定的临时目录。"""
    global _thread, page_fetcher, _publish_fn, _refresh_fn
    _stop.set()
    with _lock:
        _thread = None
    page_fetcher = request_us_page
    _publish_fn = None
    _refresh_fn = None
