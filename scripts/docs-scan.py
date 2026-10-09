#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""docs 收尾体检——`.claude/rules/project.md`「docs 体量治理（2026-10-09 立）」的执行件。

两半（都不写盘、零出网）：
  1. 体量三读数：单文件 >120,000 字符／单行 >1,500 字符／单节 >30,000 字符 ⇒ 只报警，不动笔。**行数不作闸**。
  2. 断链扫描：活跃工作区里每个「追加N」「第 N 项」「相对链接」都要能落地——标签要么还在某个标题里，
     要么已进 `docs/history/` 且**原地留着带同一标签的指针行**；条目号要么在 FIX-LEDGER，要么在归档里；
     相对链接的目标文件必须存在。

用法：
    python scripts/docs-scan.py            # 读数＋报警＋断链结果（无断链时打印「断链＝0」）
    python scripts/docs-scan.py --selftest # 四枚样本证明这闸自己会红（3 枚坏必须被抓、1 枚好不许误报）

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

HEAD = re.compile(r"^\s*>*\s*(#{1,6})\s+(.*)$")
APPEND_LABEL = re.compile(r"^(追加[〇零一二三四五六七八九十百]+)")
APPEND_REF = re.compile(r"追加[〇零一二三四五六七八九十百]+")
ITEM_REF = re.compile(r"第\s*([0-9]{1,3})\s*项")
ITEM_HEAD = re.compile(r"^([0-9]{1,3})\.\s")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"^\s*```")
# 「追加」后面跟量词或区间号时是散文用法（追加一行／追加两段／追加一–九），不是节次引用——两类都不能算断链
QUANT_AFTER = set("个条枚行项次句要上入两段–—~-～至到")
POINTER_HINT = ("搬", "归档", "指针", "history")
APPEND_OWNER = "CODE-REVIEW.md"  # 「追加N」这一族节次的归属文件（只有它欠留指针行）


def read(path):
    return io.open(path, encoding="utf-8").read()


def lines_of(text):
    return text.split("\n")


def active_docs(root):
    return sorted(glob.glob(os.path.join(root, "docs", "*.md")))


def history_docs(root):
    return sorted(glob.glob(os.path.join(root, "docs", "history", "*.md")))


def strip_fences(text):
    """把 ``` 代码块内部抹成空行（保留行数以对齐）——ASCII 框图里的 `[x](y)` 不是链接。"""
    out = []
    inside = False
    for line in text.split("\n"):
        if FENCE.match(line):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else line)
    return "\n".join(out)


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


def size_rows(paths):
    rows = []
    for path in paths:
        text = read(path)
        lines = lines_of(text)
        hs = [(n, len(m.group(1)), m.group(2).strip())
              for n, m in ((i + 1, HEAD.match(l)) for i, l in enumerate(lines)) if m]
        worst = (0, "", 0)
        # 节＝从本级标题到"下一个同级或更高级标题"；H1 是文件题名，整篇都算它 ⇒ 不参与单节判定
        for k, (n, level, title) in enumerate(hs):
            if level < 2:
                continue
            end = len(lines)
            for n2, level2, _ in hs[k + 1:]:
                if level2 <= level:
                    end = n2 - 1
                    break
            chars = sum(len(x) + 1 for x in lines[n - 1:end])
            if chars > worst[2]:
                worst = (n, title, chars)
        rows.append({
            "path": path,
            "lines": len(lines),
            "chars": len(text),
            "max_line": max([len(x) for x in lines] or [0]),
            "big_lines": sum(1 for x in lines if len(x) > MAX_LINE_CHARS),
            "section_line": worst[0],
            "section_title": worst[1][:44],
            "section_chars": worst[2],
        })
    return rows


def alarms(rows):
    hits = []
    for r in rows:
        if r["chars"] > MAX_FILE_CHARS:
            hits.append("FILE %s chars=%d > %d" % (r["path"], r["chars"], MAX_FILE_CHARS))
        if r["big_lines"]:
            hits.append("LINE %s 单行 >%d 字符的行＝%d 行（最长 %d）"
                        % (r["path"], MAX_LINE_CHARS, r["big_lines"], r["max_line"]))
        if r["section_chars"] > MAX_SECTION_CHARS:
            hits.append("SECTION %s:%d chars=%d > %d | %s"
                        % (r["path"], r["section_line"], r["section_chars"],
                           MAX_SECTION_CHARS, r["section_title"]))
    return hits


def has_pointer_on(path, label):
    """原地那一行既要带标签、又要指向归档——两个条件同行才算指针（防"提到了但没搬家"的假指针）。"""
    for line in lines_of(read(path)):
        if label in line and any(h in line for h in POINTER_HINT):
            return True
    return False


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
    counts = {"append": 0, "item": 0, "link": 0}
    for path in active:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        text = strip_fences(read(path))
        for lab in iter_labels(text):
            counts["append"] += 1
            if lab not in all_labels:
                broken.append("%s: 「%s」在任何标题里都不存在" % (rel, lab))
            elif (lab not in active_labels
                  and os.path.basename(path) == APPEND_OWNER
                  and not has_pointer_on(path, lab)):
                # 只有「拥有追加节的文件」欠一行指针；别的文件引用它，标签能落地就算通
                broken.append("%s: 「%s」已搬进归档，但原地没有带标签的指针行" % (rel, lab))
        for m in ITEM_REF.finditer(text):
            counts["item"] += 1
            if m.group(1) not in items:
                broken.append("%s: 「第 %s 项」在 FIX-LEDGER 与归档里都没有条目行" % (rel, m.group(1)))
        for m in MD_LINK.finditer(text):
            target = m.group(1).split("#")[0].strip()
            if not target or target.startswith(("http:", "https:", "mailto:")):
                continue
            counts["link"] += 1
            if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(path), target))):
                broken.append("%s: 链接目标不存在 %s" % (rel, target))
    return broken, counts, len(all_labels)


def report(root="."):
    rows = size_rows(active_docs(root))
    print("== 体量读数（对着哪一棵树：本轮工作区；行数只作参考，不作闸） ==")
    for r in rows:
        print("%-26s lines=%-5d chars=%-8d big_lines=%-3d max_line=%-6d worst_section=%-8d @:%-5d %s"
              % (os.path.relpath(r["path"], root).replace(os.sep, "/"), r["lines"], r["chars"],
                 r["big_lines"], r["max_line"], r["section_chars"], r["section_line"],
                 r["section_title"]))
    hits = alarms(rows)
    print("== 超标报警 ==")
    print("\n".join(hits) if hits else "（无）")
    broken, counts, labels = link_scan(root)
    print("== 断链扫描：引用数=%s，已知标签数=%d ==" % (counts, labels))
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
                    "追加九百九十九 是悬空标签\n\n"
                    "按纪律在门槛节追加一行带出处、原句不动（动词用法，不是节次）\n\n"
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
            "归档标题计入集合": labels == 3,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
    verdict = "PASS" if all(checks.values()) else "FAIL"
    print("SELFTEST %s %s broken=%d refs=%s" % (verdict, checks, len(broken), counts))
    for line in broken:
        print("  样本断链:", line)
    return 0 if verdict == "PASS" else 1


def main():
    # 本机控制台是 GBK：中文读数直接 print 会被码页打断，统一按 UTF-8 出（必要时替换非法字节）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--selftest" in sys.argv[1:]:
        return selftest()
    _, broken = report(".")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
