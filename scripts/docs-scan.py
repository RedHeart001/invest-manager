#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""docs 收尾体检——`.claude/rules/project.md`「docs 体量治理（2026-10-09 立）」的执行件。

两半（除 `--move` 外都不写盘、零出网）：
  1. 体量读数：单文件 >120,000 字符／单行 >1,500 字符／单节 >30,000 字符 ⇒ 报警，不动笔。**行数不作闸**。
     单节按两把读数取并集：**叶节跨度 ∪ 任意节自身体**（恒等式＝自身体＋Σ直接子节＝跨度，不重复计数）。
     「自身体」＝只按终端叶节会把挂在容器自身上下、Σ在子节之外的那一块设成不可见（10-10 实测：门槛
     堆积 124,333 挂在 `## CR9 · 修复计划` 自身上＝L390→首个子节 L435，不是任何叶节）。
  2. 断链扫描：活跃工作区里每个「追加N」「第 N 项」「相对链接」都要能落地——标签要么还在某个标题里，
     要么已进 `docs/history/` 且**原地留着带同一标签的指针行**；条目号要么在 FIX-LEDGER，要么在归档里；
     相对链接的目标文件必须存在。
  3. 表格扫描（由 `data-service/runtime/` 三枚临时件并回本件，任何机器上都能跑）：表数／数据行数／列数不一致处数。
  4. 速览尺 + TITLE 档：速览类区块（作用域见下）非标题行 >500 字符 ⇒ 报警；**任意级标题行 >500 字符** ⇒ 报警。

用法：
    python scripts/docs-scan.py             # 体量读数＋超标报警＋表格扫描＋断链结果
    python scripts/docs-scan.py --selftest  # 判据自带会红的样本，全绿才算过
    python scripts/docs-scan.py --plan --file docs/CODE-REVIEW.md --section "追加十二"   # 只打印将搬跨度，不写盘

口径（都按 `len(text)` 含换行，逐行和与它差「行数−1」，混用会让每轮对账多一个谜）：
    行区间的字符数 ＝ len("\\n".join(该区间各行))。

范围：超标判定只看 `docs/*.md`（活跃工作区）；`docs/history/` 只进入断链扫描的目标集合，
      否则这条规则会去咬归档区自己（归档区继续长是正常态）。
