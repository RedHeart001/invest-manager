#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""docs 收尾体检——`.claude/rules/project.md`「docs 体量治理（2026-10-09 立）」的执行件。

除 `--move`／`--baseline --register` 外都不写盘、零出网。

  1. 体量读数：单文件 >120,000 字符／单行 >1,500 字符／单节 >30,000 字符 ⇒ 报警，不动笔。**行数不作闸**。
     单节按两把读数取并集：**叶节跨度 ∪ 容器自身体**（恒等式＝自身体＋Σ直接子节＝跨度，不重复计数）。
  2. 断链扫描：活跃工作区里每个「追加N」「第 N 项」「相对链接」「文末/见『节名』」都要能落地。
  3. 表格扫描（由 `data-service/runtime/` 三枚临时件并回本件，任何机器上都能跑）。
     列数＝去掉首尾定界符后按**未转义**竖线切分（`\\|` 算正文、不算列），与 GFM 渲染同口径。
  4. 速览尺 + TITLE 档：速览类区块非标题行 >500 ⇒ 报警；任意级标题行 >500 ⇒ 报警。

用法：
    python scripts/docs-scan.py                          # 读数＋报警（逐条）＋表格＋断链
    python scripts/docs-scan.py --selftest               # 判据自带会红的样本，全绿才算过
    python scripts/docs-scan.py --baseline               # 与已登记基线比：NEW 决定退出码＋KNOWN 只读账
    python scripts/docs-scan.py --baseline --print       # 全列（LINE 不再是 top-10）
    python scripts/docs-scan.py --baseline --register    # 把当轮清单登记为基线（写盘）
    python scripts/docs-scan.py --plan --file docs/CODE-REVIEW.md --section "追加十二"   # 打印将搬跨度，不写盘
    python scripts/docs-scan.py --list-closed            # 逐项报闭包证据（首行✅／块内✅／项尾40字）＋已搬指针行在册

口径（都按 `len(text)` 含换行，逐行和与它差「行数−1」，混用会让每轮对账多一个谜）：
    行区间的字符数 ＝ len("\\n".join(该区间各行))。

