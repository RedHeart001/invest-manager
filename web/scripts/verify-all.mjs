// 状态确认：串行跑全部 web 集成套件并汇总
import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const suites = ["test-db.mjs", "test-p1.mjs", "test-p3.mjs", "test-p4.mjs", "test-p6.mjs", "test-p5.mjs"];
const lines = [];
for (const s of suites) {
  const started = Date.now();
  const r = spawnSync(process.execPath, [`scripts/${s}`], {
    cwd: process.cwd(),
    encoding: "utf8",
    timeout: 20 * 60 * 1000,
    env: { ...process.env, TEST_BASE: "http://localhost:3000" },
  });
  const out = `${r.stdout ?? ""}\n${r.stderr ?? ""}`;
  const tail = out
    .split("\n")
    .filter((l) => /=====|通过|失败|OK|NG|PASS|FAIL/i.test(l))
    .slice(-14)
    .join("\n");
  lines.push(
    `\n########## ${s} — exit=${r.status} 用时 ${Math.round((Date.now() - started) / 1000)}s ##########\n${tail}`,
  );
  console.log(`${s}: exit=${r.status}`);
}
writeFileSync("verify-suites.txt", lines.join("\n"), "utf8");
console.log("ALL DONE");
