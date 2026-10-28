/**
 * 零漂移词库导出器
 * ---------------------------------------------------------------
 * 把 ANIMA提示词生成器.html 里内嵌的 JS 词库常量，原样导出成
 * presets/anima_v4_pools.json，供 Python 规则层读取。
 *
 * 手法（与 Krea2-Portrait-V12 的 export_v12_pools.mjs 同构）：
 *   ① 正则切出三段 <script>；
 *   ② 造一套极简 DOM 桩（只满足脚本加载期会碰到的调用）；
 *   ③ 用 vm 沙箱把三段脚本当普通 JS 跑一遍；
 *   ④ 在**同一段源码**末尾追加一行 globalThis.__EXPORT__ = {...} 把
 *      词库常量捞出来 —— 不能靠读沙箱属性，因为 `const` 声明落在
 *      全局词法环境里，不会挂到 sandbox 对象上。
 *
 * ⚠️ 词库的唯一真源永远是那份 HTML。只改 JSON 不改 HTML，
 *    下次导出会被原样冲回去。
 *
 * 用法：
 *   node tools/export_v3_pools.mjs [源HTML] [输出JSON] [--check]
 *   --check 只对拍不写盘（CI / 回归用）
 */
import fs from "fs";
import path from "path";
import crypto from "crypto";
import vm from "vm";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.resolve(HERE, "..");

const DEFAULT_SRC = "S:/ComfyUI/提示词/ANIMA提示词生成器.html";
const DEFAULT_OUT = path.join(PLUGIN_ROOT, "presets", "anima_v4_pools.json");

const argv = process.argv.slice(2);
const CHECK_ONLY = argv.includes("--check");
const positional = argv.filter((a) => !a.startsWith("--"));
const SRC = positional[0] || DEFAULT_SRC;
const OUT = positional[1] || DEFAULT_OUT;

