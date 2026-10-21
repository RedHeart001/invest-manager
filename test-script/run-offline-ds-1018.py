"""本轮专用：跑 ② 的离线 ds 套件，但排除会买额度的那一枚（test_p6_mcp 自带一条无条件真报价）。

不改良生产件，只在 gitignored 的 runtime/ 里落一份临时跑法；汇总行字面按 gate.mjs 的两套正则解析，
解析不出＝红（不许当成 0/0 通过）。
"""
import os
import re
import subprocess
import sys

DS = "data-service"
PY = os.path.join(DS, ".venv", "Scripts", "python.exe")
LIVE = {"test_p0.py", "test_p1.py"}
PAID = {"test_p6_mcp.py"}
RE = [re.compile(r"=====\s*(\d+)/(\d+)\s*通过"), re.compile(r"==\s*[^=：\n]*[:：]\s*(\d+)/(\d+)\s*通过")]

names = sorted(n for n in os.listdir(os.path.join(DS, "tests")) if n.startswith("test_") and n.endswith(".py"))
skip = names.count("test_p6_mcp.py") and (LIVE | PAID) or LIVE
run = [n for n in names if n not in skip]

tp = tn = fails = 0
lines = []
for n in run:
    p = os.path.join(DS, "tests", n)
    r = subprocess.run([PY, p], capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    m = next((x for x in (rx.search(out) for rx in RE) if x), None)
    if not m:
        fails += 1
        lines.append("NG(解析不出) %s exit=%s tail=%s" % (n, r.returncode, out.strip()[-160:].replace("\n", " ")))
        continue
    a, b = int(m.group(1)), int(m.group(2))
    tp += a
    tn += b
    if a != b or r.returncode != 0:
        fails += 1
        bad = [l.strip() for l in out.split("\n") if "NG" in l][:8]
        lines.append("NG %s %d/%d exit=%s\n    %s" % (n, a, b, r.returncode, "\n    ".join(bad)))
    else:
        lines.append("OK %s %d/%d" % (n, a, b))

print("\n".join(lines))
print("== 标题：本轮离线跑 %d 套（② 24 枚减去 %s）：%d/%d 通过，失败 %d 枚 ==" % (len(run), sorted(skip), tp, tn, fails))
sys.exit(1 if fails else 0)