范围：超标判定只看 `docs/*.md`（活跃工作区）；`docs/history/` 只进入断链扫描的目标集合。
"""

import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile

MAX_FILE_CHARS = 120000
MAX_LINE_CHARS = 1500
MAX_SECTION_CHARS = 30000
MAX_SPEED_CHARS = 500
MAX_TITLE_CHARS = 500

SPEED_TITLES = ("状态卡", "当前状态", "速览", "状态总览")
BASELINE_PATH = os.path.join("scripts", "docs-scan-baseline.json")

HEAD = re.compile(r"^\s*>*\s*(#{1,6})\s+(.*)$")
NUM_ITEM = re.compile(r"^[0-9]{1,3}\.\s")
APPEND_REF = re.compile(r"追加[〇零一二三四五六七八九十百]+")
ITEM_REF = re.compile(r"第\s*([0-9]{1,3})\s*项")
ITEM_HEAD = re.compile(r"^([0-9]{1,3})\.\s")
# 10-12 补：搬动执行件自己写的「原地指针行」。编号项之间会夹着**别人**的指针行
# （如 FIX-LEDGER 里 #22 之后紧跟着 23/24/25 的指针），项尾判定必须在此即止——
# 否则 `--item 22` 会把 23/24/25 的指针一起卷进归档（10-12 差点踩到的那一形）。
POINTER_LINE = re.compile(r"^\s*>\s*\*\*【已搬归档】\*\*")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"^\s*```")
RANGE = re.compile(r"^(\d+)\.\.(\d+)$")
# 新形（1a-iii 补）：文末/末/见/参见 之后的引号节名，或「见 <file>.md …『节名』」
CUE_NAME = re.compile(r"(?:文末|参见|详见|见)\s*[『「《]([^』」》]{2,})[』」》]")
CUE_FILE = re.compile(r"(?:文末|参见|详见|见)\s*([A-Za-z0-9_.\-/]+\.md)")
SEP_ROW = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
# GFM 口径：`\|` 是单元正文里的竖线，不是列分隔符（表格里的 grep 模式 `A\|B` 全靠它）
CELL_SPLIT = re.compile(r"(?<!\\)\|")

QUANT_AFTER = set("个条枚行项次句要上入两段–—~-～至到")
POINTER_HINT = ("搬", "归档", "指针", "history")
APPEND_OWNER = "CODE-REVIEW.md"
META_MARKERS = ("不存在", "没有编号", "未登记", "悬空", "样例", "样本", "假链接", "误抓", "豁免")


def read(path):
    return io.open(path, encoding="utf-8").read()


def lines_of(text):
    return text.split("\n")


def active_docs(root):
    return sorted(glob.glob(os.path.join(root, "docs", "*.md")))


def history_docs(root):
    return sorted(glob.glob(os.path.join(root, "docs", "history", "*.md")))


def relpath(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def span_chars(lines, start, end):
    if end < start:
        return 0
    return len("\n".join(lines[start - 1:end]))


def build_sections(lines):
    """标题树。恒等式：span ＝ 标题行 ＋ body ＋ Σ 直接子节 span ⇒ body ＝ span − Σ子节 span。"""
    hs = []
    for i, l in enumerate(lines):
        m = HEAD.match(l)
        if m:
            hs.append({"line": i + 1, "level": len(m.group(1)), "title": m.group(2).strip()})
    n = len(hs)
    for k in range(n):
        end = len(lines)
        for j in range(k + 1, n):
            if hs[j]["level"] <= hs[k]["level"]:
                end = hs[j]["line"] - 1
                break
        hs[k]["end"] = end
        hs[k]["span"] = span_chars(lines, hs[k]["line"], end)
    stack = []
    children = [[] for _ in range(n)]
    for k in range(n):
        while stack and hs[stack[-1]]["level"] >= hs[k]["level"]:
            stack.pop()
        parent = stack[-1] if stack else None
        hs[k]["parent"] = parent
        if stack:
            children[stack[-1]].append(k)
        stack.append(k)
    for k in range(n):
        hs[k]["children"] = children[k]
        hs[k]["is_leaf"] = not children[k]
        hs[k]["body"] = hs[k]["span"] - sum(hs[c]["span"] for c in children[k])
    return hs


def speed_scope(lines, secs):
    scope = set()
    first_h2 = None
    for s in secs:
        if s["level"] == 2:
            first_h2 = s["line"]
            break
    upto = (first_h2 - 1) if first_h2 else len(lines)
    for i in range(1, upto + 1):
        scope.add(i)
    for s in secs:
        if s["level"] >= 2 and any(w in s["title"] for w in SPEED_TITLES):
            for i in range(s["line"], s["end"] + 1):
                scope.add(i)
    return scope


def size_rows(paths):
    rows = []
    for path in paths:
        text = read(path)
        lines = lines_of(text)
        secs = build_sections(lines)
        heading_lines = {s["line"] for s in secs}
        sec_hits = []
        for s in secs:
            if s["level"] < 2:
                continue
            if s["is_leaf"]:
                if s["span"] > MAX_SECTION_CHARS:
                    sec_hits.append(("叶节", s["line"], s["title"], s["span"], s["end"]))
            elif s["body"] > MAX_SECTION_CHARS:
                sec_hits.append(("自身体", s["line"], s["title"], s["body"], s["end"]))
        scope = speed_scope(lines, secs)
        speed_hits = [(i, len(lines[i - 1])) for i in sorted(scope)
                      if i not in heading_lines and len(lines[i - 1]) > MAX_SPEED_CHARS]
        title_hits = [(s["line"], len(lines[s["line"] - 1]), s["title"]) for s in secs
                      if len(lines[s["line"] - 1]) > MAX_TITLE_CHARS]
        big_nums = [n for n, x in enumerate(lines, 1) if len(x) > MAX_LINE_CHARS]
        rows.append({
            "path": path, "lines": len(lines), "chars": len(text),
            "max_line": max([len(x) for x in lines] or [0]),
            "big_lines": len(big_nums), "big_nums": big_nums,
            "sec_hits": sec_hits, "speed_hits": speed_hits, "title_hits": title_hits,
        })
    return rows


def table_scan(paths):
    result = {"tables": 0, "rows": 0, "mismatch": 0, "per_file": [], "mismatches": []}
    for path in paths:
        lines = lines_of(read(path))
        tables = rows = bad = 0
        cur = None
        for n, line in enumerate(lines, 1):
            s = line.lstrip("> ").rstrip()
            is_row = s.startswith("|") and s.endswith("|") and len(s) > 1
            if is_row:
                cols = len(CELL_SPLIT.split(s[1:-1]))
                if cur is None:
                    tables += 1
                    cur = {"cols": cols, "start": n}
                elif cols != cur["cols"]:
                    bad += 1
                    result["mismatches"].append((path, cur["start"], n, cols, cur["cols"]))
                rows += 1
            else:
                cur = None
        result["tables"] += tables
        result["rows"] += rows
        result["mismatch"] += bad
        result["per_file"].append((path, tables, rows, bad))
    return result


# --------------------------------------------------------------------------
# 报警：逐条、带病名与"灭它需要的字"两列语义
# --------------------------------------------------------------------------

def prefix60(s):
    return s[:60]


def _disease_for(kind, sub):
    if kind == "FILE":
        return "该搬", "「搬」字（把已闭环整节搬进 history）"
    if kind == "SECTION":
        if sub == "叶节":
            return "该搬", "「搬」字"
        return "该分册", "「分册」或「插标题」字（正文堆在子节之外）"
    if kind == "LINE":
        return "这一行内本体与沿革同行", "「搬」字（整段挪进同文件小节、行内留指针，见 rules :138）"
    if kind == "SPEED":
        return "该搬", "「搬」字（速览只写指向，明细进 history）"
    if kind == "TITLE":
        return "该改白", "「改」字（标题行>500，沿革搬进正文）"
    if kind == "TABLE":
        return "该修", "「改」字（列数错位）"
    return "?", "?"


def collect_alarms(root, rows, ts):
    alarms = []
    for r in rows:
        rel = relpath(root, r["path"])
        lines = lines_of(read(r["path"]))
        if r["chars"] > MAX_FILE_CHARS:
            d, need = _disease_for("FILE", None)
            alarms.append({"ruler": "FILE", "file": rel, "line": None, "anchor": rel,
                           "detail": "chars=%d > %d" % (r["chars"], MAX_FILE_CHARS),
                           "disease": d, "need": need})
        for kind, ln, title, chars, end in r["sec_hits"]:
            d, need = _disease_for("SECTION", kind)
            alarms.append({"ruler": "SECTION", "file": rel, "line": ln, "anchor": title,
                           "detail": "%s chars=%d > %d（L%d–L%d）" % (kind, chars, MAX_SECTION_CHARS, ln, end),
                           "disease": d, "need": need})
        for n in r["big_nums"]:
            d, need = _disease_for("LINE", None)
            alarms.append({"ruler": "LINE", "file": rel, "line": n, "anchor": prefix60(lines[n - 1]),
                           "detail": "len=%d > %d" % (len(lines[n - 1]), MAX_LINE_CHARS),
                           "disease": d, "need": need})
        for ln, chars in r["speed_hits"]:
            d, need = _disease_for("SPEED", None)
            alarms.append({"ruler": "SPEED", "file": rel, "line": ln, "anchor": prefix60(lines[ln - 1]),
                           "detail": "len=%d > %d" % (chars, MAX_SPEED_CHARS),
                           "disease": d, "need": need})
        for ln, chars, title in r["title_hits"]:
            d, need = _disease_for("TITLE", None)
            alarms.append({"ruler": "TITLE", "file": rel, "line": ln, "anchor": prefix60(lines[ln - 1]),
                           "detail": "len=%d > %d" % (chars, MAX_TITLE_CHARS),
                           "disease": d, "need": need})
    for path, hdr, ln, cols, exp in ts["mismatches"]:
        rel = relpath(root, path)
        lines = lines_of(read(path))
        anchor = "%s ∪ %s" % (prefix60(lines[hdr - 1]), prefix60(lines[ln - 1]))
        d, need = _disease_for("TABLE", None)
        alarms.append({"ruler": "TABLE", "file": rel, "line": ln, "anchor": anchor,
                       "detail": "表头 L%d／错位 L%d cols=%d != %d" % (hdr, ln, cols, exp),
                       "disease": d, "need": need})
    return alarms


def alarm_key(a):
    return (a["file"], a["ruler"], a["anchor"])


def print_alarms(alarms, limit_line=10):
    """逐条打印；LINE 档默认只列 top-N＋总数（--print/登记时全列）。"""
    by_ruler = {}
    for a in alarms:
        by_ruler.setdefault(a["ruler"], []).append(a)
    for ruler in ("FILE", "SECTION", "LINE", "SPEED", "TITLE", "TABLE"):
        group = by_ruler.get(ruler, [])
        if not group:
            continue
        print("-- %s：%d 条 --" % (ruler, len(group)))
        shown = group
        if ruler == "LINE" and limit_line is not None and len(group) > limit_line:
            shown = group[:limit_line]
        for a in shown:
            loc = a["file"] + ((":L%d" % a["line"]) if a["line"] else "")
            print("  [%s] %s | %s | 病名=%s | 灭它=%s"
                  % (a["ruler"], loc, a["detail"], a["disease"], a["need"]))
        if ruler == "LINE" and len(group) > len(shown):
            print("  …（另有 %d 条未列，--print 或登记时全列）" % (len(group) - len(shown)))


# --------------------------------------------------------------------------
# --baseline：键＝(文件, 尺名, 锚点)，行号不参与
# --------------------------------------------------------------------------

def load_baseline(root):
    p = os.path.join(root, BASELINE_PATH)
    if not os.path.exists(p):
        return None
    try:
        data = json.loads(read(p))
    except Exception:
        return None
    return set(tuple(x) for x in data.get("keys", []))


def save_baseline(root, alarms):
    p = os.path.join(root, BASELINE_PATH)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    keys = sorted(alarm_key(a) for a in alarms)
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"keys": [list(k) for k in keys]}, ensure_ascii=False, indent=1) + "\n")
    return p


def run_baseline(root, do_print=False, do_register=False):
    rows = size_rows(active_docs(root))
    ts = table_scan(active_docs(root))
    alarms = collect_alarms(root, rows, ts)
    current = {alarm_key(a): a for a in alarms}
    if do_register:
        p = save_baseline(root, alarms)
        print("已登记基线：%s（%d 条）" % (p, len(alarms)))
        return 0
    base = load_baseline(root)
    if base is None:
        print("基线未登记（本笔只实现能力＋样本，登记在收尾）——当前 %d 条报警全部视为 NEW" % len(alarms))
        print_alarms(alarms, limit_line=None if do_print else 10)
        return 0
    new = [k for k in current if k not in base]
    known = [k for k in current if k in base]
    vanished = [k for k in base if k not in current]
    print_alarms([current[k] for k in new] if not do_print else alarms,
                 limit_line=None if do_print else 10)
    print("== 基线对账：NEW=%d／KNOWN=%d/%d ==" % (len(new), len(known), len(base)))
    if new:
        for k in new:
            print("  NEW:", k)
    # 只读账：KNOWN 命中 n/N ＋ 本轮消失的锚点列表（不报警、不影响退出码）
    print("== 只读账：KNOWN 命中 %d／登记总数 %d；本轮消失锚点 %d 枚 ==" % (len(known), len(base), len(vanished)))
    for k in vanished:
        print("  消失:", k)
    return 1 if new else 0


# --------------------------------------------------------------------------
# 断链扫描
# --------------------------------------------------------------------------

def iter_labels(text):
    for m in APPEND_REF.finditer(text):
        nxt = text[m.end():m.end() + 1]
        if nxt and nxt in QUANT_AFTER:
            continue
        yield m.group(0)


def heading_labels(paths):
    labels = set()
    for path in paths:
        for line in lines_of(read(path)):
            m = HEAD.match(line)
            if not m:
                continue
            for lab in iter_labels(m.group(2)):
                labels.add(lab)
    return labels


def all_heading_texts(paths):
    out = set()
    for path in paths:
        for line in lines_of(read(path)):
            m = HEAD.match(line)
            if m:
                out.add(m.group(2).strip())
    return out


def has_pointer_on(path, label):
    for line in lines_of(read(path)):
        if label in line and any(h in line for h in POINTER_HINT):
            return True
    return False


def line_iter(text):
    inside = False
    for line in text.split("\n"):
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            yield line


def link_scan(root):
    active = active_docs(root)
    history = history_docs(root)
    led = os.path.join(root, "docs", "FIX-LEDGER.md")
    active_labels = heading_labels(active)
    all_labels = active_labels | heading_labels(history)
    all_titles = all_heading_texts(active) | all_heading_texts(history)
    items = set()
    for path in [led] + history:
        if not os.path.exists(path):
            continue
        for line in lines_of(read(path)):
            m = ITEM_HEAD.match(line)
            if m:
                items.add(m.group(1))
    broken = []
    counts = {"append": 0, "item": 0, "link": 0, "secname": 0, "meta_exempt": 0}
    for path in active:
        rel = relpath(root, path)
        for line in line_iter(read(path)):
            meta = any(k in line for k in META_MARKERS)
            for lab in iter_labels(line):
                if meta:
                    counts["meta_exempt"] += 1
                    continue
                counts["append"] += 1
                if lab not in all_labels:
                    broken.append("%s: 「%s」在任何标题里都不存在" % (rel, lab))
                elif (lab not in active_labels
                      and os.path.basename(path) == APPEND_OWNER
                      and not has_pointer_on(path, lab)):
                    broken.append("%s: 「%s」已搬进归档，但原地没有带标签的指针行" % (rel, lab))
            for m in ITEM_REF.finditer(line):
                if meta:
                    counts["meta_exempt"] += 1
                    continue
                counts["item"] += 1
                if m.group(1) not in items:
                    broken.append("%s: 「第 %s 项」在 FIX-LEDGER 与归档里都没有条目行" % (rel, m.group(1)))
            for m in MD_LINK.finditer(line):
                target = m.group(1).split("#")[0].strip()
                if not target or target.startswith(("http:", "https:", "mailto:")):
                    continue
                if meta:
                    counts["meta_exempt"] += 1
                    continue
                counts["link"] += 1
                if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(path), target))):
                    broken.append("%s: 链接目标不存在 %s" % (rel, target))
            # 新形：文末/见『节名』 + 见 <file>.md …『节名』（只看名字能不能落地，位置词不参与）
            for m in CUE_NAME.finditer(line):
                if meta:
                    counts["meta_exempt"] += 1
                    continue
                counts["secname"] += 1
                if not any(m.group(1) in t for t in all_titles):
                    broken.append("%s: 「%s」在任何标题里都不存在（新形：引号节名）" % (rel, m.group(1)))
            for m in CUE_FILE.finditer(line):
                if meta:
                    counts["meta_exempt"] += 1
                    continue
                counts["secname"] += 1
                if not os.path.exists(os.path.join(root, "docs", m.group(1))):
                    broken.append("%s: 引用的文件不存在 docs/%s（新形）" % (rel, m.group(1)))
    return broken, counts, len(all_labels)


# --------------------------------------------------------------------------
# 搬动守卫（--plan／--move 共用；写盘命令在 1b 接上）
# --------------------------------------------------------------------------

def block_headings(secs, start, end):
    return [s for s in secs if start <= s["line"] <= end]


def block_violations(secs, start, end):
    """统一越界判据：被搬块内每一枚标题的完整跨度必须落在块内。"""
    return [s for s in block_headings(secs, start, end) if s["end"] > end]


def item_span(lines, head_lines, n):
    """一枚编号项的跨度 (start, end)（1-based，含两端）；找不到返回 None。

    块尾 ＝「下一枚编号行／任一枚标题行／**已搬归档指针行**」之前。
    指针行那一条是 10-12 补的：编号项之间夹着 `> **【已搬归档】** 第 N 项 …`
    （FIX-LEDGER 里 #22 之后是 23/24/25 的指针），原判据既非编号行也非标题行
    ⇒ 搬 #22 会把别人的指针一起卷走。`--section`（按标题跨度）与 `--lines`（显式逃生口）不走这里。
    """
    m = re.compile(r"^%d\.\s" % n)
    found = None
    for idx, line in enumerate(lines, 1):
        if m.match(line):
            found = idx
            break
    if found is None:
        return None
    end = len(lines)
    for j in range(found + 1, len(lines) + 1):
        if NUM_ITEM.match(lines[j - 1]) or (j in head_lines) or POINTER_LINE.match(lines[j - 1]):
            end = j - 1
            break
    return (found, end)


def resolve_block(lines, secs, spec):
    """把 --section/--item/--lines 解析成一个 [start,end] 块；返回 (block, err)。"""
    starts, ends = [], []
    head_lines = {s["line"] for s in secs}
    if spec.get("section") is not None:
        t = spec["section"]
        match = [s for s in secs if s["title"] == t]
        if not match:
            return None, "找不到标题：%s" % t
        starts.append(match[0]["line"])
        ends.append(match[0]["end"])
    if spec.get("item") is not None:
        for tok in spec["item"].split(","):
            tok = tok.strip()
            if not tok:
                continue
            span = item_span(lines, head_lines, int(tok))
            if span is None:
                return None, "找不到第 %d 项" % int(tok)
            starts.append(span[0])
            ends.append(span[1])
    if spec.get("lines") is not None:
        for part in spec["lines"].split(","):
            part = part.strip()
            mm = RANGE.match(part)
            if not mm:
                return None, "区间格式应为 A..B：%s" % part
            starts.append(int(mm.group(1)))
            ends.append(int(mm.group(2)))
    if not starts:
        return None, "没有给出切块（--section／--item／--lines）"
    return (min(starts), max(ends)), None


def table_guard(lines, start, end):
    """表格守卫：①块内若含表格行，则该表表头＋分隔行必须同在块内；②落点邻接同侧。"""
    for i in range(start, end + 1):
        s = lines[i - 1].lstrip("> ").rstrip()
        if not (s.startswith("|") and s.endswith("|") and len(s) > 1):
            continue
        # 往上找表头＋分隔行
        j = i - 1
        while j >= 1 and lines[j - 1].lstrip("> ").rstrip().startswith("|"):
            j -= 1
        hdr = j + 1
        if hdr < start or not (hdr + 1 <= end):
            return "块内含表格行（L%d）但其表头/分隔行不在块内（表头 L%d）⇒ 拒绝" % (i, hdr)
    return None


def reorder_check(old_text, new_text):
    """换序无损：行字节多重集逐字相等 ＋ 总行数总字符数不变（先验）；再验缝（后验）。"""
    ol, nl = old_text.split("\n"), new_text.split("\n")
    if len(ol) != len(nl) or len(old_text) != len(new_text):
        return False, "无损失败：总行数/总字符数变了（%d/%d → %d/%d）" % (len(ol), len(old_text), len(nl), len(new_text))
    if sorted(ol) != sorted(nl):
        return False, "无损失败：行字节多重集不等"
    for i in range(1, len(nl)):
        # setext 缺陷形＝普通段落行紧贴下一行裸 `---`（`---` 把上一行渲染成 H2）。
        # 排除：上一行是标题／表格行／引用块（`> x` 后的 `---` 是 thematic break，非此缺陷）。
        prev = nl[i - 1].strip()
        if (nl[i].strip() == "---" and prev
                and not prev.startswith(("#", ">", "|")) and prev != "---"):
            return False, "缝失败：L%d 段落行紧贴 L%d `---`（setext 下划线形）" % (i, i + 1)
    return True, "OK"


def run_plan(root, spec):
    rel = spec.get("file")
    if not rel:
        print("--plan 需要 --file <相对仓库根的路径>")
        return 1
    path = os.path.join(root, rel)
    if not os.path.exists(path):
        print("文件不存在：%s" % rel)
        return 1
    lines = lines_of(read(path))
    secs = build_sections(lines)
    blocks, err = _resolve_blocks(lines, secs, spec)
    if err:
        print("PLAN 拒绝：%s" % err)
        return 1
    print("== PLAN %s ==" % rel)
    print("块数：%d" % len(blocks))
    for start, end in blocks:
        print("  块 L%d–L%d（%d 行，%d 字符）"
              % (start, end, end - start + 1, span_chars(lines, start, end)))
        inner = block_headings(secs, start, end)
        if inner:
            print("  块内标题（%d 枚）：" % len(inner))
            for s in inner:
                print("    %s L%d–L%d span=%d | %s"
                      % ("#" * s["level"], s["line"], s["end"], s["span"], s["title"][:44]))
        else:
            print("  块内标题：0 枚")
        viol = block_violations(secs, start, end)
        if viol:
            print("  越界：块内 %d 枚标题的完整跨度跨出块外 ⇒ 拒绝" % len(viol))
            for s in viol:
                print("    %s L%d–L%d（块尾 L%d） | %s"
                      % ("#" * s["level"], s["line"], s["end"], end, s["title"][:44]))
            return 1
        tg = table_guard(lines, start, end)
        if tg:
            print("  表格守卫：%s" % tg)
            return 1
    print("越界检查：通过（每块内每枚标题的跨度都落在块内）；表格守卫：通过")
    return 0


# --------------------------------------------------------------------------
# 搬动（--move）：四种切块共用一道越界拒绝；默认 dry-run，--go 才写盘
# --------------------------------------------------------------------------

def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_closed(root, appendix=False):
    """--list-closed：**报证据，不判终局**（10-12 改）。

    三列证据＋一行在册：① 首行是否含 ✅（原判据，保留成第一列）；② 整项跨度内 ✅ 计数；
    ③ 项尾 40 字——本仓编号项都是**追加式**（首行是原始登记，闭环节写在段尾），
    原判据（首行含 ✅）实测对本仓命中 0 枚，闭包只能靠人读末句 ⇒ 把末句摆出来。
    另扫 `> **【已搬归档】** 第 N 项` 行，列出**已搬在册**的编号与指针行号
    （已搬项的编号行本身已不在盘上，故不能按行打印，只能单独成行）。
    """
    led = os.path.join(root, "docs", "FIX-LEDGER.md")
    lines = lines_of(read(led))
    secs = build_sections(lines)
    head_lines = {s["line"] for s in secs}
    active = active_docs(root)
    ref_counts = {}
    for path in active:
        for line in line_iter(read(path)):
            for m in ITEM_REF.finditer(line):
                ref_counts[m.group(1)] = ref_counts.get(m.group(1), 0) + 1
    moved = {}
    for i, line in enumerate(lines, 1):
        m = re.match(r"^\s*>\s*\*\*【已搬归档】\*\*\s*第\s*([0-9]{1,3})\s*项", line)
        if m:
            moved.setdefault(m.group(1), i)
    print("== --list-closed docs/FIX-LEDGER.md（报证据，不判终局） ==")
    for i, line in enumerate(lines, 1):
        m = ITEM_HEAD.match(line)
        if not m:
            continue
        num = m.group(1)
        span = item_span(lines, head_lines, int(num))
        end = span[1] if span else i
        body = "\n".join(lines[i - 1:end])
        tail_src = ""
        for j in range(end, i - 1, -1):
            if lines[j - 1].strip():
                tail_src = lines[j - 1].strip()
                break
        print("  %-4s L%-4d 首行✅=%-5s 块内✅=%-3d refs=%-3d | 尾: …%s"
              % (num, i, "✅" in line, body.count("✅"), ref_counts.get(num, 0), tail_src[-40:]))
    if moved:
        print("  已搬在册（有指针行，%d 枚）：%s"
              % (len(moved), "、".join("%s@L%d" % (k, moved[k]) for k in sorted(moved, key=int))))
    else:
        print("  已搬在册（有指针行）：无")
    if appendix:
        appendix_candidates(root)
    return 0


def appendix_candidates(root):
    """--appendix-candidates：逐枚追加节查活引用＋累计列（取前 K 枚 ⇒ FILE 降到 X）。"""
    cr = os.path.join(root, "docs", "CODE-REVIEW.md")
    led = os.path.join(root, "docs", "FIX-LEDGER.md")
    history = history_docs(root)
    lines = lines_of(read(cr))
    secs = build_sections(lines)
    # 未闭环编号＝FIX-LEDGER 里出现的、未含 ✅ 的编号项集合（近似：该编号任一编号行含 ✅ 即视为已闭环）
    closed_nums, open_nums = set(), set()
    for line in lines_of(read(led)):
        m = ITEM_HEAD.match(line)
        if not m:
            continue
        (closed_nums if "✅" in line else open_nums).add(m.group(1))
    active_text = "\n".join(read(p) for p in active_docs(root))
    print("== --appendix-candidates（逐枚追加节：还有没有活引用、是哪几枚） ==")
    base = len(read(cr))
    total = 0
    rows = []
    for s in secs:
        if not s["title"].startswith("追加"):
            continue
        span = s["span"]
        refs = set(ITEM_REF.findall(lines[s["line"] - 1:s["end"]][0] if False else "\n".join(lines[s["line"] - 1:s["end"]])))
        live = sorted(n for n in refs if n in open_nums)
        total += span
        rows.append((s["title"][:40], span, live))
    cum = 0
    for title, span, live in rows:
        cum += span
        print("  %-44s span=%-7d 累计=%-8d 活引用=%s | FILE→%d"
              % (title, span, cum, live or "无", base - cum))
    print("  （33 枚全搬＝%d；按最小累计转绿需 K 枚，见 --plan 逐枚）" % total)
    return 0


def move(root, spec, do_go=False):
    """--move 四种切块：--section／--item／--lines／--reorder。

    history 语义（section/item/lines）：逐字节 append 到归档＋原地插指针行＋history/README 索引行＋打印 sha256。
    reorder 语义（同文件换序）：不写指针、不写索引；先验无损（行多重集＋总数）再验缝。
    """
    rel = spec.get("file")
    if not rel:
        print("--move 需要 --file <相对仓库根的路径>")
        return 1
    path = os.path.join(root, rel)
    if not os.path.exists(path):
        print("文件不存在：%s" % rel)
        return 1
    lines = lines_of(read(path))
    secs = build_sections(lines)
    if spec.get("reorder") is not None:
        return _move_reorder(root, path, lines, secs, spec, do_go)
    # 多切块单批：把每枚子块解析出来
    blocks, err = _resolve_blocks(lines, secs, spec)
    if err:
        print("MOVE 拒绝：%s" % err)
        return 1
    # 统一越界拒绝 + 表格守卫（逐块）
    for start, end in blocks:
        viol = block_violations(secs, start, end)
        if viol:
            print("MOVE 拒绝：块 L%d–L%d 内标题跨度跨出块外" % (start, end))
            for s in viol:
                print("  %s L%d–L%d（块尾 L%d） | %s"
                      % ("#" * s["level"], s["line"], s["end"], end, s["title"][:44]))
            return 1
        tg = table_guard(lines, start, end)
        if tg:
            print("MOVE 拒绝：块 L%d–L%d 表格守卫：%s" % (start, end, tg))
            return 1
    # 抽出待搬内容（按行区间，从后往前以便原地删除）
    moved_lines = []
    proofs = []
    for start, end in blocks:
        chunk = lines[start - 1:end]
        moved_lines.extend(chunk)
        proofs.append((start, end, len(chunk), span_chars(lines, start, end), sha256("\n".join(chunk))))
    print("== MOVE %s（%s） ==" % (rel, "写盘" if do_go else "dry-run"))
    for start, end, nl, nc, h in proofs:
        print("  块 L%d–L%d：%d 行／%d 字符／sha256=%s" % (start, end, nl, nc, h[:16]))
    moved_text = "\n".join(moved_lines)
    print("  合计：%d 块／%d 行／%d 字符／sha256=%s"
          % (len(blocks), len(moved_lines), len(moved_text), sha256(moved_text)[:16]))
    if not do_go:
        print("（dry-run：加 --go 才写盘。归档件、指针行、索引行都在写入时才动）")
        return 0
    # 写归档
    date = spec.get("date") or "2026-10-11"
    slug = spec.get("slug") or "docs-move"
    archive_rel = os.path.join("docs", "history", "%s-%s.md" % (date, slug))
    archive_path = os.path.join(root, archive_rel)
    header = ("# %s 归档（%s）\n\n"
              "> **这是什么**：[../%s](../%s) 的以下块整体搬迁（%s 触发，机械，必进）。\n"
              "> **内容逐字保留、未做任何改写**；本文件只作历史对照，不在此维护状态。\n\n---\n\n"
              % (os.path.basename(rel), date, os.path.basename(rel), os.path.basename(rel),
                 spec.get("reason") or "体量治理"))
    if os.path.exists(archive_path):
        old = read(archive_path)
        new_archive = old + "\n" + moved_text + "\n"
    else:
        new_archive = header + moved_text + "\n"
    io.open(archive_path, "w", encoding="utf-8", newline="\n").write(new_archive)
    print("已写入归档：%s（%d 字符）" % (archive_rel, len(new_archive)))
    # 原地插指针行（在删除前基于原行列表生成 label，避免行号错位吃掉后续块的指针）＋从后往前删块
    pointer_lines = []
    for start, end in blocks:
        title = None
        for s in secs:
            if s["line"] == start:
                title = s["title"]
                break
        m_first = ITEM_HEAD.match(lines[start - 1])
        if title:
            label = title
        elif m_first:
            label = "第 %s 项" % m_first.group(1)
        else:
            label = lines[start - 1][:30]
        pointer_lines.append((start, end, "> **【已搬归档】** %s —— 正文见 [%s](%s)（体量治理：整块搬迁，原地只留指针）。"
                              % (label, os.path.basename(archive_rel), "history/" + os.path.basename(archive_rel))))
    for start, end, ptr in sorted(pointer_lines, key=lambda x: -x[0]):
        lines = lines[:start - 1] + [ptr] + lines[end:]
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    print("已插指针行 %d 枚：%s" % (len(pointer_lines), rel))
    # history/README 索引行：插到「时间线索引」那张表的最后一行之后（不是 blockquote 之后）
    # 幂等：同名归档件已有索引行就不再追加（多批次共用同一归档时必踩，否则每次重复一行）
    idx = os.path.join(root, "docs", "history", "README.md")
    idx_lines = lines_of(read(idx))
    if any(os.path.basename(archive_rel) in l for l in idx_lines):
        print("history/README.md 已有该归档的索引行，跳过")
        return 0
    ins = None
    for i, l in enumerate(idx_lines):
        s = l.strip()
        if s.startswith("|") and (s.endswith("|") or "](…" in s or "](." in s):
            ins = i + 1   # 记最后一枚表格行的下一行下标
    row = "| [%s](%s) | %s 的块搬迁（%s） | 整体搬迁，内容逐字保留 | 见 [../%s](../%s) |" % (
        os.path.basename(archive_rel), os.path.basename(archive_rel), os.path.basename(rel), date,
        os.path.basename(rel), os.path.basename(rel))
    if ins is not None:
        idx_lines.insert(ins, row)
    else:
        idx_lines.append(row)
    io.open(idx, "w", encoding="utf-8", newline="\n").write("\n".join(idx_lines))
    print("已加 history/README.md 索引行")
    return 0


def _resolve_blocks(lines, secs, spec):
    """把 spec 解析成一组 [start,end] 子块（--item 多枚 ＝ 多子块）。"""
    blocks = []
    if spec.get("section") is not None:
        t = spec["section"]
        match = [s for s in secs if s["title"] == t]
        if not match:
            return None, "找不到标题：%s" % t
        blocks.append((match[0]["line"], match[0]["end"]))
    if spec.get("item") is not None:
        head_lines = {s["line"] for s in secs}
        for tok in spec["item"].split(","):
            tok = tok.strip()
            if not tok:
                continue
            span = item_span(lines, head_lines, int(tok))
            if span is None:
                return None, "找不到第 %d 项" % int(tok)
            blocks.append(span)
    if spec.get("lines") is not None:
        for part in spec["lines"].split(","):
            part = part.strip()
            mm = RANGE.match(part)
            if not mm:
                return None, "区间格式应为 A..B：%s" % part
            blocks.append((int(mm.group(1)), int(mm.group(2))))
    if not blocks:
        return None, "没有给出切块（--section／--item／--lines）"
    return sorted(blocks), None


def _move_reorder(root, path, lines, secs, spec, do_go):
    """--reorder：把 --lines 命名的块移到 --before（1-indexed 行号）之前。先验无损，再验缝。"""
    part = spec["reorder"]
    mm = RANGE.match(part.strip())
    before_tok = spec.get("before")
    if not mm or not before_tok:
        print("MOVE 拒绝：--reorder 需要 `--reorder A..B --before N`")
        return 1
    start, end = int(mm.group(1)), int(mm.group(2))
    before = int(before_tok)
    if not (1 <= start <= end <= len(lines)) or not (1 <= before <= len(lines) + 1):
        print("MOVE 拒绝：行号越界")
        return 1
    if start < before <= end + 1:
        print("MOVE 拒绝：--before %d 落在块 L%d–L%d 内部或紧邻（无位移）" % (before, start, end))
        return 1
    viol = block_violations(secs, start, end)
    if viol:
        print("MOVE 拒绝：换序块内标题跨度跨出块外")
        for s in viol:
            print("  %s L%d–L%d | %s" % ("#" * s["level"], s["line"], s["end"], s["title"][:44]))
        return 1
    chunk = lines[start - 1:end]
    rest = lines[:start - 1] + lines[end:]
    # --before N ＝ 把块紧邻置于原第 N 行之前（删掉块后，原第 N 行在 rest 里的下标）
    if before <= start:
        insert_at = before - 1
    else:
        insert_at = before - 1 - len(chunk)
    insert_at = max(0, min(insert_at, len(rest)))
    new_lines = rest[:insert_at] + chunk + rest[insert_at:]
    new_text = "\n".join(new_lines)
    ok, why = reorder_check(read(path), new_text)
    print("== MOVE --reorder %s（%s） ==" % (spec["file"], "写盘" if do_go else "dry-run"))
    print("  块 L%d–L%d（%d 行）→ 紧邻置于 L%d 之前（落点 rest[%d]）" % (start, end, len(chunk), before, insert_at))
    print("  无损＋缝检查：%s（%s）" % ("通过" if ok else "拒绝", why))
    if not ok:
        return 1
    if not do_go:
        print("（dry-run：加 --go 才写盘）")
        return 0
    io.open(path, "w", encoding="utf-8", newline="\n").write(new_text)
    print("已写盘：%s" % spec["file"])
    return 0


# --------------------------------------------------------------------------
# 报告 / 自检
# --------------------------------------------------------------------------

def report(root="."):
    paths = active_docs(root)
    rows = size_rows(paths)
    print("== 体量读数（对着哪一棵树：本轮工作区；行数只作参考，不作闸） ==")
    for r in rows:
        print("%-26s lines=%-5d chars=%-8d big_line=%-3d max_line=%-6d"
              % (relpath(root, r["path"]), r["lines"], r["chars"], r["big_lines"], r["max_line"]))
    ts = table_scan(paths)
    alarms = collect_alarms(root, rows, ts)
    print("== 超标报警（逐条；LINE 默认 top-10） ==")
    if alarms:
        print_alarms(alarms, limit_line=10)
    else:
        print("（无）")
    print("== 报警总数：%d ==" % len(alarms))
    print("== 表格扫描：表=%d 数据行=%d 错位=%d ==" % (ts["tables"], ts["rows"], ts["mismatch"]))
    for path, hdr, ln, cols, exp in ts["mismatches"]:
        print("  MISMATCH %s 表头 L%d／错位 L%d cols=%d != %d"
              % (relpath(root, path), hdr, ln, cols, exp))
    broken, counts, labels = link_scan(root)
    print("== 断链扫描：真引用 追加=%d／第N项=%d／链接=%d／节名=%d，元文本豁免=%d，已知标签数=%d =="
          % (counts["append"], counts["item"], counts["link"], counts["secname"],
             counts["meta_exempt"], labels))
    print("\n".join(broken) if broken else "断链＝0")
    return len(alarms), len(broken)


def _write(path, text):
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


def _speed_hits_for(lines):
    secs = build_sections(lines)
    heading_lines = {s["line"] for s in secs}
    scope = speed_scope(lines, secs)
    return [(i, len(lines[i - 1])) for i in sorted(scope)
            if i not in heading_lines and len(lines[i - 1]) > MAX_SPEED_CHARS]


def _test_speed_in():
    return len(_speed_hits_for(["# t", "## 状态卡", "x" * 600])) == 1


def _test_speed_out():
    return len(_speed_hits_for(["# t", "## 正常节", "y" * 600])) == 0


def _test_baseline_new():
    root = tempfile.mkdtemp(prefix="docs-scan-bt-")
    buf = io.StringIO()
    old = sys.stdout
    try:
        os.makedirs(os.path.join(root, "docs"))
        os.makedirs(os.path.join(root, "scripts"))
        _write(os.path.join(root, "docs", "X.md"), "# t\n" + "z" * 2000 + "\n")
        _write(os.path.join(root, "scripts", "docs-scan-baseline.json"), '{"keys": []}\n')
        sys.stdout = buf
        rc = run_baseline(root)
        sys.stdout = old
        out = buf.getvalue()
        # 2000 字那一行同时命中 LINE＋SPEED 两档 ⇒ 各列一条、NEW=2、退出码 1
        return rc == 1 and "NEW=2" in out
    finally:
        sys.stdout = old
        shutil.rmtree(root, ignore_errors=True)


def _test_table_rows(lines):
    root = tempfile.mkdtemp(prefix="docs-scan-tbt-")
    try:
        p = os.path.join(root, "t.md")
        _write(p, "\n".join(lines) + "\n")
        return table_scan([p])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _test_table_escaped_green():
    # 表格里写 grep 模式靠 `\|`；它算正文，不能被读成多一列（＝本轮 7 处错位的成因）
    ts = _test_table_rows(["| 编号 | 证据 |", "|---|---|",
                           '| A | `grep -rn "x\\|y" web/` 命中 0 |'])
    return ts["mismatch"] == 0 and ts["tables"] == 1 and ts["rows"] == 3


def _test_table_extra_col_red():
    # 换成转义口径后，尺还得证明它拦得住真错位：多一列必须红
    ts = _test_table_rows(["| a | b |", "|---|---|", "| 1 | 2 |", "| 3 | 4 | 5 |"])
    return ts["mismatch"] == 1 and ts["rows"] == 4


def selftest():
    root = tempfile.mkdtemp(prefix="docs-scan-selftest-")
    try:
        os.makedirs(os.path.join(root, "docs", "history"))
        _write(os.path.join(root, "docs", "CODE-REVIEW.md"),
               "# review\n\n#### 追加一 · 活着的一节\n正文\n\n"
               "追加十二 已整节搬至 docs/history/2026-01-01-x.md（归档，这一行就是留着的指针）\n\n"
               "追加十三 的教训还在别处被引用，可这一行什么都没留\n\n"
               "追加九百九十九 是盘上查无此节的一个编号\n\n"
               "按纪律在门槛节追加一行带出处、原句不动（动词用法，不是节次）\n\n"
               "元文本豁免样例：这一行说『追加九百九十九』这个标签在盘上不存在，是在谈它，不是引用它\n\n"
               "样例：第 999 项 这种写法在盘上不存在，这一行是在谈它（豁免），不是引用它\n\n"
               "见「活着的一节」好；文末『查无此节』坏（引号节名新形）\n\n"
               "```\n│  [x](gone-inside-fence.md) │\n```\n")
        _write(os.path.join(root, "docs", "FIX-LEDGER.md"),
               "# ledger\n\n1. 活条目\n\n见第 1 项好；见第 999 项坏；[链接](history/gone.md)坏；"
               "[本地](CODE-REVIEW.md)好\n")
        _write(os.path.join(root, "docs", "history", "2026-01-01-x.md"),
               "# archived\n\n#### 追加十二 · 归档里的正文\n\n#### 追加十三 · 归档里的另一节\n")
        broken, counts, labels = link_scan(root)
        joined = "\n".join(broken)
        lc_append, lc_partial, lc_moved = _test_list_closed_evidence()
        checks = {
            "悬空第N项被抓": "第 999 项" in joined,
            "悬空追加分身被抓": "追加九百九十九" in joined,
            "搬走却没留指针被抓": "追加十三" in joined,
            "悬空链接被抓": "history/gone.md" in joined,
            "活标签不误报": "「追加一」" not in joined,
            "搬走且带指针不误报": "「追加十二」" not in joined,
            "动词用法不误报": "追加一行" not in joined,
            "代码块内链接不误报": "gone-inside-fence.md" not in joined,
            "元文本豁免计入而非静默放过": counts["meta_exempt"] >= 2,
            "归档标题计入集合": labels == 3,
            # 新形（1a-iii）
            "新形·引号节名落地不误报": "活着的一节」在任何标题" not in joined,
            "新形·引号节名悬空被抓": "查无此节" in joined and counts["secname"] >= 2,
            # 搬动守卫（#61 形状永久回归）
            "越界·按节口径搬行区间必须红": _test_guard_oob(),
            "表格守卫·块内表格行缺表头必须红": _test_guard_table(),
            # 换序两枚
            "换序·纯换序绿": _test_reorder_ok(),
            "换序·改一个字符必须红": _test_reorder_byte(),
            # 速览一对（㉒）
            "速览·白名单块内 600 字行该红": _test_speed_in(),
            "速览·同一行落在块外不该红": _test_speed_out(),
            # 新增红必须报出（㉒）
            "基线·NEW 必报且退出码为 1": _test_baseline_new(),
            # 表格尺·转义口径（10-11 那 7 处错位的归因）
            "表格·转义竖线不算列（绿）": _test_table_escaped_green(),
            "表格·真多一列必须红": _test_table_extra_col_red(),
            # --move 多切块单批与换序（1b）
            "move·多切块单批一遍抽全": _test_move_multiblock(),
            "move·换序先验无损在缝检查之前": _test_reorder_order(),
            "move·换序缝缺陷被抓": _test_reorder_seam(),
            # 项尾守卫 + --list-closed 证据面（10-12 补）
            "move·项后指针行不被卷走": _test_item_stops_at_pointer(),
            "list-closed·追加式项的闭环节可见": lc_append,
            "list-closed·部分闭环末句可见": lc_partial,
            "list-closed·已搬指针行在册": lc_moved,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
    verdict = "PASS" if all(checks.values()) else "FAIL"
    print("SELFTEST %s（%d 判据） %s broken=%d refs=%s"
          % (verdict, len(checks), "" if not checks else "", len(broken), counts))
    for k, v in checks.items():
        if not v:
            print("  FAIL:", k)
    for line in broken:
        print("  样本断链:", line)
    return 0 if verdict == "PASS" else 1


def _mk(lines):
    text = "\n".join(lines)
    return text, lines_of(text), build_sections(lines_of(text))


def _test_guard_oob():
    # `## A` 下紧贴 `#### B`（#61 形状）；按行区间只搬 `#### B` 的行 ⇒ B 的跨度跨出 ⇒ 必须红
    text, lines, secs = _mk(["## A", "#### B", "b1", "b2", "## C", "c1"])
    spec = {"lines": "2..2"}
    block, err = resolve_block(lines, secs, spec)
    if err:
        return False
    start, end = block
    return len(block_violations(secs, start, end)) == 1


def _test_guard_table():
    lines = ["## A", "| h | v |", "| --- | --- |", "| 1 | 2 |", "| 3 | 4 |", "tail"]
    text, lines2, secs = _mk(lines)
    # 只搬数据行 L4..L5，表头/分隔行(L2/L3)不在块内 ⇒ 必须红
    return table_guard(lines2, 4, 5) is not None


def _test_reorder_ok():
    old = "A\nnewsec\n\n---\n"
    new = "newsec\nA\n\n---\n"   # 纯换序，多重集相等，缝干净（`---` 前是空行）
    ok, _ = reorder_check(old, new)
    return ok


def _test_reorder_byte():
    old = "a\nb\nc\n"
    new = "a\nB\nc\n"   # 改一个字符 ⇒ 多重集不等 ⇒ 必须红
    ok, _ = reorder_check(old, new)
    return not ok


def _test_reorder_seam():
    # 构造多重集相等、但换序后 paragraph 紧贴裸 `---`（setext 缺陷形）⇒ 只能靠缝判据抓到
    old2 = "para1\npara2\n\n---\n"     # ["para1","para2","","---",""]：缝干净
    new2 = "para1\n\npara2\n---\n"     # ["para1","","para2","---",""]：para2 紧贴 --- ⇒ 缝失败
    ok, why = reorder_check(old2, new2)
    return (not ok) and ("缝失败" in why)


def _test_move_multiblock():
    root = tempfile.mkdtemp(prefix="docs-scan-mb-")
    buf = io.StringIO()
    old_stdout = sys.stdout
    try:
        os.makedirs(os.path.join(root, "docs", "history"))
        _write(os.path.join(root, "docs", "history", "README.md"), "# idx\n\n## 时间线索引\n\n")
        _write(os.path.join(root, "docs", "Z.md"),
               "# z\n\n1. a1\na2\n\n2. b1\nb2\n\n3. c1\nc2\n")
        sys.stdout = buf
        rc = move(root, {"file": "docs/Z.md", "item": "1,2",
                         "date": "2026-01-01", "slug": "z-move", "reason": "test"}, do_go=True)
        sys.stdout = old_stdout
        left = read(os.path.join(root, "docs", "Z.md"))
        arch = read(os.path.join(root, "docs", "history", "2026-01-01-z-move.md"))
        return (rc == 0 and "3. c1" in left and "1. a1" not in left
                and "a1" in arch and "b1" in arch
                # 每块各一枚指针（label 在删除前生成）——bug 形：只插了第一块的指针
                and "第 1 项" in left and "第 2 项" in left)
    finally:
        sys.stdout = old_stdout
        shutil.rmtree(root, ignore_errors=True)


def _test_item_stops_at_pointer():
    """`--item` 遇「已搬归档」指针行即止：搬 #22 不许把 23/24/25 的指针一起卷走。

    10-12 补的判据——编号项之间夹着**别人**的指针行，原项尾判定既非编号行也非标题行。
    """
    root = tempfile.mkdtemp(prefix="docs-scan-ptr-")
    buf = io.StringIO()
    old_stdout = sys.stdout
    try:
        os.makedirs(os.path.join(root, "docs", "history"))
        _write(os.path.join(root, "docs", "history", "README.md"), "# idx\n\n## 时间线索引\n\n")
        _write(os.path.join(root, "docs", "Z.md"),
               "# z\n\n22. a1\na2\n\n"
               "> **【已搬归档】** 第 23 项 —— 正文见 [x.md](history/x.md)（体量治理：整块搬迁，原地只留指针）。\n"
               "> **【已搬归档】** 第 24 项 —— 正文见 [x.md](history/x.md)（体量治理：整块搬迁，原地只留指针）。\n\n"
               "26. b1\nb2\n")
        sys.stdout = buf
        rc = move(root, {"file": "docs/Z.md", "item": "22",
                         "date": "2026-01-01", "slug": "z-ptr", "reason": "test"}, do_go=True)
        sys.stdout = old_stdout
        left = read(os.path.join(root, "docs", "Z.md"))
        arch = read(os.path.join(root, "docs", "history", "2026-01-01-z-ptr.md"))
        return (rc == 0
                and "a1" in arch and "b1" not in arch
                # 指针行原地存活、没被卷进归档
                and "第 23 项" in left and "第 24 项" in left
                and "第 23 项" not in arch)
    finally:
        sys.stdout = old_stdout
        shutil.rmtree(root, ignore_errors=True)


def _test_list_closed_evidence():
    """`--list-closed` 的三列证据＋在册行：追加式项的闭环节、部分闭环的末句、已搬指针都要看得见。

    返回 (追加式可见, 末句可见, 已搬在册)——三条各自成判据，不许一锅绿。
    """
    root = tempfile.mkdtemp(prefix="docs-scan-lc-")
    buf = io.StringIO()
    old_stdout = sys.stdout
    try:
        os.makedirs(os.path.join(root, "docs", "history"))
        _write(os.path.join(root, "docs", "FIX-LEDGER.md"),
               "# ledger\n\n"
               "7. **首行没有勾**：这件事的结论写在段尾。\n"
               "   收尾句：已落地，闭合。✅\n\n"
               "8. **部分闭环**：还剩一条没做。\n"
               "   🟡 剩 2 条待办。\n\n"
               "> **【已搬归档】** 第 9 项 —— 正文见 [x.md](history/x.md)（体量治理：整块搬迁，原地只留指针）。\n")
        _write(os.path.join(root, "docs", "CODE-REVIEW.md"), "# review\n")
        sys.stdout = buf
        list_closed(root)
        sys.stdout = old_stdout
        out = buf.getvalue()
        append_visible = re.search(r"7\s+L\d+\s+首行✅=False\s+块内✅=1\b", out) is not None
        partial_visible = "剩 2 条待办" in out
        moved_visible = re.search(r"已搬在册（有指针行，1 枚）：9@L\d+", out) is not None
        return (append_visible, partial_visible, moved_visible)
    finally:
        sys.stdout = old_stdout
        shutil.rmtree(root, ignore_errors=True)


def _test_reorder_order():
    # 漏带一行 ⇒ 总行数变（先验失败）；此时缝也不干净，判据顺序要求先报"无损失败"
    old = "a\n\nb\n"
    new = "b\na\n"   # 少一行（带走了空行），总行数变
    ok, why = reorder_check(old, new)
    return (not ok) and ("无损失败" in why)


def parse_spec(argv):
    spec = {"file": None, "section": None, "item": None, "lines": None, "reorder": None,
            "before": None, "date": None, "slug": None, "reason": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--file", "--section", "--item", "--lines", "--reorder", "--before",
                 "--date", "--slug", "--reason") and i + 1 < len(argv):
            spec[a[2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    return spec


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    if "--plan" in argv:
        return run_plan(".", parse_spec(argv))
    if "--list-closed" in argv:
        return list_closed(".", appendix="--appendix-candidates" in argv)
    if "--move" in argv:
        return move(".", parse_spec(argv), do_go="--go" in argv)
    if "--baseline" in argv:
        return run_baseline(".", do_print="--print" in argv, do_register="--register" in argv)
    _, broken = report(".")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
