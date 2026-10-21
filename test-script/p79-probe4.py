"""#79 后续（10-17 09:30 重试用）：先立对照组，通则跑 A/B 两臂。

标签是 10-17 00:3x 换的（刀 3＝`facdbf6` 之后盘上白名单多了 `ZeroDivisionError`，而旧写法把两枚
写成"盘上"＝贴错标签，会把一枚错读数的字面抄进账）。现在两臂各测：

- **A 臂＝盘上现值**（不硬写，从 `pl._BOARD_DATA_SHAPE_ERRORS` 读）⇒ 看的是刀 1＋刀 2：每条腿
  实际落的种类（`legOutcomes`）与"一次映射只回报一次"在真上游上成不成立（回报计数）。
- **B 臂＝摘掉 `ZeroDivisionError`**（＝刀 3 之前的判据）⇒ 只有真上游抛 `ZeroDivisionError`
  （板块**存在**但零成分）时两臂才分岔：A 换下一腿、B 整族转新浪。两臂同形＝本轮没买到刀 3 的
  分岔，读数照抄这一句。

`TypeError` 那一形本轮**不测**＝#79 已就地判"不进白名单"并由绿字钉住（要放宽必须先改那枚绿字），
而"该代码无成分"与"东财软拒"在源码层同形、不可按需制造 ⇒ 交给 `boardPaths["legs"].byClass`
每轮实网自己积累。打点形状沿用上一轮：概念腿挂一枚**不存在**的 BK 代码（1 个 HTTP 那一档），
行业腿挂真代码 BK1033，两臂合计至多 1＋2 发，对照不通就停手。
"""

import logging
import os
import tempfile
import time

os.environ["LIMITER_STATE_FILE"] = os.path.join(tempfile.mkdtemp(prefix="p79c-"), "limiter.json")
logging.basicConfig(level=logging.INFO, format="LOG %(levelname)s %(name)s %(message)s")

import akshare as ak  # noqa: E402

import app.main  # noqa: E402,F401
from app.hotspot import pipeline as pl  # noqa: E402

DISK = tuple(pl._BOARD_DATA_SHAPE_ERRORS)  # 盘上现值，落笔时读，不写死
NARROW = tuple(t for t in DISK if t is not ZeroDivisionError)  # ＝刀 3 之前的判据
REAL = "BK1033"  # 电源设备（离线用例里那枚真代码）

try:
    df = pl._ak_guarded(lambda: ak.stock_board_industry_cons_em(symbol=REAL), 45.0, "p79-control")
    print("对照：真代码 %s → 返回行数＝%s｜列＝%s" % (
        REAL, "None" if df is None else len(df), list(df.columns)[:6] if df is not None else "-"
    ))
    control_ok = df is not None and len(df) > 0
except Exception as e:  # noqa: BLE000
    print("对照：真代码 %s 也抛了＝%s｜%s" % (REAL, type(e).__name__, str(e)[:180]))
    control_ok = False

print("东财桶此刻＝granted:%s 连续失败:%s cooldown:%s" % (
    pl._EM.state().get("granted"), pl._EM.state().get("consecutiveFailures"),
    pl._EM.state().get("cooldown")))

if control_ok:
    # 回报计数：包一层再委托真方法 ⇒ 熔断照旧真计，只是这一臂报了几枚读得到（C29 的判别对象）。
    real_ok, real_fail = pl._EM.on_success, pl._EM.on_failure
    counts = {"ok": 0, "fail": 0}
    pl._EM.on_success = lambda: (counts.__setitem__("ok", counts["ok"] + 1), real_ok())[1]
    pl._EM.on_failure = lambda: (counts.__setitem__("fail", counts["fail"] + 1), real_fail())[1]

    BOARD = "P79第三轮板"
    pl._board_cache["codes"] = (time.time(), {BOARD: {"em-concept": "BK9999", "em-industry": REAL}})
    for label, wl in (("A 臂＝盘上现值", DISK), ("B 臂＝摘掉 ZeroDivisionError", NARROW)):
        counts["ok"] = counts["fail"] = 0
        pl._BOARD_DATA_SHAPE_ERRORS = wl
        r = pl.map_board_products(BOARD, limit=3)
        print("%s｜白名单＝%s" % (label, tuple(t.__name__ for t in wl)))
        print("    source:%s pathForms:%s 成分:%s" % (r["source"], r["pathForms"], len(r["stocks"])))
        print("    legOutcomes:%s｜回报＝ok:%s fail:%s（一次映射只回报一次 ⇒ 至多一枚）" % (
            r.get("legOutcomes"), counts["ok"], counts["fail"]))
    print("两臂各测什么＝A＝刀 1＋刀 2 的真上游读数；B＝只有真上游抛 ZeroDivisionError 时才与 A 分岔。")
    print("东财桶终态＝granted:%s 连续失败:%s cooldown:%s" % (
        pl._EM.state().get("granted"), pl._EM.state().get("consecutiveFailures"),
        pl._EM.state().get("cooldown")))
else:
    print("对照组不通 ⇒ 此刻东财成分端点整体不可达，『该 BK 代码无成分那一形』与『东财拒绝那一形』"
          "还是分不开，两臂都不打（不继续花钱）。")