// ── ① 极简 DOM 桩 ──────────────────────────────────────────────
// 目的只有一个：让第三块脚本在加载期不抛异常。所有节点操作都是空转，
// 我们不依赖它产出任何数据。
function makeEl(tag = "div") {
  const el = {
    tagName: tag,
    innerHTML: "",
    textContent: "",
    value: "",
    type: "",
    className: "",
    dataset: {},
    style: {},
    children: [],
    open: false,
    selected: false,
    disabled: false,
    classList: {
      toggle() {},
      add() {},
      remove() {},
      contains() {
        return false;
      },
    },
    appendChild(c) {
      this.children.push(c);
      return c;
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
    removeEventListener() {},
    focus() {},
    click() {},
    setAttribute() {},
    getAttribute() {
      return null;
    },
  };
  return el;
}

const docStub = {
  createElement: (t) => makeEl(t),
  createTextNode: () => makeEl("text"),
  getElementById: () => makeEl("div"),
  querySelector: () => null,
  querySelectorAll: () => [],
  body: makeEl("body"),
  head: makeEl("head"),
  addEventListener() {},
};

const sandbox = {
  document: docStub,
  window: {},
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  console,
  setTimeout,
  clearTimeout,
  URL: { createObjectURL: () => "blob:stub" },
  Blob: function () {},
  showSaveFilePicker: undefined,
};
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
vm.createContext(sandbox);

// ── ② 切 script + ③ 跑 + ④ 导出 ───────────────────────────────
const html = fs.readFileSync(SRC, "utf8");
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
if (blocks.length < 3) {
  throw new Error(`script 块数量异常：期望 ≥3，实际 ${blocks.length}`);
}

const EXPORT_LINE = `
;globalThis.__EXPORT__ = {
  SECTIONS: SECTIONS,
  CANON: CANON,
  APPEAR: APPEAR,
  MUTEX_GROUPS: MUTEX_GROUPS,
  DROP_LIST: typeof dropList !== "undefined" ? dropList : null,
  TAG_CAP: typeof cap !== "undefined" ? cap : null,
};
`;

// 三块合成一段源码再跑：`const` 词法绑定只在同一段脚本内可见。
const combined = blocks.join("\n;\n") + EXPORT_LINE;
try {
  vm.runInContext(combined, sandbox, { filename: "anima-generator.js" });
} catch (err) {
  // 第三块脚本末尾会调 render()，DOM 桩已覆盖；仍抛错说明源文件结构变了，
  // 这时必须显式失败，绝不能静默产出半份词库。
  throw new Error(`沙箱执行失败（源脚本结构可能已变）：${err.message}`);
}

const bag = sandbox.__EXPORT__;
if (!bag || !Array.isArray(bag.SECTIONS) || !bag.SECTIONS.length) {
  throw new Error("未能从沙箱导出 SECTIONS，导出中止");
}

// ── ⑤ 规整成 JSON 友好的形状 ───────────────────────────────────
function normalizeSections(sections) {
  return sections.map((s) => ({
    id: s.id,
    title: s.title,
    open: !!s.open,
    cls: s.cls || "",
    fields: (s.fields || []).map((f) => ({
      key: f.key,
      lab: f.lab,
      req: !!f.req,
      type: f.type || "select",
      tail: !!f.tail,
      opts: (f.opts || []).map(([zh, en]) => [zh, en]),
    })),
  }));
}

// 正则字面量不能 JSON 序列化 —— 拆成 source / flags 两个字符串，
// Python 侧用 re.compile(source, flags) 复原。
function normalizeMutex(groups) {
  return (groups || []).map((g) => ({
    id: g.id,
    a: { source: g.a.source, flags: g.a.flags || "" },
    b: { source: g.b.source, flags: g.b.flags || "" },
  }));
}

const sections = normalizeSections(bag.SECTIONS);
const canon = {};
for (const [k, v] of Object.entries(bag.CANON || {})) {
  canon[k] = { ...v };
}

const counters = {
  sections: sections.length,
  fields: sections.reduce((n, s) => n + s.fields.length, 0),
  options: sections.reduce((n, s) => n + s.fields.reduce((m, f) => m + f.opts.length, 0), 0),
  roles: (sections.find((s) => s.id === "count")?.fields.find((f) => f.key === "role")?.opts || []).length,
  appear: Object.keys(bag.APPEAR || {}).length,
  canon: Object.keys(canon).length,
  mutex: (bag.MUTEX_GROUPS || []).length,
};

const payload = {
  _meta: {
    source_file: path.basename(SRC),
    source_path: SRC.replace(/\\/g, "/"),
    source_sha256: crypto.createHash("sha256").update(fs.readFileSync(SRC)).digest("hex"),
    schema: "anima-wardrobe-v4/pools@1",
    generated_by: "tools/export_v3_pools.mjs",
    counters,
  },
  sections,
  canon,
  appear: bag.APPEAR || {},
  mutex_groups: normalizeMutex(bag.MUTEX_GROUPS),
};

const text = JSON.stringify(payload, null, 1) + "\n";

if (CHECK_ONLY) {
  if (!fs.existsSync(OUT)) {
    console.error(`[export_v3_pools] --check 失败：${OUT} 不存在`);
    process.exit(1);
  }
  const old = JSON.parse(fs.readFileSync(OUT, "utf8"));
  const a = JSON.stringify(old.sections) + JSON.stringify(old.canon) + JSON.stringify(old.appear);
  const b = JSON.stringify(payload.sections) + JSON.stringify(payload.canon) + JSON.stringify(payload.appear);
  if (a !== b) {
    console.error("[export_v3_pools] --check 失败：磁盘 JSON 与源 HTML 已漂移");
    process.exit(1);
  }
  console.log(`[export_v3_pools] --check 通过（${counters.sections} 段 / ${counters.fields} 字段 / ${counters.options} 选项）`);
} else {
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, text, "utf8");
  console.log(`[export_v3_pools] 已写出 ${OUT}`);
  console.log(`  段 ${counters.sections} · 字段 ${counters.fields} · 选项 ${counters.options} · 角色 ${counters.roles} · APPEAR ${counters.appear} · 法典 ${counters.canon} · 互斥 ${counters.mutex}`);
  console.log(`  源 sha256 ${payload._meta.source_sha256.slice(0, 16)}…`);
}