"""

import glob
import io
import os
import re
import shutil
import sys
import tempfile

MAX_FILE_CHARS = 120000
MAX_LINE_CHARS = 1500
MAX_SECTION_CHARS = 30000
MAX_SPEED_CHARS = 500   # 速览尺：速览类区块的每一行
MAX_TITLE_CHARS = 500   # TITLE 档：任意级标题行——四把尺里最后补的盲区（10-16 实测唯一命中＝FIX-LEDGER:45）

# 速览尺作用域：首个 H2 之前 ∪ 标题命中下列词的区块。不据此做任何改名动作（改名是零收益的散文编辑）。
SPEED_TITLES = ("状态卡", "当前状态", "速览", "状态总览")

HEAD = re.compile(r"^\s*>*\s*(#{1,6})\s+(.*)$")
NUM_ITEM = re.compile(r"^[0-9]{1,3}\.\s")
APPEND_LABEL = re.compile(r"^(追加[〇零一二三四五六七八九十百]+)")
APPEND_REF = re.compile(r"追加[〇零一二三四五六七八九十百]+")
ITEM_REF = re.compile(r"第\s*([0-9]{1,3})\s*项")
ITEM_HEAD = re.compile(r"^([0-9]{1,3})\.\s")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"^\s*```")
RANGE = re.compile(r"^(\d+)\.\.(\d+)$")
# 「追加」后面跟量词或区间号时是散文用法（追加一行／追加两段／追加一–九），不是节次引用——两类都不能算断链
QUANT_AFTER = set("个条枚行项次句要上入两段–—~-～至到")
POINTER_HINT = ("搬", "归档", "指针", "history")
APPEND_OWNER = "CODE-REVIEW.md"  # 「追加N」这一族节次的归属文件（只有它欠留指针行）
# 元文本豁免：一句话里在**谈**某个标签不存在／是样例，就不是对它的引用。判据＝同一行含下列词之一。
# 已知残留（诚实边界）：真断链若恰好写在带这些词的句子里，会被这一档豁免放过——所以豁免行会单独计数打出来。
META_MARKERS = ("不存在", "没有编号", "未登记", "悬空", "样例", "样本", "假链接", "误抓", "豁免")


def read(path):
    return io.open(path, encoding="utf-8").read()


def lines_of(text):
    return text.split("\n")


def active_docs(root):
    return sorted(glob.glob(os.path.join(root, "docs", "*.md")))


def history_docs(root):
    return sorted(glob.glob(os.path.join(root, "docs", "history", "*.md")))


def span_chars(lines, start, end):
    """1-indexed 闭区间 [start, end] 的字符数，口径＝len(拼接文本)（含行间换行，不含区间外多余额）。"""
    if end < start:
        return 0
    return len("\n".join(lines[start - 1:end]))


def build_sections(lines):
    """把标题树算出来：每节得到 line/level/title/end/span/body/is_leaf/children。

    恒等式：span ＝ 标题行 ＋ body ＋ Σ 直接子节 span（直接子节＝紧邻的、父级恰为本节的那些标题），
    所以 body ＝ span − Σ 子节 span，两把读数不重复计数。
    """
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
        hs[k]["parent"] = stack[-1] if stack else None
        if stack:
            children[stack[-1]].append(k)
        stack.append(k)
    for k in range(n):
        hs[k]["children"] = children[k]
        hs[k]["is_leaf"] = not children[k]
        hs[k]["body"] = hs[k]["span"] - sum(hs[c]["span"] for c in children[k])
    return hs


def speed_scope(lines, secs):
    """速览尺作用域＝首个 H2 之前的行 ∪ 标题命中白名单词的节的整段（1-indexed 行号集合）。"""
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
        # 节尺两读数：叶节看跨度、容器看自身体（恒等式保证二者之和覆盖全篇且不重复）
        sec_hits = []
        for s in secs:
            if s["level"] < 2:   # H1 是文件题名，整篇都算它 ⇒ 不参与单节判定
                continue
            if s["is_leaf"]:
                if s["span"] > MAX_SECTION_CHARS:
                    sec_hits.append(("叶节", s["line"], s["title"], s["span"]))
            elif s["body"] > MAX_SECTION_CHARS:
                sec_hits.append(("自身体", s["line"], s["title"], s["body"]))
        # 速览尺（非标题行）；TITLE 档（任意级标题行）
        scope = speed_scope(lines, secs)
        speed_hits = [(i, len(lines[i - 1])) for i in sorted(scope)
                      if i not in heading_lines and len(lines[i - 1]) > MAX_SPEED_CHARS]
        title_hits = [(s["line"], len(lines[s["line"] - 1]), s["title"]) for s in secs
                      if len(lines[s["line"] - 1]) > MAX_TITLE_CHARS]
        rows.append({
            "path": path,
            "lines": len(lines),
            "chars": len(text),
            "max_line": max([len(x) for x in lines] or [0]),
            "big_lines": sum(1 for x in lines if len(x) > MAX_LINE_CHARS),
            "sec_hits": sec_hits,
            "speed_hits": speed_hits,
            "title_hits": title_hits,
        })
    return rows


def table_scan(paths):
    """表数／数据行数／列数不一致处数（把 data-service/runtime 的三枚临时件并回本件）。"""
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
                    result["mismatches"].append(
                        (path, cur["start"], n, cols, cur["cols"]))
                rows += 1
            else:
                cur = None
        result["tables"] += tables
        result["rows"] += rows
        result["mismatch"] += bad
        result["per_file"].append((path, tables, rows, bad))
    return result


def alarms(rows):
    hits = []
    for r in rows:
        rel = r["path"]
        if r["chars"] > MAX_FILE_CHARS:
            hits.append("[FILE] %s chars=%d > %d" % (rel, r["chars"], MAX_FILE_CHARS))
        if r["big_lines"]:
            hits.append("[LINE] %s 单行 >%d 字符的行＝%d 行（最长 %d）"
                        % (rel, MAX_LINE_CHARS, r["big_lines"], r["max_line"]))
        for kind, ln, title, chars in r["sec_hits"]:
            hits.append("[SECTION·%s] %s:%d chars=%d > %d | %s"
                        % (kind, rel, ln, chars, MAX_SECTION_CHARS, title[:44]))
        for ln, chars in r["speed_hits"]:
            hits.append("[SPEED] %s:%d chars=%d > %d" % (rel, ln, chars, MAX_SPEED_CHARS))
        for ln, chars, title in r["title_hits"]:
            hits.append("[TITLE] %s:%d chars=%d > %d | %s"
                        % (rel, ln, chars, MAX_TITLE_CHARS, title[:44]))
    return hits


def iter_labels(text):
    """节次标签引用；「追加」作动词时（追加一行／追加两条）不算引用。"""
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


def has_pointer_on(path, label):
    """原地那一行既要带标签、又要指向归档——两个条件同行才算指针（防"提到了但没搬家"的假指针）。"""
    for line in lines_of(read(path)):
        if label in line and any(h in line for h in POINTER_HINT):
            return True
    return False


def line_iter(text):
    """逐行给出正文（跳过 ``` 代码块内部，框图里的 `[x](y)` 不是链接）。"""
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
    items = set()
    for path in [led] + history:
        if not os.path.exists(path):
            continue
        for line in lines_of(read(path)):
            m = ITEM_HEAD.match(line)
            if m:
                items.add(m.group(1))
    broken = []
    counts = {"append": 0, "item": 0, "link": 0, "meta_exempt": 0}
    for path in active:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
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
                    # 只有「拥有追加节的文件」欠一行指针；别的文件引用它，标签能落地就算通
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
    return broken, counts, len(all_labels)


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
            # 跨度＝到下一枚编号行或任意级标题，取先者（#61 教训：按"下一枚编号行"会让第 61 项吞门槛区）
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
    print("块跨度：L%d–L%d（%d 行，%d 字符）" % (start, end, end - start + 1,
                                          span_chars(lines, start, end)))
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
    print("越界检查：通过（块内每枚标题的跨度都落在块内）")
    return 0


def report(root="."):
    paths = active_docs(root)
    rows = size_rows(paths)
    print("== 体量读数（对着哪一棵树：本轮工作区；行数只作参考，不作闸） ==")
    for r in rows:
        print("%-26s lines=%-5d chars=%-8d big_line=%-3d max_line=%-6d"
              % (os.path.relpath(r["path"], root).replace(os.sep, "/"), r["lines"], r["chars"],
                 r["big_lines"], r["max_line"]))
    hits = alarms(rows)
    print("== 超标报警 ==")
    print("\n".join(hits) if hits else "（无）")
    ts = table_scan(paths)
    print("== 表格扫描：表=%d 数据行=%d 错位=%d ==" % (ts["tables"], ts["rows"], ts["mismatch"]))
    for r in ts["per_file"]:
        print("  %-26s tables=%-3d rows=%-4d mismatch=%d"
              % (os.path.relpath(r[0], root).replace(os.sep, "/"), r[1], r[2], r[3]))
    for path, hdr, ln, cols, exp in ts["mismatches"]:
        print("  MISMATCH %s 表头 L%d／错位 L%d cols=%d != %d"
              % (os.path.relpath(path, root).replace(os.sep, "/"), hdr, ln, cols, exp))
    broken, counts, labels = link_scan(root)
    print("== 断链扫描：真引用 追加=%d／第N项=%d／链接=%d，元文本豁免=%d，已知标签数=%d =="
          % (counts["append"], counts["item"], counts["link"], counts["meta_exempt"], labels))
    print("   （豁免＝同一行含 %s 之一——那一行是在**谈**这个标签而不是引用它；这一档的残留见文件头注）"
          % "／".join(META_MARKERS))
    print("\n".join(broken) if broken else "断链＝0")
    return len(hits), len(broken)


def selftest():
    root = tempfile.mkdtemp(prefix="docs-scan-selftest-")
    try:
        os.makedirs(os.path.join(root, "docs", "history"))
        io.open(os.path.join(root, "docs", "CODE-REVIEW.md"), "w",
                encoding="utf-8", newline="\n").write(
                    "# review\n\n#### 追加一 · 活着的一节\n正文\n\n"
                    "追加十二 已整节搬至 docs/history/2026-01-01-x.md（归档，这一行就是留着的指针）\n\n"
                    "追加十三 的教训还在别处被引用，可这一行什么都没留\n\n"
                    "追加九百九十九 是盘上查无此节的一个编号\n\n"
                    "按纪律在门槛节追加一行带出处、原句不动（动词用法，不是节次）\n\n"
                    "元文本豁免样例：这一行说『追加九百九十九』这个标签在盘上不存在，是在谈它，不是引用它\n\n"
                    "样例：第 999 项 这种写法在盘上不存在，这一行是在谈它（豁免），不是引用它\n\n"
                    "```\n│  product/[type]/[code](图表) / chat(统一Agent)  │\n│ [x](gone-inside-fence.md) │\n```\n")
        io.open(os.path.join(root, "docs", "FIX-LEDGER.md"), "w",
                encoding="utf-8", newline="\n").write(
                    "# ledger\n\n1. 活条目\n\n见第 1 项好；见第 999 项坏；[链接](history/gone.md)坏；"
                    "[本地](CODE-REVIEW.md)好\n")
        io.open(os.path.join(root, "docs", "history", "2026-01-01-x.md"), "w",
                encoding="utf-8", newline="\n").write(
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
            "动词用法不误报": "「追加一」" not in joined and "追加一行" not in joined,
            "代码块内链接不误报": "gone-inside-fence.md" not in joined,
            "元文本豁免计入而非静默放过": counts["meta_exempt"] >= 2 and "追加九百九十九」在任何标题" in joined,
            "归档标题计入集合": labels == 3,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
    verdict = "PASS" if all(checks.values()) else "FAIL"
    print("SELFTEST %s %s broken=%d refs=%s" % (verdict, checks, len(broken), counts))
    for line in broken:
        print("  样本断链:", line)
    return 0 if verdict == "PASS" else 1


def parse_move_spec(argv):
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
    # 本机控制台是 GBK：中文读数直接 print 会被码页打断，统一按 UTF-8 出（必要时替换非法字节）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    if "--plan" in argv:
        return run_plan(".", parse_move_spec(argv))
    _, broken = report(".")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
