/**
 * #59 的守卫：把「同一父节点下两个兄弟共用同一个 key」这一类错误变成一道自动闸。
 *
 * 为什么用源码 AST 而不是渲染测试：这个仓库现在零 UI 组件测试覆盖，为一条 key 规则去挂
 * jsdom／渲染栈的成本远大于收益；而这一类错误在**源码结构里就可判定**，不需要真渲染。
 *
 * 三条规则（都只看「元素被当作 JSX children 的那一位」，所以不碰非渲染用途的 .map）：
 *  - R1 同一个父节点的子节点之间，key 的字面完全相同 ⇒ 撞（同一作用域里同串表达式必然同值）。
 *  - R2 JSX children 位置上的 `.map(...)` 返回元素却没有 key（含 `<>…</>` 这种挂不上 key 的形状）。
 *  - R3 `.map(...)` 返回的元素的 key 是常量 ⇒ 整列表必然同一个值。
 *
 * 已知残留（静态判不出的，写清楚而不是假装覆盖）：两个**不同串**的表达式在运行时取值相同
 * （`${a}` 与 `${b}` 而 a===b）、key 藏在 fragment 里的兄弟、以及**先 `.map` 成变量再当 children 用**
 * 的那一种（本闸只认 JSX children 位置上的 `.map`，否则会把「构造节点数组」的正常用法误报）。
 * 这三形要拦就得渲染，不在本闸内。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import ts from "typescript";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCAN_DIRS = ["app"];

export type KeyFinding = {
  rule: "R1" | "R2" | "R3";
  file: string;
  line: number;
  detail: string;
};

type JsxLike = ts.JsxElement | ts.JsxSelfClosingElement | ts.JsxFragment;
type KeyInfo = { text: string; constant: boolean };

function tsxFiles(dir: string, out: string[] = []): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    if (name === "node_modules" || name === ".next") continue;
    const p = path.join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) tsxFiles(p, out);
    else if (name.endsWith(".tsx")) out.push(p);
  }
  return out;
}

function keyOf(el: JsxLike): KeyInfo | null {
  if (ts.isJsxFragment(el)) return null;
  const open = ts.isJsxElement(el) ? el.openingElement : el;
  for (const prop of open.attributes.properties) {
    if (!ts.isJsxAttribute(prop) || prop.name.getText() !== "key") continue;
    if (!prop.initializer) return { text: "true", constant: true };
    if (ts.isStringLiteral(prop.initializer)) {
      return { text: prop.initializer.text, constant: true };
    }
    if (ts.isJsxExpression(prop.initializer) && prop.initializer.expression) {
      const e = prop.initializer.expression;
      const text = e.getText().trim();
      const constant =
        ts.isStringLiteral(e) ||
        ts.isNumericLiteral(e) ||
        e.kind === ts.SyntaxKind.TrueKeyword ||
        e.kind === ts.SyntaxKind.FalseKeyword ||
        !/[A-Za-z_$]/.test(text);
      return { text, constant };
    }
    return null;
  }
  return null;
}

function lineOf(sf: ts.SourceFile, node: ts.Node): number {
  return sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
}

/** 拆掉 `cond && <X/>`、`c ? <X/> : <Y/>`、括号，取出这一位上可能出现的元素 */
function elementsInSlot(node: ts.Node): JsxLike[] {
  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxFragment(node)) {
    return [node as JsxLike];
  }
  if (ts.isParenthesizedExpression(node)) return elementsInSlot(node.expression);
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
    return [...elementsInSlot(node.left), ...elementsInSlot(node.right)];
  }
  if (ts.isConditionalExpression(node)) {
    return [...elementsInSlot(node.whenTrue), ...elementsInSlot(node.whenFalse)];
  }
  return [];
}

/** 一个 children 数组里每个「槽位」实际参与 React 比较的那个元素（React 只认每一位的第一个） */
function slots(children: readonly ts.JsxChild[]): JsxLike[] {
  const out: JsxLike[] = [];
  for (const child of children) {
    if (ts.isJsxElement(child) || ts.isJsxSelfClosingElement(child) || ts.isJsxFragment(child)) {
      out.push(child as JsxLike);
      continue;
    }
    if (ts.isJsxExpression(child) && child.expression) {
      const first = elementsInSlot(child.expression)[0];
      if (first) out.push(first);
    }
  }
  return out;
}

function isJsxChildrenPosition(node: ts.Node): boolean {
  let p: ts.Node | undefined = node.parent;
  while (p) {
    if (ts.isJsxExpression(p) && p.expression === node) return true;
    p = p.parent;
  }
  return false;
}

/** `.map` 回调交给「这一位」的元素 */
function returnedElements(fn: ts.Node | undefined): JsxLike[] {
  if (!fn || (!ts.isArrowFunction(fn) && !ts.isFunctionExpression(fn))) return [];
  const body = fn.body;
  if (!ts.isBlock(body)) return elementsInSlot(body);
  const out: JsxLike[] = [];
  for (const stmt of body.statements) {
    if (ts.isReturnStatement(stmt) && stmt.expression) out.push(...elementsInSlot(stmt.expression));
  }
  return out;
}

