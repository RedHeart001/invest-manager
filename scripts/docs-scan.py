#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""docs 收尾体检——`.claude/rules/project.md`「docs 体量治理（2026-10-09 立）」的执行件。

除 `--move`／`--baseline --register` 外都不写盘、零出网。

  1. 体量读数：单文件 >120,000 字符／单行 >1,500 字符／单节 >30,000 字符 ⇒ 报警，不动笔。**行数不作闸**。
     单节按两把读数取并集：**叶节跨度 ∪ 容器自身体**（恒等式＝自身体＋Σ直接子节＝跨度，不重复计数）。
  2. 断链扫描：活跃工作区里每个「追加N」「第 N 项」「相对链接」「文末/见『节名』」都要能落地。
  3. 表格扫描（由 `data-service/runtime/` 三枚临时件并回本件，任何机器上都能跑）。
  4. 速览尺 + TITLE 档：速览类区块非标题行 >500 ⇒ 报警；任意级标题行 >500 ⇒ 报警。

用法：
    python scripts/docs-scan.py                          # 读数＋报警（逐条）＋表格＋断链
    python scripts/docs-scan.py --selftest               # 判据自带会红的样本，全绿才算过
    python scripts/docs-scan.py --baseline               # 与已登记基线比：NEW 决定退出码＋KNOWN 只读账
    python scripts/docs-scan.py --baseline --print       # 全列（LINE 不再是 top-10）
    python scripts/docs-scan.py --baseline --register    # 把当轮清单登记为基线（写盘）
    python scripts/docs-scan.py --plan --file docs/CODE-REVIEW.md --section "追加十二"   # 打印将搬跨度，不写盘

口径（都按 `len(text)` 含换行，逐行和与它差「行数−1」，混用会让每轮对账多一个谜）：
    行区间的字符数 ＝ len("\\n".join(该区间各行))。

范围：超标判定只看 `docs/*.md`（活跃工作区）；`docs/history/` 只进入断链扫描的目标集合。
"""

import glob
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
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"^\s*```")
RANGE = re.compile(r"^(\d+)\.\.(\d+)$")
# 新形（1a-iii 补）：文末/末/见/参见 之后的引号节名，或「见 <file>.md …『节名』」
CUE_NAME = re.compile(r"(?:文末|参见|详见|见)\s*[『「《]([^』」》]{2,})[』」》]")
CUE_FILE = re.compile(r"(?:文末|参见|详见|见)\s*([A-Za-z0-9_.\-/]+\.md)")
SEP_ROW = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")

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
                cols = s.count("|") - 1
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
            n = int(tok)
            m = re.compile(r"^%d\.\s" % n)
            found = None
            for idx, line in enumerate(lines, 1):
                if m.match(line):
                    found = idx
                    break
            if found is None:
                return None, "找不到第 %d 项" % n
            end = len(lines)
            for j in range(found + 1, len(lines) + 1):
                if NUM_ITEM.match(lines[j - 1]) or (j in head_lines):
                    end = j - 1
                    break
            starts.append(found)
            ends.append(end)
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
        if nl[i - 1].strip() == "---" and nl[i].strip() and not nl[i].startswith("#"):
            return False, "缝失败：L%d `---` 紧贴段落行（setext 下划线形）" % i
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
    block, err = resolve_block(lines, secs, spec)
    if err:
        print("PLAN 拒绝：%s" % err)
        return 1
    start, end = block
    print("== PLAN %s ==" % rel)
    print("块跨度：L%d–L%d（%d 行，%d 字符）"
          % (start, end, end - start + 1, span_chars(lines, start, end)))
    inner = block_headings(secs, start, end)
    if inner:
        print("块内标题（%d 枚）：" % len(inner))
        for s in inner:
            print("  %s L%d–L%d span=%d | %s"
                  % ("#" * s["level"], s["line"], s["end"], s["span"], s["title"][:44]))
    else:
        print("块内标题：0 枚")
    viol = block_violations(secs, start, end)
    if viol:
        print("越界：块内 %d 枚标题的完整跨度跨出块外 ⇒ 拒绝" % len(viol))
        for s in viol:
            print("  %s L%d–L%d（块尾 L%d） | %s"
                  % ("#" * s["level"], s["line"], s["end"], end, s["title"][:44]))
        return 1
    tg = table_guard(lines, start, end)
    if tg:
        print("表格守卫：%s" % tg)
        return 1
    print("越界检查：通过（块内每枚标题的跨度都落在块内）；表格守卫：通过")
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
    old = "para\n---\n\nnewsec\n"
    new = "newsec\npara\n---\n\n"   # 纯换序（带空行，缝干净）
    ok, _ = reorder_check(old, new)
    return ok


def _test_reorder_byte():
    old = "a\nb\nc\n"
    new = "a\nB\nc\n"   # 改一个字符 ⇒ 多重集不等 ⇒ 必须红
    ok, _ = reorder_check(old, new)
    return not ok


def parse_spec(argv):
    spec = {"file": None, "section": None, "item": None, "lines": None, "reorder": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--file", "--section", "--item", "--lines", "--reorder") and i + 1 < len(argv):
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
    if "--baseline" in argv:
        return run_baseline(".", do_print="--print" in argv, do_register="--register" in argv)
    _, broken = report(".")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