export function scanSource(text: string, label: string): KeyFinding[] {
  const sf = ts.createSourceFile(label, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const rel = label.replace(/\\/g, "/");
  const findings: KeyFinding[] = [];

  const visit = (node: ts.Node): void => {
    if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
      const seen = new Map<string, number>();
      for (const slotEl of slots(node.children)) {
        const k = keyOf(slotEl);
        if (!k) continue;
        const line = lineOf(sf, slotEl);
        const prev = seen.get(k.text);
        if (prev !== undefined) {
          findings.push({ rule: "R1", file: rel, line, detail: `key 与同父兄弟（:${prev}）字面相同＝${k.text}` });
        } else {
          seen.set(k.text, line);
        }
      }
    }

    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "map" &&
      isJsxChildrenPosition(node) &&
      node.arguments.length >= 1
    ) {
      for (const el of returnedElements(node.arguments[0])) {
        const line = lineOf(sf, el);
        if (ts.isJsxFragment(el)) {
          findings.push({ rule: "R2", file: rel, line, detail: "在 JSX children 位置的 .map 返回 `<>…</>`，短 fragment 挂不上 key" });
          continue;
        }
        const k = keyOf(el);
        if (!k) findings.push({ rule: "R2", file: rel, line, detail: "在 JSX children 位置的 .map 里返回元素却没有 key" });
        else if (k.constant) findings.push({ rule: "R3", file: rel, line, detail: `.map 返回元素的 key 是常量＝${k.text}（整列表必然同一个值）` });
      }
    }

    ts.forEachChild(node, visit);
  };
  visit(sf);
  return findings;
}

export function scannedFiles(): string[] {
  const files: string[] = [];
  for (const dir of SCAN_DIRS) tsxFiles(path.join(ROOT, dir), files);
  return files.sort();
}

function scanFile(abs: string): KeyFinding[] {
  return scanSource(readFileSync(abs, "utf8"), path.relative(ROOT, abs));
}

export function scanRepo(): KeyFinding[] {
  return scannedFiles().flatMap(scanFile);
}

describe("JSX key 守卫（#59）", () => {
  it("闸自己坏掉时不能静默全绿＝扫到的 .tsx 数必须大于 10", () => {
    expect(scannedFiles().length).toBeGreaterThan(10);
  });

  it("R1 同父兄弟的 key 不许字面同串", () => {
    expect(scanRepo().filter((f) => f.rule === "R1")).toEqual([]);
  });

  it("R2 JSX children 位置的 .map 必须给 key", () => {
    expect(scanRepo().filter((f) => f.rule === "R2")).toEqual([]);
  });

  it("R3 .map 返回元素的 key 不许是常量", () => {
    expect(scanRepo().filter((f) => f.rule === "R3")).toEqual([]);
  });

  // —— 成对断言：合成样本只证明「闸会红」，库内扫描才证明「现在没有红的」。两半都要有。 ——
  const wrap = (jsx: string) => (jsx.trimStart().startsWith("<") ? `const el = (\n${jsx}\n);\n` : `${jsx}\n`);
  const rulesOf = (jsx: string) => scanSource(wrap(jsx), "fixture.tsx").map((f) => f.rule);

  it("合成样本能点亮 R1（同串 key 的兄弟）", () => {
    expect(rulesOf(`<main>\n  <Charts key={\`\${type}:\${code}\`} />\n  <Research key={\`\${type}:\${code}\`} />\n</main>`)).toEqual(["R1"]);
  });

  it("合成样本里加了命名空间的同一对兄弟＝R1 不报", () => {
    expect(rulesOf(`<main>\n  <Charts key={\`charts:\${type}:\${code}\`} />\n  <Research key={\`research:\${type}:\${code}\`} />\n</main>`)).toEqual([]);
  });

  it("合成样本能点亮 R1 的条件兄弟形", () => {
    expect(rulesOf(`<div>\n  {ok && <A key="x" />}\n  {!ok && <B key="x" />}\n</div>`)).toEqual(["R1"]);
  });

  it("合成样本能点亮 R2（.map 没 key／短 fragment），补齐后转绿", () => {
    expect(rulesOf(`<ul>\n  {rows.map((r) => <li>{r.name}</li>)}\n</ul>`)).toEqual(["R2"]);
    expect(rulesOf(`<ul>\n  {rows.map((r) => <><li>{r.name}</li></>)}\n</ul>`)).toEqual(["R2"]);
    expect(rulesOf(`<ul>\n  {rows.map((r) => <li key={r.id}>{r.name}</li>)}\n</ul>`)).toEqual([]);
  });

  it("合成样本能点亮 R3（map 里 key 是常量），换成项来源后转绿", () => {
    expect(rulesOf(`<ul>\n  {rows.map((r) => <li key="row">{r.name}</li>)}\n</ul>`)).toEqual(["R3"]);
    expect(rulesOf(`<ul>\n  {rows.map((r) => <li key={7}>{r.name}</li>)}\n</ul>`)).toEqual(["R3"]);
    expect(rulesOf(`<ul>\n  {rows.map((r) => <li key={\`row:\${r.id}\`}>{r.name}</li>)}\n</ul>`)).toEqual([]);
  });

  it("两处刻意放行＝下标 key 不算撞、非 children 位置的 .map 不归本闸管", () => {
    expect(rulesOf(`<ul>\n  {rows.map((r, i) => <li key={i}>{r.name}</li>)}\n</ul>`)).toEqual([]);
    expect(rulesOf(`const nodes = rows.map((r) => <li>{r.name}</li>);`)).toEqual([]);
  });
});
