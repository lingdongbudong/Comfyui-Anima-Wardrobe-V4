/**
 * Anima V3 面板 · 前端冒烟
 * ---------------------------------------------------------------------------
 * 不是"语法检查"那种假冒烟。这里真的把面板跑起来：
 *   ① 用 jsdom 造一个真 DOM；
 *   ② 把插件 JS 复制到临时目录，让 `../../scripts/app.js` 能解析到桩；
 *   ③ 桩里的 fetchApi 喂的是 tools/dump_ui_fixtures.py 从**真后端**导出的
 *      夹具 —— 接口改了字段名，这里立刻红；
 *   ④ 真去点按钮、填权重、读控件，断言结果。
 *
 * ⚠️ jsdom 陷阱（本项目踩过，写用例前必读）：
 *   · `h()` 传含换行的模板字符串会让 cssText 整段丢弃 →
 *     断言**不能靠 style.x / cssText 定位**，要用 DOM 结构或 getAttribute。
 *   · 同名文本跨区重复 → 查找必须限定在目标区（这里全用 querySelector
 *     限定在具体容器下，不全局搜文本）。
 *   · 用例之间共享同一个 node 状态 → 新用例前先复位。
 *
 * 跑法：node tests/av3_ui_smoke.mjs
 *      （需先跑 python tools/dump_ui_fixtures.py 生成夹具）
 */
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN = path.dirname(HERE);
const SRC_JS = path.join(PLUGIN, "js", "anima_wardrobe_v4_studio.js");
const FIX = path.join(HERE, "fixtures");

let PASS = 0;
const FAILS = [];
function ck(name, cond, note = "") {
  if (cond) {
    PASS++;
    console.log(`  [OK] ${name}`);
  } else {
    FAILS.push(name);
    console.log(`  [!!] ${name}${note ? "  " + note : ""}`);
  }
}

/* ── 0. 前置检查 ─────────────────────────────────────────────────── */
for (const f of ["pools.json", "contract.json", "characters.json", "scenes.json"]) {
  if (!fs.existsSync(path.join(FIX, f))) {
    console.error(`缺少夹具 ${f}，请先跑：python tools/dump_ui_fixtures.py`);
    process.exit(2);
  }
}
const POOLS = JSON.parse(fs.readFileSync(path.join(FIX, "pools.json"), "utf8"));
const CONTRACT = JSON.parse(fs.readFileSync(path.join(FIX, "contract.json"), "utf8"));

/* 角色库夹具：**真实全量数据**（2687 条 / 288 作品）。
   ⚠️⚠️ 这里以前是手写的 6 条合成数据，于是漏掉了一个线上 bug：
      我把 character.work 写成了 slug，而真实数据里它是**作品英文名** ——
      「点 IP 作品 → 角色列表空掉」就在 66 条断言全绿的情况下溜了过去。
      夹具必须与真后端同源，这条没有例外。

   ⚠️ 也**不能抽样**：works[].count 必须与 characters 里属于该作品的实际
      条数一致，否则「点作品 → 卡片数 == count」这条断言测的就是假数据。*/
const CHAR_FIX = JSON.parse(
  fs.readFileSync(path.join(FIX, "characters.json"), "utf8"));
/* 场景搭配库夹具（v3.9.0）—— 同样是真后端导出的 */
const SCENE_FIX = JSON.parse(
  fs.readFileSync(path.join(FIX, "scenes.json"), "utf8"));
/* 夹具形状自检：夹具本身不自洽的话，后面所有断言都是空转。 */
{
  const ids = new Set(CHAR_FIX.works.map((w) => w.id));
  const bad = CHAR_FIX.characters.filter((c) => !ids.has(c.work_id));
  if (bad.length) {
    console.error(`夹具自检失败：${bad.length} 条角色的 work_id 不在 works.id 里，`
      + `例 ${bad.slice(0, 3).map((c) => `${c.tag}→${c.work_id || "(空)"}`).join(", ")}`);
    process.exit(3);
  }
  const cnt = new Map();
  for (const c of CHAR_FIX.characters) cnt.set(c.work_id, (cnt.get(c.work_id) || 0) + 1);
  const mismatch = CHAR_FIX.works.filter((w) => (cnt.get(w.id) || 0) !== w.count);
  if (mismatch.length) {
    console.error(`夹具自检失败：${mismatch.length} 个作品的 count 与实际条数不符，`
      + `例 ${mismatch.slice(0, 3).map((w) => {
        return `${w.id} count=${w.count} 实际=${cnt.get(w.id) || 0}`;
      }).join(", ")}`);
    process.exit(3);
  }
  console.log(`[夹具] 角色 ${CHAR_FIX.characters.length} · 作品 ${CHAR_FIX.works.length}`
    + ` · work_id 与 works.count 自检通过`);
}

/* ⚠️ 夹具里的 `tags` 只有前 8 条 —— 因为 `characters_payload()` 就是这么发的
   （`tags[:8]`，卡片展示够用）。而"编辑特征标签"必须拿到**全量**，
   所以这里额外读一次内置角色库**原文**，当作全量的独立基准。
   不这么做的话，"标签行数 = 全量"只能拿 8 条自证，等于没测。 */
const RAW_CHARS = JSON.parse(fs.readFileSync(
  path.join(PLUGIN, "presets", "anima_v4_characters.json"), "utf8"));
const RAW_BY_TAG = new Map(RAW_CHARS.characters.map((c) => [c.tag, c]));
{
  const more = [...RAW_BY_TAG.values()].filter((c) => (c.tags || []).length > 8);
  if (!more.length) {
    console.error("夹具自检失败：内置角色库里没有一条标签数 > 8 的角色，"
      + "特征标签用例无法验证“全量 vs 载荷”的差异");
    process.exit(3);
  }
}

const { JSDOM } = await import(
  pathToFileURL(path.join("C:/Users/VGBFC/.workbuddy/binaries/node/workspace/node_modules/jsdom/lib/api.js")).href
);

/* ── 1. jsdom 环境 ───────────────────────────────────────────────── */
// ⚠️ 必须挂 virtualConsole：jsdom 里事件处理函数抛的异常会被吞进
//    virtual console，不接出来的话用例只会看到"元素没出现"，
//    完全不知道是代码报错了。
const vc = new (await import(
  pathToFileURL(path.join("C:/Users/VGBFC/.workbuddy/binaries/node/workspace/node_modules/jsdom/lib/api.js")).href
)).VirtualConsole();
vc.on("jsdomError", (e) => console.error("[jsdomError]", e.detail || e));
vc.on("error", (...a) => console.error("[jsdom console.error]", ...a));
const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", {
  pretendToBeVisual: true,
  virtualConsole: vc,
});
global.window = dom.window;
global.document = dom.window.document;
// Node 22 自带只读的 global.navigator（只有 getter），直接赋值会炸，
// 必须用 defineProperty 覆盖。
Object.defineProperty(global, "navigator", {
  value: dom.window.navigator,
  configurable: true,
  writable: true,
});
global.HTMLElement = dom.window.HTMLElement;
global.alert = () => {};
// ⚠️ 插件脚本是在 Node 上下文里跑的（只是 import 了浏览器桩），
//    所以浏览器全局要一个个显式挂上去。FileReader 是 v3.4.0 上传预览图
//    用到的 —— 不挂就是 "FileReader is not defined"，而且它抛在事件回调里，
//    不挂 virtualConsole 的话只会看到"元素没出现"。
global.FileReader = dom.window.FileReader;
global.requestAnimationFrame = (fn) => setTimeout(fn, 0);

/* ── 2. 搭临时目录 + 桩 ─────────────────────────────────────────── */
// 目录结构必须还原浏览器里的 URL 布局：
//   真实运行时插件脚本在  /extensions/<插件名>/xxx.js
//     （ComfyUI 的 WEB_DIRECTORY="./js" 是把 js/ 目录**挂在** extensions 根上的，
//       不会多出一层 js/ —— 这一点踩过一次，写成 js/ 子目录会 404）
//   它 import 的是        ../../scripts/app.js  →  /scripts/app.js
// 所以这里建成 <TMP>/extensions/<插件>/... + <TMP>/scripts/...，还原真实布局。
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "av3ui-"));
const PLUG_DIR = path.join(TMP, "extensions", "Comfyui-Anima-Wardrobe-V4");
fs.mkdirSync(PLUG_DIR, { recursive: true });
fs.mkdirSync(path.join(TMP, "scripts"), { recursive: true });
fs.writeFileSync(path.join(TMP, "package.json"), '{"type":"module"}', "utf8");
fs.copyFileSync(SRC_JS, path.join(PLUG_DIR, "anima_wardrobe_v4_studio.js"));

fs.writeFileSync(path.join(TMP, "scripts", "app.js"), `
export const app = {
  canvas: { },
  graph: { setDirtyCanvas() {} },
  registerExtension(ext) { globalThis.__AV3_EXT = ext; },
};
`, "utf8");

fs.writeFileSync(path.join(TMP, "scripts", "api.js"), `
export const api = {
  fetchApi(url, opts) { return globalThis.__AV3_FETCH(url, opts); },
};
`, "utf8");

/* 记录所有请求，供断言用 */
const CALLS = [];
/* 用户数据的内存桩（命名预设 / 角色收藏）。
   刻意维护**内存状态**、写操作返回"最新完整列表" —— 与真后端契约一致
   （见 __init__.py 里那三条约定）。只回一个固定值的话，
   "保存后列表变了没""收藏后计数涨了没"这类断言就全是空转。 */
const STORE = { presets: {}, favorites: [] };
const countW = (w) => (!w ? 0
  : Object.keys(w.sections || {}).length + Object.keys(w.fields || {}).length
    + Object.values(w.options || {})
        .reduce((n, x) => n + Object.keys(x || {}).length, 0));
const presetList = () => Object.entries(STORE.presets)
  .map(([name, p]) => ({
    name,
    saved_at: p.saved_at || "",
    summary: `${p.level || "—"} · 权重 ${countW(p.weights)} 项`,
    data: Object.fromEntries(
      Object.entries(p).filter(([k]) => k !== "saved_at")),
  }))
  .sort((a, b) => (a.saved_at < b.saved_at ? 1 : -1));

/* 角色覆盖层的内存桩（v3.4.0 角色编辑 + 自定义角色）。
   与真后端同构：基于**夹具**重算，edits 覆盖内置、custom 追加、
   works.count 重算 —— 断言"保存后卡片真的变了"才有意义。 */
const USERCH = { edits: {}, custom: [], next: 1 };
// v3.43.0：场景收藏（桩里用一个数组模拟后端的 user_scene_favorites.json）
const SCENE_FAV = [];
// v3.18.6：内置角色也能删 —— 桩里用 Set 记"已删"，charPayload 过滤掉它们
const REMOVED_CHARS = new Set();
const workIdOf = (en) => (CHAR_FIX.works.find((w) => w.en === en) || {}).id || "";
function charPayload() {
  const chars = CHAR_FIX.characters.filter((c) => !REMOVED_CHARS.has(c.tag))
    .map((c) => ({ ...c, user: false }));
  for (const c of chars) {
    const p = USERCH.edits[c.tag];
    if (p) Object.assign(c, p);
  }
  for (const c of USERCH.custom) {
    chars.push({ ...c, user: true, work_id: workIdOf(c.work) });
  }
  const works = CHAR_FIX.works.map((w) => ({ ...w }));
  const cnt = {};
  for (const c of chars) if (c.work_id) cnt[c.work_id] = (cnt[c.work_id] || 0) + 1;
  for (const w of works) w.count = cnt[w.id] || 0;
  return { available: true, meta: {}, works, characters: chars };
}

globalThis.__AV3_FETCH = async (url, opts) => {
  CALLS.push({ url, opts });
  const body = (u) => ({ ok: true, status: 200, json: async () => u });
  const arg = () => JSON.parse((opts && opts.body) || "{}");
  if (url.endsWith("/pools")) return body(POOLS);
  if (url.endsWith("/contract")) return body(CONTRACT);
  if (url.endsWith("/scenes")) return body(SCENE_FIX);
  // ── v3.43.0：场景收藏（**独立文件**，值域是场景 id，不是角色 tag）──
  // ⚠️ 必须排在 "/scenes" 之前判断吗？不必（endsWith 不会混淆），
  //    但顺序写清楚，避免以后有人把它挪到通用分支后面。
  if (url.endsWith("/scenes/favorites")) return body({ favorites: [...SCENE_FAV] });
  if (url.endsWith("/scenes/favorites/toggle")) {
    const b = arg();
    const sid = String(b.id || "");
    const has = SCENE_FAV.includes(sid);
    const want = (b.on === undefined || b.on === null) ? !has : !!b.on;
    if (!/^sc_[a-z0-9_]+$/.test(sid)) {
      return { ok: false, status: 400, json: async () => ({ error: "场景 id 不合法" }) };
    }
    if (want && !has) SCENE_FAV.push(sid);
    else if (!want && has) SCENE_FAV.splice(SCENE_FAV.indexOf(sid), 1);
    return body({ favorites: [...SCENE_FAV] });
  }
  if (url.endsWith("/characters")) {
    return body(charPayload());
  }
  // ── 角色编辑 / 自定义角色（v3.4.0）──────────────────────────────
  // ⚠️ 顺序：thumb-clear / save / delete / reset 都要排在 "/characters" 与
  //    泛化的 "/thumb/" 之前判（endsWith("/characters") 本身不歧义，但
  //    "/thumb/" 是 includes，得留神）。这里其实都不冲突，仍按具体在前排。
  if (url.endsWith("/characters/save")) {
    const b = arg();
    const f = b.fields || {};
    if (!String(f.trigger || "").trim()) {
      return { ok: false, status: 400, json: async () => ({ error: "角色标签不能为空" }) };
    }
    // 特征标签校验（与真后端同口径：小写英文，单条 ≤40 字符）
    const tagList = Array.isArray(f.tags) ? f.tags : [];
    const badTag = tagList.find((t) => String(t).length > 40
      || !/^[a-z0-9][a-z0-9 _\-:'()./!+]*$/.test(String(t).toLowerCase()));
    if (badTag) {
      return { ok: false, status: 400, json: async () => ({ error: "标签不合法：" + badTag }) };
    }
    if (b.mode === "create") {
      const tag = "user_stub" + (USERCH.next++);
      USERCH.custom.push({
        tag, name: String(f.trigger).split(",")[0].trim(), zh: f.zh || "",
        work: f.work || "", trigger: f.trigger, pop: 0, hair: "", eyes: "",
        tags: tagList.slice(), thumb: tag,
      });
      return body({ ok: true, data: charPayload(), character: { tag } });
    }
    const tag = b.tag;
    const cu = USERCH.custom.find((c) => c.tag === tag);
    if (cu) {
      cu.trigger = f.trigger;
      cu.name = String(f.trigger).split(",")[0].trim();
      cu.zh = f.zh || "";
      cu.work = f.work || "";
      cu.tags = tagList.slice();
    } else {
      const p = { ...(USERCH.edits[tag] || {}), trigger: f.trigger };
      // 留空 = 清除覆盖（与真后端 _norm_overlay 丢空值的语义一致）
      if (f.zh) p.zh = f.zh; else delete p.zh;
      if (f.work) p.work = f.work; else delete p.work;
      if (tagList.length) p.tags = tagList.slice(); else delete p.tags;
      USERCH.edits[tag] = p;
    }
    return body({ ok: true, data: charPayload(), character: { tag } });
  }
  if (url.includes("/characters/detail")) {
    // 单个角色的完整记录 + 内置原始标签（列表载荷只带 tags[:8]，所以必须按需拉）
    const q = decodeURIComponent((url.split("?tag=")[1] || ""));
    const bi = CHAR_FIX.characters.find((c) => c.tag === q);
    const cu = USERCH.custom.find((c) => c.tag === q);
    if (!bi && !cu) {
      return { ok: false, status: 404, json: async () => ({ error: "找不到角色：" + q }) };
    }
    // ⚠️ 全量标签取自**原文**（RAW_BY_TAG），不能用夹具里被截断的 tags[:8]
    const raw = RAW_BY_TAG.get(q);
    const bt = raw ? (raw.tags || []) : [];
    const eff = cu ? { ...cu }
      : { ...bi, tags: bt.slice(), ...(USERCH.edits[q] || {}) };
    return body({
      ok: true, tag: q, user: !!cu,
      trigger: eff.trigger || "", zh: eff.zh || "", work: eff.work || "",
      thumb: eff.thumb || "", hair: eff.hair || "", eyes: eff.eyes || "",
      tags: (eff.tags || []).slice(),
      builtin_tags: bt.slice(),
      tags_overridden: !!(USERCH.edits[q] && "tags" in USERCH.edits[q]),
    });
  }
  if (url.endsWith("/characters/delete")) {
    // v3.18.6：单条（tag）与批量（tags）都支持，且**内置角色也能删**
    const a = arg();
    const want = Array.isArray(a.tags) ? a.tags : [a.tag];
    const deleted = [];
    const failed = [];
    for (const t of want) {
      const i = USERCH.custom.findIndex((c) => c.tag === t);
      if (i >= 0) {
        USERCH.custom.splice(i, 1);
        deleted.push(t);
        continue;
      }
      if (!CHAR_FIX.characters.some((c) => c.tag === t) || REMOVED_CHARS.has(t)) {
        failed.push({ tag: t, error: "找不到这个角色（可能已经被删掉）" });
        continue;
      }
      REMOVED_CHARS.add(t);
      deleted.push(t);
    }
    if (!deleted.length) {
      return { ok: false, status: 400,
               json: async () => ({ error: failed[0]?.error || "删除失败", failed }) };
    }
    return body({ ok: true, data: charPayload(), deleted, failed });
  }
  if (url.endsWith("/characters/reset")) {
    const tag = arg().tag;
    if (USERCH.custom.some((c) => c.tag === tag)) {
      return { ok: false, status: 400, json: async () => ({ error: "这是自定义角色" }) };
    }
    delete USERCH.edits[tag];
    return body({ ok: true, data: charPayload() });
  }
  if (url.endsWith("/characters/thumb-clear")) {
    const tag = arg().tag;
    const cu = USERCH.custom.find((c) => c.tag === tag);
    if (cu) cu.thumb = tag;
    else if (USERCH.edits[tag]) delete USERCH.edits[tag].thumb;
    return body({ ok: true, data: charPayload(), thumb: "user_" + tag });
  }
  if (url.endsWith("/characters/thumb")) {
    const b = arg();
    const tag = b.tag;
    const cu = USERCH.custom.find((c) => c.tag === tag);
    if (cu) cu.thumb = "user_" + tag;
    else USERCH.edits[tag] = { ...(USERCH.edits[tag] || {}), thumb: "user_" + tag };
    return body({ ok: true, data: charPayload(), thumb: "user_" + tag });
  }
  // 用户数据：注意顺序 —— 更具体的子路径先判（虽然 endsWith 本身不歧义）
  if (url.endsWith("/favorites/toggle")) {
    const b = arg();
    const on = b.on === undefined ? !STORE.favorites.includes(b.tag) : !!b.on;
    if (on && !STORE.favorites.includes(b.tag)) STORE.favorites.push(b.tag);
    if (!on) STORE.favorites = STORE.favorites.filter((t) => t !== b.tag);
    return body({ favorites: STORE.favorites });
  }
  if (url.endsWith("/favorites")) return body({ favorites: STORE.favorites });
  if (url.endsWith("/presets/save")) {
    const b = arg();
    if (!String(b.name || "").trim()) {
      return { ok: false, status: 400, json: async () => ({ error: "预设名不能为空" }) };
    }
    STORE.presets[b.name] = { ...(b.data || {}), saved_at: "2026-10-03 16:00:00" };
    return body({ presets: presetList() });
  }
  if (url.endsWith("/presets/delete")) {
    delete STORE.presets[arg().name];
    return body({ presets: presetList() });
  }
  if (url.endsWith("/presets")) return body({ presets: presetList() });
  if (url.includes("/thumb/")) {
    // 刻意回 404：验证面板会退化成首字母色块而不是整片空白
    return { ok: false, status: 404, json: async () => ({}) };
  }
  if (url.endsWith("/roll")) {
    // 与后端同一套语义的**最小**桩：这里只负责"回一个形状正确的响应"，
    // 真正的抽取逻辑由 Python 侧的 check_v3_gate 全套基线保证。
    const req = JSON.parse(opts.body);
    return body({
      text: "1girl, solo, black hair, school uniform, sitting, smile",
      tags: ["1girl", "solo", "black hair", "school uniform", "sitting", "smile"],
      state: { count: "1girl, solo", hair_color: "black hair" },
      level: req.nsfw_level,
      level_label: "0 · 全年龄",
      cn_summary: "单人少女，黑发，JK制服，端坐，微笑",
      dropped: [],
      notes: ["测试桩"],
      report: {
        n: 6, ok_f: 16, total_f: 16, ok_s: 10, total_s: 10,
        real_level: 0, drawn: [],
      },
    });
  }
  return { ok: false, status: 404, json: async () => ({}) };
};

/* ── 3. 载入插件 ─────────────────────────────────────────────────── */
await import(pathToFileURL(path.join(PLUG_DIR, "anima_wardrobe_v4_studio.js")).href);
const EXT = globalThis.__AV3_EXT;
ck("注册扩展成功", !!EXT && EXT.name === "Anima.Wardrobe.V3.Studio");

/* ── 4. 造节点 ───────────────────────────────────────────────────── */
function makeNode() {
  const node = {
    widgets: [],
    __av3Buttons: false,
    addWidget(type, name, value, cb) {
      const w = { type, name, value, callback: cb, serialize: true };
      this.widgets.push(w);
      return w;
    },
  };
  node.widgets.push(
    { type: "combo", name: "nsfw_level", value: "sfw", callback: null },
    { type: "number", name: "seed", value: -1, callback: null },
    { type: "combo", name: "tag_cap", value: "自动", callback: null },
    { type: "number", name: "base_prob", value: 0.65, callback: null },
    { type: "text", name: "disabled_sections", value: "", callback: null },
    { type: "text", name: "lock_fields", value: "", callback: null },
    { type: "text", name: "force_role", value: "", callback: null },
    { type: "text", name: "weights_json", value: "", callback: null },
    { type: "text", name: "extra_body", value: "", callback: null },
    { type: "toggle", name: "appearance_follow", value: true, callback: null },
    { type: "text", name: "selected_roles", value: "", callback: null },
    { type: "toggle", name: "big_breasts", value: false, callback: null },
    { type: "text", name: "role_works", value: "", callback: null },
    // v3.17.0：胸部大小等级（追加末尾；夹具必须与真后端 INPUT_TYPES 同源）
    { type: "combo", name: "breast_size", value: "不指定",
      options: { values: ["不指定", "平胸", "小胸", "中等", "大胸", "巨乳", "爆乳"] },
      callback: null },
    // v3.19.0：服装风格智配（同样追加末尾，与 nodes.py INPUT_TYPES 顺序一致）
    { type: "combo", name: "outfit_style", value: "随机", callback: null },
    // v3.45.0：角色官方发型对齐（追加末尾，与 nodes.py INPUT_TYPES 顺序一致）
    { type: "toggle", name: "hair_follow", value: true, callback: null },
  );
  return node;
}

const nodeType = function () {};
nodeType.prototype = {};
await EXT.beforeRegisterNodeDef(nodeType, { name: "AnimaV4RandomPrompt" });
ck("对非目标节点不生效", await (async () => {
  const other = function () {};
  other.prototype = {};
  await EXT.beforeRegisterNodeDef(other, { name: "Krea2PortraitV12" });
  return !other.prototype.onNodeCreated;
})());

const node = makeNode();
nodeType.prototype.onNodeCreated.call(node);
const btnNames = node.widgets.filter((w) => w.type === "button").map((w) => w.name);
ck("节点挂上 4 个按钮", btnNames.length === 4, JSON.stringify(btnNames));
ck("按钮不进工作流 JSON", node.widgets.filter((w) => w.type === "button")
  .every((w) => w.serialize === false));

/* 控件名与后端 INPUT_TYPES 的一致性 —— 拼错一个字母面板就静默失灵 */
const BACKEND_WIDGETS = [
  "nsfw_level", "seed", "tag_cap", "base_prob", "disabled_sections",
  "lock_fields", "force_role", "weights_json", "extra_body",
  "appearance_follow",
  "selected_roles",
  "big_breasts",
  "role_works",
  "breast_size",
  "outfit_style",
  "role_fav_only",
  "hair_follow",
  "hair_len_pick",
  "hair_tie_pick",
  "hair_curl_pick",
  "hair_acc_pick",
];
const jsSrc = fs.readFileSync(SRC_JS, "utf8");
const used = [...jsSrc.matchAll(/w(?:get|set)\(node,\s*"([^"]+)"/g)].map((m) => m[1]);
const unknown = [...new Set(used)].filter((n) => !BACKEND_WIDGETS.includes(n));
ck("JS 引用的控件名全部存在于节点", unknown.length === 0, JSON.stringify(unknown));

/* 接口 URL 与后端路由的一致性 */
const routes = [...jsSrc.matchAll(/`\/\$\{NS\}\/([a-z-]+)`/g)].map((m) => m[1]);
const pyInit = fs.readFileSync(path.join(PLUGIN, "__init__.py"), "utf8");
// v4.0.0：路由改用 `_dual_get/_dual_post` 动态拼接（同一处理函数镜像到 v4 与 v3），
// 所以字面量 `"/anima-wardrobe-v4/xxx"` 不再出现 —— 三种登记形式都要认。
const badRoutes = [...new Set(routes)].filter((r) =>
  !pyInit.includes(`/${r}\``)
  && !pyInit.includes(`"/anima-wardrobe-v4/${r}"`)
  && !pyInit.includes(`_dual_get("/${r}")`)
  && !pyInit.includes(`_dual_post("/${r}")`));
ck("JS 请求的路由后端都有", badRoutes.length === 0, JSON.stringify(badRoutes));

/* ── 5. 打开面板 ─────────────────────────────────────────────────── */
const openBtn = node.widgets.find((w) => w.name.includes("打开随机面板"));
openBtn.callback();
for (let i = 0; i < 80 && !document.body.querySelector(".av3-panel"); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
const panel = document.body.querySelector(".av3-panel");
ck("面板已打开", !!panel);
if (!panel) {
  console.log("\n[av3_ui_smoke] 面板没打开，后续用例跳过");
  console.log(`通过 ${PASS}，失败 ${FAILS.length}`);
  process.exit(1);
}

ck("请求了 /pools 与 /contract",
  CALLS.some((c) => c.url.endsWith("/pools")) &&
  CALLS.some((c) => c.url.endsWith("/contract")));

const lvBtns = panel.querySelectorAll(".av3-lv button");
ck("档位按钮 = 契约里的档位数", lvBtns.length === CONTRACT.levels.length,
  `${lvBtns.length} vs ${CONTRACT.levels.length}`);
ck("默认选中当前档位（sfw）",
  [...lvBtns].find((b) => b.classList.contains("on"))?.textContent.includes("全年龄"));

const secEls = panel.querySelectorAll(".av3-sec");
ck("段落块 = 词库段数", secEls.length === POOLS.sections.length,
  `${secEls.length} vs ${POOLS.sections.length}`);

let fieldRows = 0;
let weightInputs = 0;
for (const s of POOLS.sections) {
  const el = panel.querySelector(`.av3-sec[data-sec="${s.id}"]`);
  if (!el) continue;
  const rows = el.querySelectorAll(".av3-row");
  fieldRows += rows.length;
  for (const r of rows) if (r.querySelector("input.av3-w")) weightInputs++;
}
const totalFields = POOLS.sections.reduce((n, s) => n + s.fields.length, 0);
// v3.2.0：角色字段从权重页移除了（选择权交给「角色库」页签），
// 所以权重页的行数 = 词库字段数 - 1。这里要**精确**等于，不能只判"少一个"，
// 否则哪天误删了别的字段也测不出来。
const weightPageFields = totalFields - 1;
ck("字段行 = 词库字段数 - 1（角色已移出权重页）",
  fieldRows === weightPageFields, `${fieldRows} vs ${weightPageFields}`);
ck("每个字段都有权重输入框",
  weightInputs === weightPageFields, `${weightInputs} vs ${weightPageFields}`);

// 角色字段确实不在权重页里 —— 这条是上面那个 -1 的正面依据
{
  const roleRow = panel.querySelector('.av3-row[data-key="role"]');
  ck("权重页里没有角色字段行", !roleRow,
    roleRow ? roleRow.outerHTML.slice(0, 80) : "");
  const anyRoleLab = [...panel.querySelectorAll(".av3-row .lab")]
    .some((e) => e.textContent.includes("角色"));
  ck("权重页里没有叫「角色」的字段标签", !anyRoleLab);
}
// 行必须带 data-key：refreshSectionState 靠它对齐 🎯 徽标，
// 用索引对齐的话跳过 role 之后会整体错位一格
ck("每行都有 data-key",
  [...panel.querySelectorAll(".av3-row")].every((r) => !!r.dataset.key),
  [...panel.querySelectorAll(".av3-row")].filter((r) => !r.dataset.key).length + " 行缺 key");

ck("默认展开前三段",
  panel.querySelectorAll(".av3-sec.open").length === 3,
  String(panel.querySelectorAll(".av3-sec.open").length));

/* ── 6. 权重细则弹窗 ─────────────────────────────────────────────── */
const hairSec = panel.querySelector('.av3-sec[data-sec="hair"]');
const colorRow = [...hairSec.querySelectorAll(".av3-row")]
  .find((r) => r.querySelector(".lab")?.textContent === "颜色");
ck("找到「头发 / 颜色」字段行", !!colorRow);
const badge = colorRow.querySelector(".av3-t");
ck("🎯 徽标初始为未调", badge.textContent.trim() === "🎯", badge.textContent);

badge.click();
const mini = document.body.querySelector(".av3-mini");
ck("权重细则弹窗打开", !!mini);
const fieldOpts = POOLS.sections
  .find((s) => s.id === "hair").fields.find((f) => f.key === "hair_color").opts;
const oRows = mini.querySelectorAll(".av3-oRow");
ck("细则里选项数 = 该字段选项数", oRows.length === fieldOpts.length,
  `${oRows.length} vs ${fieldOpts.length}`);

/* 快捷按钮「3」→ 权重 3.0 */
const firstQuick3 = oRows[0].querySelectorAll(".av3-t")[3];
firstQuick3.click();
const firstInput = oRows[0].querySelector("input.av3-w");
ck("快捷按钮写入输入框", firstInput.value === "3", firstInput.value);

/* 应用 → 回写控件 + 徽标变三态之一 */
mini.querySelector(".ft .pri").click();
ck("弹窗关闭", !document.body.querySelector(".av3-mini"));
const wj = node.widgets.find((w) => w.name === "weights_json").value;
let wjParsed = null;
try { wjParsed = JSON.parse(wj); } catch (e) { /* 留 null，下面断言会红 */ }
ck("权重写回 weights_json（结构化核对）",
  !!wjParsed && wjParsed.options?.hair_color?.["black hair"] === 3,
  wj);
ck("🎯 徽标变成「调过」", badge.textContent.trim().startsWith("🎯 ")
  || badge.textContent.trim() === "🎯 全部", badge.textContent);

/* ── 7. 清空权重 ─────────────────────────────────────────────────── */
const clearBtn = [...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("清空权重"));
clearBtn.click();
ck("清空后控件为空串",
  node.widgets.find((w) => w.name === "weights_json").value === "");

/* ── 8. 段权重 0 → 写进 disabled_sections（采用时才写） ─────────── */
const sceneSec = panel.querySelector('.av3-sec[data-sec="scene"]');
const sceneW = sceneSec.querySelector(".hd input.av3-w");
sceneW.value = "0";
sceneW.dispatchEvent(new dom.window.Event("input"));
ck("段权重 0 时该段置灰", sceneSec.classList.contains("off"));

/* ── 8.5 段「本档不参与」的判据（v3.8.0 修）───────────────────────
   判据必须是「段内**还有没有** ≤ 当前档的选项」，不能是「段最高档 ≤ 当前档」：
   后者在段内混入分档词条后会误标 —— v3.8.0 给「视角」加了 `pov crotch`(L2)、
   `pov, fellatio`(L3) 之后，⑧镜头段的最高档被抬到 3，全年龄档就会被打上
   「本档不参与」，而该段 16 条全年龄词条照样在抽。 */
const secTitle = (id) => panel.querySelector(`.av3-sec[data-sec="${id}"] .hd .t`).textContent;
const labeled = (id) => secTitle(id).includes("本档不参与");
ck("⑧镜头 在全年龄档不被误标（段内仍有全年龄视角词条）", !labeled("camera"), secTitle("camera"));
ck("④身材与肤质 在全年龄档不被误标", !labeled("body"), secTitle("body"));
ck("🔞服装状态 在全年龄档仍标为不参与", labeled("cloth_nsfw"), secTitle("cloth_nsfw"));
// ⚠️ v3.9.0 起法典段的判据变了：场景搭配库里有 L0 的 SFW 预设，
//    所以全年龄档下该段**有活可干** —— 不再标「本档不参与」。
ck("🎬法典/场景段 在全年龄档参与（有 L0 场景搭配）",
  !labeled("canon"), secTitle("canon"));

/* ── 9. 全部随机（预演） ─────────────────────────────────────────── */
const rollBtn = [...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("全部随机"));
rollBtn.click();
for (let i = 0; i < 80 && !(panel.querySelector(".av3-out")?.textContent || "")
  .includes("school uniform"); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
const outTxt = panel.querySelector(".av3-out").textContent;
ck("结果渲染到输出区", outTxt.includes("school uniform"), outTxt.slice(0, 60));
ck("中文摘要渲染", panel.querySelector(".av3-sum").textContent.includes("单人少女"));
ck("自检行渲染", /自检/.test(panel.querySelector(".av3-sc").textContent));

const rollCall = CALLS.filter((c) => c.url.endsWith("/roll")).pop();
const sent = JSON.parse(rollCall.opts.body);
ck("请求带了档位", sent.nsfw_level === "sfw", sent.nsfw_level);
ck("请求带了关闭的段", sent.disabled_sections === "scene", sent.disabled_sections);
ck("请求带了外貌对齐开关", sent.appearance_follow === true);
ck("请求带了发型对齐开关", sent.hair_follow === true);

/* ── 9.5 预演必须带上「已选角色」与「锁定字段」（v3.8.0 修）──────────
   修之前这两个没发 → 选了角色点「全部随机」看到的预览是全库随机抽的，
   而真正跑工作流按 selected_roles 走 —— 预览与实跑对不上，
   与「面板与工作流共用同一套引擎」的承诺直接矛盾。 */
const rollCalls = () => CALLS.filter((c) => c.url.endsWith("/roll"));
const nRoll = rollCalls().length;
node.widgets.find((w) => w.name === "selected_roles").value = "hatsune_miku";
node.widgets.find((w) => w.name === "lock_fields").value = "place";
rollBtn.click();
for (let i = 0; i < 80 && rollCalls().length === nRoll; i++) {
  await new Promise((r) => setTimeout(r, 10));
}
const sent2 = JSON.parse(rollCalls().pop().opts.body);
ck("预演请求带上已选角色（修：预演 ≠ 实跑）",
  sent2.selected_roles === "hatsune_miku", String(sent2.selected_roles));
ck("预演请求带上锁定字段",
  sent2.lock_fields === "place", String(sent2.lock_fields));
node.widgets.find((w) => w.name === "selected_roles").value = "";
node.widgets.find((w) => w.name === "lock_fields").value = "";

/* ── 10. 采用这条 → 写回 seed ───────────────────────────────────── */
const before = node.widgets.find((w) => w.name === "seed").value;
const adopt = [...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("采用这条"));
adopt.click();
const after = node.widgets.find((w) => w.name === "seed").value;
ck("采用后 seed 被写回", after !== before && after >= 0, `${before} → ${after}`);
ck("采用后档位写回 nsfw_level",
  node.widgets.find((w) => w.name === "nsfw_level").value === "sfw");
ck("采用后 disabled_sections 写回",
  node.widgets.find((w) => w.name === "disabled_sections").value === "scene");


/* ── 10.5 角色库页签 ────────────────────────────────────────────── */
const tabBtns = [...panel.querySelectorAll(".av3-tabs button")];
ck("有四个页签（词库权重 / 角色库 / 🎬 场景搭配 / 🔍 特写搭配）",
  tabBtns.length === 4, tabBtns.map((b) => b.textContent).join("/"));
ck("场景搭配是独立页签", tabBtns[2].textContent.includes("场景搭配"),
  tabBtns[2].textContent);
ck("特写搭配是独立页签（v3.18.0，与场景搭配分开）",
  tabBtns[3].textContent.includes("特写搭配"), tabBtns[3].textContent);
ck("默认在词库页", tabBtns[0].classList.contains("on")
  && panel.querySelectorAll(".av3-sec").length > 0);

tabBtns[1].click();               // 切到角色库
for (let i = 0; i < 100 && !panel.querySelector(".av3-card"); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("切页后请求了 /characters", CALLS.some((c) => c.url.endsWith("/characters")));
ck("权重树已让位（左列不再有段落块）",
  panel.querySelectorAll(".av3-sec").length === 0);

// ⚠️ 作品行会随每次 renderChars() 重建，所以这里用**函数**查而不是缓存数组，
//    否则后续点击会操作到已经脱离文档的旧节点。
const workRows = () => [...panel.querySelectorAll(".av3-work")];
const rowOf = (label) =>
  workRows().find((r) => r.querySelector(".n").textContent === label);
const workLabel = (w) => w.zh || w.en;

// 作品列表 = 「全部作品」+ 「⭐ 我的收藏」+ 每个作品一行
ck("作品列表 = 作品数 + 2（「全部作品」+「我的收藏」）",
  workRows().length === CHAR_FIX.works.length + 2, String(workRows().length));
ck("「⭐ 我的收藏」紧跟在「全部作品」后面",
  workRows()[1].querySelector(".n").textContent.includes("我的收藏"),
  workRows()[1].querySelector(".n").textContent);
ck("收藏为 0 时该行置灰", workRows()[1].classList.contains("empty"));
ck("作品显示中文名", !!rowOf(workLabel(CHAR_FIX.works[0])),
  workLabel(CHAR_FIX.works[0]));
ck("保底作品带 ★ 标记",
  workRows().filter((r) => r.classList.contains("tgt")).length
  === CHAR_FIX.works.filter((w) => w.target).length);

const cards = () => [...panel.querySelectorAll(".av3-card")];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PAGE = 96;   // 面板分页渲染上限（与 ui.charLimit 初值一致）
ck("角色卡片 = 首页分页数（不是把 2687 条一次塞进 DOM）",
  cards().length === Math.min(PAGE, CHAR_FIX.characters.length),
  `${cards().length} / 总 ${CHAR_FIX.characters.length}`);

// 默认按人气降序：期望值从夹具现算，不硬编码名字 ——
// 硬编码的断言会随数据变动而红，那种红没有信息量。
const top = [...CHAR_FIX.characters].sort((a, b) => b.pop - a.pop)[0];
ck("默认按人气排行（第一位是人气最高的）",
  cards()[0].querySelector(".nm").textContent === (top.zh || top.name),
  `${cards()[0].querySelector(".nm").textContent} vs ${top.zh || top.name}`);
ck("卡片带 dataset.tag（测试定位用）", cards()[0].dataset.tag === top.tag,
  cards()[0].dataset.tag || "(空)");
ck("卡片显示中文名 + 英文名",
  cards()[0].querySelector(".en").textContent === top.name,
  cards()[0].querySelector(".en").textContent);
ck("卡片显示人气值", !!cards()[0].querySelector(".pp").textContent);

// 缩略图加载失败 → 应退化成首字母色块，而不是留一个破图。
// ⚠️ jsdom 默认不加载图片，onerror 永远不会自己触发，
//    所以这里**手工派发 error 事件** —— 测的是我们自己的降级逻辑，
//    不是 jsdom 的加载器。
const phImgs = [...panel.querySelectorAll(".av3-card img.ph")];
phImgs.forEach((im) => im.dispatchEvent(new dom.window.Event("error")));
ck("缩略图加载失败时退化成首字母色块",
  panel.querySelectorAll(".av3-card .ph.letter").length === phImgs.length
  && panel.querySelectorAll(".av3-card img.ph").length === 0,
  `色块 ${panel.querySelectorAll(".av3-card .ph.letter").length} / 破图 ${panel.querySelectorAll(".av3-card img.ph").length}`);
ck("色块用角色名首字",
  [...panel.querySelectorAll(".av3-card .ph.letter")]
    .map((e) => e.textContent).join("").includes((top.zh || top.name).slice(0, 1)),
  [...panel.querySelectorAll(".av3-card .ph.letter")].map((e) => e.textContent).join(""));

// ── 点 IP 作品筛选 ────────────────────────────────────────────────
// ★ 这一条就是线上 bug 的回归用例。
//   期望值取自 **works[].count**（后端算的），实际值取前端按 work_id 筛出的
//   卡片数 —— 两边来源不同，所以能真正验证一致性。
//   用错字段（`c.work`，那是作品英文名）时列表为空，这里会得到 0。
const zzz = CHAR_FIX.works.find((w) => w.id === "zenless_zone_zero");
rowOf(workLabel(zzz)).click();
ck(`点「${workLabel(zzz)}」→ 卡片数 == works.count（${zzz.count}）`,
  cards().length === Math.min(PAGE, zzz.count),
  `${cards().length}（应为 ${Math.min(PAGE, zzz.count)}；字段用错时是 0）`);
ck("点作品后列表非空（不是「没有匹配的角色」）",
  cards().length > 0
  && !panel.querySelector(".av3-grid .av3-empty"),
  panel.querySelector(".av3-grid .av3-empty")?.textContent || "");
ck("作品行高亮", rowOf(workLabel(zzz)).classList.contains("on"));

// 再拿一个「角色数 < 分页上限」的作品做**精确**数量断言，不被分页掩盖
const small = CHAR_FIX.works
  .filter((w) => w.count >= 3 && w.count <= PAGE - 1)
  .sort((a, b) => b.count - a.count)[0];
rowOf(workLabel(small)).click();
ck(`点「${workLabel(small)}」→ 卡片数精确 == count（${small.count}）`,
  cards().length === small.count, `${cards().length} vs ${small.count}`);
ck("切换作品后卡片确实换了（不是残留上一批）",
  cards().every((c) => {
    const rec = CHAR_FIX.characters.find((x) => x.tag === c.dataset.tag);
    return rec && rec.work_id === small.id;
  }));

// 回全部 + 搜索
rowOf("全部作品").click();
const searchIn = panel.querySelector(".av3-charbar input[type=text]");
const typeSearch = (v) => {
  searchIn.value = v;
  searchIn.dispatchEvent(new dom.window.Event("input"));
};

typeSearch(top.zh || top.name);
ck(`关键词搜索命中中文名（${top.zh || top.name}）`,
  cards().length >= 1 && cards().some((c) => c.dataset.tag === top.tag),
  String(cards().length));

// work_id 也在搜索串里 —— 从别处粘 slug 进来也能搜到
typeSearch(zzz.id);
ck(`关键词能搜到 work_id（${zzz.id}）`,
  cards().length === Math.min(PAGE, zzz.count), String(cards().length));

typeSearch("");

// ── 选中角色 ──────────────────────────────────────────────────────
// ⚠️ 不再按中文名找卡片：真实数据里那几位未必落在首页，
//    硬编码名字的用例会随数据变动而红。
//    改成「筛到一个小作品，然后点前几张卡片」。
const roleWidget = () => node.widgets.find((w) => w.name === "selected_roles").value;
const cardOf = (tag) => cards().find((c) => c.dataset.tag === tag);

const pickWork = CHAR_FIX.works
  .filter((w) => w.count >= 3 && w.count <= 40)
  .sort((a, b) => b.count - a.count)[0];
rowOf(workLabel(pickWork)).click();
ck("小作品下至少有三张卡片可选", cards().length >= 3, String(cards().length));
const t0 = cards()[0].dataset.tag;
const t1 = cards()[1].dataset.tag;
const t2 = cards()[2].dataset.tag;

cardOf(t0).click();
ck("点卡片写入 selected_roles", roleWidget() === t0, roleWidget());
ck("选中卡片高亮 + 打勾",
  cardOf(t0).classList.contains("on") && !!cardOf(t0).querySelector(".tick"));
ck("chips 显示已选角色", panel.querySelectorAll(".av3-chip").length === 1);
ck("人数预览 = 1girl solo（当前档位 sfw）",
  panel.querySelector(".av3-chips").textContent.includes("1girl, solo"),
  panel.querySelector(".av3-chips").textContent);

// 两位（双女）
cardOf(t1).click();
ck("两位角色写入两个 tag（| 分隔）",
  roleWidget() === `${t0}|${t1}`, roleWidget());
ck("两位 + 全年龄档 → 预览 2girls, multiple girls（不用 yuri）",
  panel.querySelector(".av3-chips").textContent.includes("2girls, multiple girls"),
  panel.querySelector(".av3-chips").textContent);

// 再点一次取消
cardOf(t1).click();
ck("再点一次取消选中", roleWidget() === t0, roleWidget());
cardOf(t1).click();

// 三位 → 群像
cardOf(t2).click();
ck("三位 → 预览 multiple girls（多人群像）",
  panel.querySelector(".av3-chips").textContent.includes("multiple girls"),
  panel.querySelector(".av3-chips").textContent);

// 切档位后预览要跟着变。
// ⚠️ 切档位会重建整个角色库页，卡片元素全部换新 ——
//    所以这里必须用 cardOf(tag) 重新查，不能留着旧引用点。
[...panel.querySelectorAll(".av3-lv button")].find((b) => b.textContent.includes("过激"))
  .click();
ck("切到过激档：3 位仍是群像",
  panel.querySelector(".av3-chips").textContent.includes("multiple girls"));
cardOf(t2).click();               // 退回 2 位
ck("2 位 + 过激档 → 预览 2girls, yuri",
  panel.querySelector(".av3-chips").textContent.includes("2girls, yuri"),
  panel.querySelector(".av3-chips").textContent);
[...panel.querySelectorAll(".av3-lv button")].find((b) => b.textContent.includes("全年龄"))
  .click();
ck("切回全年龄档 → 预览回到 2girls, multiple girls",
  panel.querySelector(".av3-chips").textContent.includes("2girls, multiple girls"),
  panel.querySelector(".av3-chips").textContent);
ck("切档位不会把角色库页顶掉", panel.querySelectorAll(".av3-card").length > 0);

// 清除
[...panel.querySelectorAll(".av3-btn")].find((b) => b.textContent.includes("清除已选角色"))
  .click();
ck("一键清除已选角色", roleWidget() === "", JSON.stringify(roleWidget()));
ck("清除后 chips 清空", panel.querySelectorAll(".av3-chip").length === 0);

/* ── 10.5.5 🎲 按当前筛选（作品 IP）随机抽角色（v3.8.0）──────────── */
// 候选池 = 当前的「作品筛选 + 关键词」结果，所以先用一个已知作品做精确断言。
rowOf(workLabel(small)).click();
const poolTags = new Set(cards().map((c) => c.dataset.tag));
const rndN = panel.querySelector(".av3-charbar input[type=number]");
const rndBtn = [...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("随机抽"));
ck("角色库页有 🎲 随机抽按钮", !!rndBtn);
ck("抽取位数输入框默认 1", !!rndN && rndN.value === "1", rndN && rndN.value);

const setN = (v) => {
  rndN.value = String(v);
  rndN.dispatchEvent(new dom.window.Event("change"));
};
setN(2);
rndBtn.click();
const picked = String(roleWidget()).split("|").filter(Boolean);
ck("🎲 一次抽 2 位", picked.length === 2, JSON.stringify(picked));
ck("抽到的角色全部来自当前筛选池",
  picked.every((t) => poolTags.has(t)), JSON.stringify(picked));
ck("抽到的角色互不重复", new Set(picked).size === picked.length);
ck("抽完 chips 同步为 2 位", panel.querySelectorAll(".av3-chip").length === 2);
ck("抽完卡片同步打勾",
  picked.every((t) => cardOf(t) && cardOf(t).classList.contains("on")));

// 追加语义（与手动点卡片一致）：再抽不会把已有的顶掉
setN(1);
rndBtn.click();
const picked3 = String(roleWidget()).split("|").filter(Boolean);
ck("🎲 是追加而不是替换",
  picked3.length === 3 && picked.every((t) => picked3.includes(t)),
  JSON.stringify(picked3));

// 池子被抽空 / 空结果时给提示而不是抛异常
// ⚠️ 状态条不是页面里唯一的 .av3-meta（左列提示、结果区都有），
//    所以限定在右列并"任一命中"来断言，别用全局 querySelector 抓第一个。
const statusText = () => [...panel.querySelectorAll(".av3-right .av3-meta")]
  .map((e) => e.textContent).join(" | ");
const clearBtn2 = [...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("清除已选角色"));
clearBtn2.click();
typeSearch("zzz_no_such_character_zzz");
rndBtn.click();
ck("空池子时只给提示、不写控件", roleWidget() === "", roleWidget());
ck("空池子提示出现在状态条", /没有角色可抽/.test(statusText()),
  statusText().slice(0, 80));
typeSearch("");
rowOf("全部作品").click();

/* ── 10.5.6 🔁 随机池（role_works · 每次自动换人，v3.10.0）───────── */
const rw = () => node.widgets.find((w) => w.name === "role_works").value;
const poolChips = () => [...panel.querySelectorAll("[data-pool]")];
const poolBtn = (t) => [...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes(t));

ck("随机池区默认显示「未限定」",
  panel.querySelector(".av3-chips").parentElement
  && [...panel.querySelectorAll(".av3-meta")]
    .some((e) => e.textContent.includes("（未限定）")),
  String(rw()));

// 选一个作品再加进池子
rowOf(workLabel(small)).click();
poolBtn("＋ 加入随机池").click();
ck("加入随机池 → 写到 role_works 控件", rw() === small.id, rw());
ck("随机池出现该作品的 chip",
  poolChips().length === 1 && poolChips()[0].dataset.pool === small.id,
  String(poolChips().length));

// 重复加入不叠加
poolBtn("＋ 加入随机池").click();
ck("重复加入不会产生第二条", poolChips().length === 1, String(poolChips().length));

// 再加一个作品 → 两个用 | 连接
rowOf(workLabel(zzz)).click();
poolBtn("＋ 加入随机池").click();
ck("多作品用 | 连接",
  rw() === `${small.id}|${zzz.id}`, rw());
ck("chips 同步为 2 条", poolChips().length === 2, String(poolChips().length));

// 「全部作品」不是有效 IP —— 不该被加进去
rowOf("全部作品").click();
poolBtn("＋ 加入随机池").click();
ck("「全部作品」不能被加进随机池（不是 IP）", poolChips().length === 2, rw());

// 已选角色存在时要给出「已选角色优先」的警告
cardOf(cards()[0].dataset.tag).click();
ck("有已选角色时提示「已选角色优先」",
  [...panel.querySelectorAll(".av3-meta")]
    .some((e) => e.textContent.includes("已选角色优先")),
  panel.querySelector(".av3-chips").textContent);
[...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("清除已选角色")).click();

// 单个 chip 的 × 移除
poolChips()[0].querySelector("b").click();
ck("点 chip 的 × 移除该作品", rw() === zzz.id, rw());
ck("移除后 chips 只剩 1 条", poolChips().length === 1);

// 预演请求要带上随机池
const nRoll3 = CALLS.filter((c) => c.url.endsWith("/roll")).length;
rollBtn.click();
for (let i = 0; i < 80
     && CALLS.filter((c) => c.url.endsWith("/roll")).length === nRoll3; i++) {
  await new Promise((r) => setTimeout(r, 10));
}
const sent3 = JSON.parse(CALLS.filter((c) => c.url.endsWith("/roll")).pop().opts.body);
ck("预演请求带上随机池（role_works）",
  sent3.role_works === zzz.id, String(sent3.role_works));

// 清空
poolBtn("清空随机池").click();
ck("清空随机池 → 控件为空串", rw() === "", rw());
ck("清空后 chips 归零", poolChips().length === 0);

/* ── 10.5b 多选批量删除（v3.18.6，内置角色也能删）──────────────── */
const selRaw = () => String(node.widgets.find((w) => w.name === "selected_roles").value || "");
const selBefore = selRaw();
const multiBtn = [...panel.querySelectorAll(".av3-btn")]
  .find((b) => (b.textContent || "").includes("多选"));
ck("角色库页有「☑ 多选」按钮", !!multiBtn, multiBtn?.textContent || "");
multiBtn.click();
await sleep(40);
ck("多选模式出现「删除所选」按钮", !!panel.querySelector("#av3-chars-delall"),
  panel.querySelector("#av3-chars-delall")?.textContent || "");
ck("未勾选时删除按钮禁用",
  panel.querySelector("#av3-chars-delall").disabled === true);
const nBeforeDel = cards().length;
const pickTags = [cards()[0].dataset.tag, cards()[1].dataset.tag];
cards()[0].click();
cards()[1].click();
await sleep(50);
ck("勾选不写入 selected_roles（删角色不该顺手改提示词）",
  selRaw() === selBefore, selRaw());
ck("勾选 2 个后按钮计数为 2",
  /（2）/.test(panel.querySelector("#av3-chars-delall").textContent),
  panel.querySelector("#av3-chars-delall").textContent);
ck("被勾选的卡片带蓝色对勾",
  panel.querySelectorAll(".av3-card .pick").length === 2,
  String(panel.querySelectorAll(".av3-card .pick").length));
panel.querySelector("#av3-chars-delall").click();       // 第一步：进入确认态
ck("第一步只进入确认态，不删",
  /再点一次/.test(panel.querySelector("#av3-chars-delall").textContent),
  panel.querySelector("#av3-chars-delall").textContent);
ck("确认态下卡片数未变", cards().length === nBeforeDel, String(cards().length));
panel.querySelector("#av3-chars-delall").click();       // 第二步：真删
await sleep(80);
// ⚠️ 不能断言"卡片数减 2"：角色库默认只渲染前 96 张（ui.charLimit），
//    总数远大于 96 时删两个仍然是 96 张。改成断言"被删的确实不在了"+"状态条报数"。
ck("批量删除后状态条报告删除数量",
  /已删除 2 个/.test(panel.querySelector("#av3-status")?.textContent || ""),
  panel.querySelector("#av3-status")?.textContent || "");
ck("被删的角色确实消失了",
  pickTags.every((t) => !cards().some((c) => c.dataset.tag === t)),
  pickTags.join("/"));
ck("删除后多选自动关闭", !panel.querySelector("#av3-chars-delall"));
ck("删除后 selected_roles 仍未被改动", selRaw() === selBefore, selRaw());

/* ── 10.6 收藏（⭐）────────────────────────────────────────────── */
const starOf = (tag) => cards().find((c) => c.dataset.tag === tag)
  ?.querySelector(".fav");
const favRow = () => workRows()[1];
const favN = () => Number(favRow().querySelector(".c").textContent);

rowOf("全部作品").click();
const ftag = cards()[0].dataset.tag;
ck("卡片右上角有收藏星（默认 ☆）", starOf(ftag)?.textContent === "☆",
  starOf(ftag)?.textContent || "（没有 .fav 元素）");
ck("人气徽标不再占右上角（改到名字右边）",
  !!cards()[0].querySelector(".nmRow .pp"), "");
ck("还没有收藏时「我的收藏」行置灰、计数为 0",
  favRow().classList.contains("empty") && favN() === 0, String(favN()));

const roleBefore = roleWidget();
starOf(ftag).click();
for (let i = 0; i < 60 && !starOf(ftag).classList.contains("on"); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("点 ☆ → 变 ★ 且带 on 类",
  starOf(ftag).textContent === "★" && starOf(ftag).classList.contains("on"),
  starOf(ftag).textContent);
ck("收藏计数实时更新", favN() === 1, String(favN()));
ck("收藏不会顺带把角色选中（stopPropagation 生效）",
  roleWidget() === roleBefore, `${roleWidget()} vs ${roleBefore}`);
ck("有收藏后该行不再置灰", !favRow().classList.contains("empty"));

rowOf("⭐ 我的收藏").click();
ck("点「我的收藏」→ 只显示已收藏的角色", cards().length === 1,
  String(cards().length));
ck("收藏视图里就是刚收藏的那位", cards()[0]?.dataset.tag === ftag,
  cards()[0]?.dataset.tag || "");
ck("收藏视图里星标仍是 ★（列表与收藏视图状态一致）",
  starOf(ftag)?.classList.contains("on"));

starOf(ftag).click();
for (let i = 0; i < 60 && favN() !== 0; i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("取消收藏后计数归零", favN() === 0, String(favN()));
ck("取消后该行重新置灰", favRow().classList.contains("empty"));
ck("收藏为空时给出明确空状态",
  (panel.querySelector(".av3-grid .av3-empty")?.textContent || "")
    .includes("还没有收藏"),
  panel.querySelector(".av3-grid .av3-empty")?.textContent?.slice(0, 24) || "");
rowOf("全部作品").click();

// 切回词库页
tabBtns[0].click();
ck("切回词库页恢复权重树", panel.querySelectorAll(".av3-sec").length > 0
  && panel.querySelectorAll(".av3-card").length === 0);

/* ── 10.7 预设 ─────────────────────────────────────────────────── */
const preBox = () => [...panel.querySelectorAll(".av3-box")]
  .find((b) => (b.querySelector("h4") || {}).textContent === "预设");
const preSel = () => preBox().querySelector("select");
const preNameIn = () => preBox().querySelector("input[type=text]");
const preBtn = (t) => [...preBox().querySelectorAll("button")]
  .find((b) => b.textContent.includes(t));
const lvBtn = (t) => [...panel.querySelectorAll(".av3-lv button")]
  .find((b) => b.textContent.includes(t));

ck("设置区下方有「预设」小节", !!preBox());
ck("没有预设时下拉禁用并提示「还没有预设」",
  preSel().disabled
  && (preSel().options[0].textContent || "").includes("还没有预设"),
  preSel().options[0]?.textContent || "");

// 先改出一套配置：档位 → 过激，第一个字段权重 → 2.5
lvBtn("过激").click();
const wInput = panel.querySelector(".av3-row input.av3-w");
const wKey = wInput.closest(".av3-row").dataset.key;
wInput.value = "2.5";
wInput.dispatchEvent(new dom.window.Event("input"));

preNameIn().value = "我的常用";
preNameIn().dispatchEvent(new dom.window.Event("input"));
preBtn("保存当前配置").click();
for (let i = 0; i < 60 && preSel().disabled; i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("保存后下拉里出现该预设",
  [...preSel().options].some((o) => o.value === "我的常用"),
  [...preSel().options].map((o) => o.value).join("/"));
ck("下拉文案带摘要（看得出存了什么）",
  (preSel().options[0].textContent || "").includes("过激"),
  preSel().options[0]?.textContent || "");
ck("保存后清空名称输入框", preNameIn().value === "", preNameIn().value);

// 把配置改走，再一键应用回来
lvBtn("全年龄").click();
const wInput2 = panel.querySelector(".av3-row input.av3-w");
wInput2.value = "0.5";
wInput2.dispatchEvent(new dom.window.Event("input"));
ck("改走之后档位确实变了",
  node.widgets.find((w) => w.name === "nsfw_level").value === "sfw",
  String(node.widgets.find((w) => w.name === "nsfw_level").value));

preBtn("📥 应用").click();
for (let i = 0; i < 60 && preSel().disabled; i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("应用预设 → 档位恢复",
  node.widgets.find((w) => w.name === "nsfw_level").value === "hardcore",
  String(node.widgets.find((w) => w.name === "nsfw_level").value));
let wj2 = {};
try {
  wj2 = JSON.parse(node.widgets.find((w) => w.name === "weights_json").value || "{}");
} catch (e) { /* 留空，下面断言会红 */ }
ck("应用预设 → 权重恢复", Number(wj2.fields?.[wKey]) === 2.5,
  JSON.stringify(wj2.fields || {}));
ck("应用预设 → 档位按钮的选中态也跟着变",
  lvBtn("过激").classList.contains("on"));

// 删除（两步确认，不用 window.confirm —— jsdom 里没实现）
preBtn("删除").click();
ck("删除是两步确认（第一次点只改文案）", !preBtn("删除"),
  preBtn("删除")?.textContent || "");
preBtn("再点一次").click();
for (let i = 0; i < 60 && !preSel().disabled; i++) {
  await new Promise((r) => setTimeout(r, 10));
}
// ⚠️ 额外等一拍：删除是写操作，要确认**在途的 GET 不会把它变回来**
//    （loadPresets 的响应可能更晚到，带的是删除前的快照）。
//    没有 presetsSeq 防作废时，这条会红。
await new Promise((r) => setTimeout(r, 120));
ck("删除后回到「还没有预设」状态", preSel().disabled,
  preSel().options[0]?.textContent || "");
ck("删除后下拉里不残留旧条目",
  ![...preSel().options].some((o) => o.value === "我的常用"),
  [...preSel().options].map((o) => o.value).join("/"));

/* ── 10.8 免责声明 ─────────────────────────────────────────────── */
const discEntry = [...panel.querySelectorAll(".av3-head button")]
  .find((b) => b.textContent.includes("免责声明"));
ck("面板头部有免责声明入口", !!discEntry);
discEntry.click();
const disc = [...document.body.querySelectorAll(".av3-disc")].pop();
ck("点开后弹出免责声明", !!disc);
const dTxt = disc ? disc.textContent : "";
ck("含开头说明（开源 / 本机生成 / 不联网）",
  dTxt.includes("本插件为开源插件")
  && dTxt.includes("生成过程全部在你本机完成，不联网、不上传任何内容"),
  dTxt.slice(0, 36));
ck("含年龄硬约束", dTxt.includes("十八岁以下禁止使用")
  && dTxt.includes("18 岁以上虚构人物"));
ck("含插件作者署名", dTxt.includes("插件作者：灵冻不冻"));
ck("含源脚本作者署名（飞蓬）",
  dTxt.includes("ANIMA提示词生成器.html") && dTxt.includes("飞蓬"));
ck("含全部 5 条条款",
  ["①", "②", "③", "④", "⑤"].every((n) => dTxt.includes(n)),
  ["①", "②", "③", "④", "⑤"].filter((n) => !dTxt.includes(n)).join(""));
disc.querySelector(".ft button").click();
ck("点「我已阅读」关闭弹窗", !document.body.querySelector(".av3-disc"));

/* ── 10.9 胸部大小等级（v3.17.0，取代巨乳开关；面板最底部）──────── */
const footEl = panel.querySelector(".av3-foot");
ck("面板最底部有独立底部条", !!footEl, panel.lastElementChild?.className);
/* v3.19.0：底部条变成两条（胸部大小 + 服装风格），
   断言改成"最后一个子元素仍是底部条"，而不是"必须是胸部那条"。 */
ck("底部条确实是面板的最后一个子元素（不会被两列滚走）",
  !!panel.lastElementChild?.classList?.contains("av3-foot"),
  panel.lastElementChild?.className);
const footEls = panel.querySelectorAll(".av3-foot");
ck("底部条共两条（胸部大小 + 服装风格）", footEls.length === 2, String(footEls.length));
const osFoot = footEls[1];
const osSel2 = osFoot.querySelector("select");
ck("第二条底部条里有服装风格下拉", !!osSel2);
ck("标签写着「服装风格」", osFoot.textContent.includes("服装风格"));
ck("十八个选项（随机/不限 + 十六个风格）",
  osSel2.options.length === 18 &&
  [...osSel2.options].map((o) => o.value).join("|")
    === "随机|不限|学院|职场|传统|运动|日常|居家|夜店|奇幻|泳装|哥特|洛丽塔|朋克|战术风|暗黑少女|辣妹|女仆",
  [...osSel2.options].map((o) => o.value).join("|"));
{ /* 改动下拉必须真的写进节点控件 */
  const osWidget = () => node.widgets.find((w) => w.name === "outfit_style").value;
  osSel2.value = "夜店";
  osSel2.dispatchEvent(new dom.window.Event("change"));
  ck("切换服装风格写进节点控件 outfit_style", osWidget() === "夜店", String(osWidget()));
  osSel2.value = "随机";
  osSel2.dispatchEvent(new dom.window.Event("change"));
}
const bsSel = footEl.querySelector("select");
ck("底部条里是胸部大小下拉", !!bsSel);
ck("标签写着「胸部大小」", footEl.textContent.includes("胸部大小"));
ck("七个选项（不指定 + 六档）",
  bsSel.options.length === 7 &&
  [...bsSel.options].map((o) => o.value).join("|")
    === "不指定|平胸|小胸|中等|大胸|巨乳|爆乳",
  [...bsSel.options].map((o) => o.value).join("|"));
ck("默认「不指定」", bsSel.value === "不指定", String(bsSel.value));
ck("带说明文字（写明覆盖什么）",
  footEl.textContent.includes("覆盖外貌对齐与权重"), footEl.textContent.slice(0, 60));

bsSel.value = "巨乳";
bsSel.dispatchEvent(new dom.window.Event("change"));
const bsWidget = () => node.widgets.find((w) => w.name === "breast_size").value;
ck("选择后写回节点控件 breast_size", bsWidget() === "巨乳", String(bsWidget()));

// 抽取请求要带上它 —— 否则面板预演与真机结果会不一致
CALLS.length = 0;
[...panel.querySelectorAll(".av3-btn")].find((b) => b.textContent.includes("全部随机"))
  .click();
for (let i = 0; i < 60 && !CALLS.some((c) => c.url.endsWith("/roll")); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
const bbRollCall = CALLS.filter((c) => c.url.endsWith("/roll")).pop();
let bbRollBody = {};
try { bbRollBody = JSON.parse(bbRollCall.opts.body); } catch (e) { /* 留空，断言会红 */ }
ck("抽取请求带上 breast_size = 巨乳", bbRollBody.breast_size === "巨乳",
  JSON.stringify(bbRollBody.breast_size));
ck("旧字段 big_breasts 不再出现在预演请求里", !("big_breasts" in bbRollBody),
  JSON.stringify(Object.keys(bbRollBody)));

bsSel.value = "不指定";
bsSel.dispatchEvent(new dom.window.Event("change"));
ck("改回「不指定」也写回", bsWidget() === "不指定", String(bsWidget()));

/* 10.9 之一：老工作流兼容 —— 旧开关开着 → 打开面板时一次性平移为「巨乳」 */
{
  const oldNode = makeNode();
  oldNode.widgets.find((w) => w.name === "big_breasts").value = true;
  nodeType.prototype.onNodeCreated.call(oldNode);
  // 与主面板同一入口：点「打开随机面板」按钮（onNodeCreated 只挂按钮不开面板）
  oldNode.widgets.find((w) => w.name.includes("打开随机面板")).callback();
  // 等**第二个** .av3-panel 出现（第一个是主面板，别拿错）
  let oldSel = null;
  for (let i = 0; i < 100 && !oldSel; i++) {
    await new Promise((r) => setTimeout(r, 10));
    const panels = document.body.querySelectorAll(".av3-panel");
    if (panels.length >= 2) oldSel = panels[panels.length - 1].querySelector(".av3-foot select");
  }
  ck("旧巨乳开关=True 的老工作流，打开面板即平移为「巨乳」",
     !!oldSel && oldSel.value === "巨乳", oldSel ? String(oldSel.value) : "无面板");
  // 平移是一次性的：旧开关应已退役
  ck("平移后旧开关退役（big_breasts=false）",
     oldNode.widgets.find((w) => w.name === "big_breasts").value === false,
     String(oldNode.widgets.find((w) => w.name === "big_breasts").value));
}

/* ── 10.10 角色编辑与自定义角色（v3.4.0 · v3.5.0 加特征标签）───── */
/* sleep 已提到文件前部（10.5b 批量删除要用） */
const editor = () => document.body.querySelector(".av3-editor");
const edInputs = () => [...editor().querySelectorAll(".av3-efld input")];
const edBtn = (t) => [...editor().querySelectorAll(".ft button")]
  .find((b) => b.textContent.includes(t));
const cardByTag = (tag) => cards().find((c) => c.dataset.tag === tag);
const PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8Dw"
  + "HwAFBQIAX8jx0gAAAABJRU5ErkJggg==";

/* ⚠️ v3.5.0 起，保存按钮在"特征标签读取完"之前是禁用的（防止把 tags 当空发出
   而静默清掉覆盖）。所以每次打开弹窗都要等它放行，否则点击是空操作。 */
async function waitEdReady() {
  for (let i = 0; i < 100; i++) {
    const b = edBtn("保存") || edBtn("添加角色");
    if (b && !b.disabled) return true;
    await sleep(10);
  }
  return false;
}
// 标签行的输入框（不在 .av3-efld 里，单独查）
const tagRowInputs = () => [...editor().querySelectorAll(".av3-tagrow input")];
const tagTexts = () => tagRowInputs().map((i) => i.value);

tabBtns[1].click();
for (let i = 0; i < 100 && !panel.querySelector(".av3-card"); i++) await sleep(10);

ck("角色库顶部有「添加角色」入口",
  [...panel.querySelectorAll(".av3-charbar .av3-btn")]
    .some((b) => b.textContent.includes("添加角色")));
ck("每张卡片都有编辑按钮 ✎", cards().every((c) => !!c.querySelector(".edit")));
ck("内置角色不带「自定义」角标",
  cards().every((c) => !c.querySelector(".av3-badge")));

/* ── 编辑一个内置角色 ── */
const editTag = cards()[0].dataset.tag;
const origRec = CHAR_FIX.characters.find((c) => c.tag === editTag);
cards()[0].querySelector(".edit").click();
ck("点 ✎ 打开角色编辑弹窗", !!editor());
ck("弹窗标题带角色名", (editor().querySelector(".hd")?.textContent || "")
  .includes("编辑角色"));
ck("弹窗里标明角色 tag（tag 本身不可改）",
  (editor().querySelector(".hd .tag")?.textContent || "") === editTag,
  editor().querySelector(".hd .tag")?.textContent || "");
ck("编辑弹窗有 3 个字段行 + 图片区",
  editor().querySelectorAll(".av3-efld").length === 3
  && !!editor().querySelector(".av3-ethumb"),
  String(editor().querySelectorAll(".av3-efld").length));
ck("内置角色同时给「↺ 恢复默认」与「🗑 删除角色」（v3.18.6 起内置可删）",
  !!edBtn("恢复默认") && !!edBtn("删除角色"),
  edBtn("恢复默认")?.textContent + " / " + edBtn("删除角色")?.textContent);
// ⚠️ 基准取**内置原文**（RAW_BY_TAG），不取夹具 —— 夹具是从 characters_payload()
//    生成的，万一接口漏发 trigger，两边一起 undefined 会让这条断言**虚假通过**
//    （v3.4.0 就是这么漏过去的，v3.5.0 才补上 trigger）。
ck("角色标签预填当前 trigger（对照内置原文）",
  edInputs()[2].value === (RAW_BY_TAG.get(editTag)?.trigger || "")
  && !!edInputs()[2].value,
  `${JSON.stringify(edInputs()[2].value)} vs ${JSON.stringify(RAW_BY_TAG.get(editTag)?.trigger)}`);
ck("作品输入框带候选作品 datalist",
  !!editor().querySelector("input[list=av3-worklist]")
  && editor().querySelectorAll("#av3-worklist option").length > 0);
ck("详情没读出来之前保存按钮是禁用的",
  (() => {
    const b = edBtn("保存");
    return b ? b.disabled === true : false;
  })(), "（或详情已即时返回，见下一条）");
ck("等一拍后保存放行（特征标签已就绪）", await waitEdReady());

// 空标签必须被拦在弹窗里（后端也会拒，但前端不该让用户白发一次请求）
edInputs()[2].value = "";
edBtn("保存").click();
await sleep(30);
ck("空角色标签被拦（弹窗不关、给出错误）",
  !!editor() && (editor().querySelector(".av3-eerr")?.textContent || "")
    .includes("不能为空"),
  editor()?.querySelector(".av3-eerr")?.textContent || "（弹窗被关了）");

CALLS.length = 0;
edInputs()[0].value = "冒烟改过";
edInputs()[2].value = "edited via smoke, test series";
edBtn("保存").click();
for (let i = 0; i < 80 && editor(); i++) await sleep(10);
ck("保存后弹窗关闭", !editor());
ck("保存走了 /characters/save",
  CALLS.some((c) => c.url.endsWith("/characters/save")));
ck("保存后卡片中文名变成改后的值",
  cardByTag(editTag)?.querySelector(".nm")?.textContent === "冒烟改过",
  cardByTag(editTag)?.querySelector(".nm")?.textContent || "(卡片没了)");
ck("改动不会污染内置夹具（原记录仍是旧中文名）",
  CHAR_FIX.characters.find((c) => c.tag === editTag)?.zh !== "冒烟改过");

/* ── 添加自定义角色 ── */
[...panel.querySelectorAll(".av3-charbar .av3-btn")]
  .find((b) => b.textContent.includes("添加角色")).click();
ck("点「添加角色」打开同一个弹窗",
  !!editor() && (editor().querySelector(".hd")?.textContent || "").includes("添加"));
ck("新增时主按钮是「添加角色」", !!edBtn("添加角色"));
ck("新增时没有删除 / 恢复默认（还没存呢）",
  !edBtn("删除角色") && !edBtn("恢复默认"));
ck("新增时「清除自定义图片」禁用",
  editor().querySelectorAll(".av3-ethumb .ops .row button")[1].disabled === true);

edInputs()[0].value = "冒烟新角色";
edInputs()[1].value = "smoke series";
edInputs()[2].value = "smoke custom girl, smoke series";
CALLS.length = 0;
edBtn("添加角色").click();
for (let i = 0; i < 80 && editor(); i++) await sleep(10);
ck("新增后弹窗关闭", !editor());
ck("新增走的是 create 模式",
  (() => {
    const c = CALLS.filter((x) => x.url.endsWith("/characters/save")).pop();
    try { return JSON.parse(c.opts.body).mode === "create"; } catch (e) { return false; }
  })());
const newCard = () => cards().find((c) => c.querySelector(".nm")?.textContent === "冒烟新角色");
ck("网格里出现刚加的自定义角色", !!newCard(),
  cards().map((c) => c.querySelector(".nm")?.textContent).join("/"));
ck("新增后搜索框自动筛选到新角色（不然人气 0 会沉底看不见）",
  (panel.querySelector(".av3-charbar input[type=text]")?.value || "").includes("冒烟新角色"),
  panel.querySelector(".av3-charbar input[type=text]")?.value || "");
const newTag = newCard()?.dataset.tag || "";
ck("自定义角色 tag 带 user_ 前缀", newTag.startsWith("user_"), newTag);
ck("自定义角色带「自定义」角标", !!newCard()?.querySelector(".av3-badge"));

/* ── 预览图：客户端校验 + 成功上传 ── */
newCard().querySelector(".edit").click();
await waitEdReady();
const fileIn = editor().querySelector('input[type=file]');
const setFiles = (f, name) => Object.defineProperty(fileIn, "files", {
  value: [f], configurable: true,
});
// ⚠️ jsdom 不加载图片、也不会自己触发 change，这里手工派发 —— 测的是我们
//    自己的校验与上传逻辑，不是 jsdom 的加载器。
setFiles(new dom.window.File(["x"], "a.txt", { type: "text/plain" }), "a.txt");
fileIn.dispatchEvent(new dom.window.Event("change"));
ck("非图片类型被拦", (editor().querySelector(".av3-eerr")?.textContent || "")
  .includes("只支持"), editor().querySelector(".av3-eerr")?.textContent || "");

setFiles(new dom.window.File([new Uint8Array(2 * 1024 * 1024 + 16)], "big.png",
                             { type: "image/png" }), "big.png");
fileIn.dispatchEvent(new dom.window.Event("change"));
ck("超 2MB 图片被拦", (editor().querySelector(".av3-eerr")?.textContent || "")
  .includes("过大"), editor().querySelector(".av3-eerr")?.textContent || "");

const pngBytes = Uint8Array.from(atob(PNG_1PX), (ch) => ch.charCodeAt(0));
setFiles(new dom.window.File([pngBytes], "p.png", { type: "image/png" }), "p.png");
fileIn.dispatchEvent(new dom.window.Event("change"));
for (let i = 0; i < 60; i++) {
  if ((editor()?.querySelector(".pv img")?.src || "").startsWith("data:image")) break;
  await sleep(10);
}
ck("选图后弹窗内立即预览本地图",
  (editor()?.querySelector(".pv img")?.src || "").startsWith("data:image"),
  (editor()?.querySelector(".pv img")?.src || "").slice(0, 24));

CALLS.length = 0;
edBtn("保存").click();
for (let i = 0; i < 80 && editor(); i++) await sleep(10);
const thumbCall = CALLS.filter((c) => c.url.endsWith("/characters/thumb")).pop();
ck("点保存时才上传图片（选了图先存内存）", !!thumbCall);
let thumbBody = {};
try { thumbBody = JSON.parse(thumbCall.opts.body); } catch (e) { /* 下面会红 */ }
ck("上传带 data_url 与角色 tag",
  String(thumbBody.data_url || "").startsWith("data:image") && thumbBody.tag === newTag,
  `${String(thumbBody.data_url || "").slice(0, 20)} / ${thumbBody.tag}`);

/* ── 删除自定义角色（两步确认）── */
newCard().querySelector(".edit").click();
await waitEdReady();
ck("自定义角色弹窗给「删除角色」", !!edBtn("删除角色"));
edBtn("删除角色").click();
ck("删除两步确认（第一次只改文案）", !!edBtn("再点一次"));
edBtn("再点一次").click();
for (let i = 0; i < 80 && editor(); i++) await sleep(10);
ck("删除后弹窗关闭", !editor());

const searchIn2 = panel.querySelector(".av3-charbar input[type=text]");
searchIn2.value = "";
searchIn2.dispatchEvent(new dom.window.Event("input"));
await sleep(20);
ck("删除后该角色从网格消失", !cardByTag(newTag), newTag);
ck("删除后一个「自定义」角标都不剩",
  !cards().some((c) => c.querySelector(".av3-badge")));

/* ── 恢复默认（内置）── */
const backCard = () => cardByTag(editTag);
backCard().querySelector(".edit").click();
await waitEdReady();
ck("编辑过的内置角色：中文名显示改后的值",
  edInputs()[0].value === "冒烟改过", edInputs()[0].value);
ck("编辑过的内置角色：角色标签显示改后的值",
  edInputs()[2].value === "edited via smoke, test series", edInputs()[2].value);
edBtn("恢复默认").click();
edBtn("再点一次").click();
for (let i = 0; i < 80 && editor(); i++) await sleep(10);
ck("恢复默认后弹窗关闭", !editor());
ck("恢复默认后中文名回到内置值",
  (backCard()?.querySelector(".nm")?.textContent || "") === (origRec?.zh || origRec?.name),
  `${backCard()?.querySelector(".nm")?.textContent} vs ${origRec?.zh || origRec?.name}`);
ck("恢复默认后重新打开弹窗是内置 trigger",
  (() => { backCard().querySelector(".edit").click();
    const v = edInputs()[2].value;
    edBtn("取消").click();
    return v === (origRec?.trigger || ""); })(),
  "（见上一条）");

/* ── 10.11 特征标签编辑（v3.5.0）────────────────────────────────
   挑一个"全量标签 > 8 条"的角色来测 —— 只有这样才验得出
   "编辑弹窗拿到的是全量、不是列表载荷里的前 8 条"。 */
const tagTestTag = (() => {
  const inPage = cards().map((c) => c.dataset.tag)
    .find((t) => (RAW_BY_TAG.get(t)?.tags || []).length > 8);
  if (inPage) return inPage;
  const any = [...RAW_BY_TAG.values()]
    .filter((c) => (c.tags || []).length > 8)
    .sort((a, b) => (b.pop || 0) - (a.pop || 0))[0];
  return any ? any.tag : "";
})();
const rawTags = (RAW_BY_TAG.get(tagTestTag)?.tags || []).slice();
ck("找到一个全量标签 > 8 条的角色用于本组用例",
  rawTags.length > 8, `${tagTestTag} → ${rawTags.length} 条`);

// 让它出现在网格里（可能不在首页）
const searchIn3 = panel.querySelector(".av3-charbar input[type=text]");
searchIn3.value = tagTestTag;
searchIn3.dispatchEvent(new dom.window.Event("input"));
await sleep(30);
const openEditorOn = async (tag) => {
  // 先收掉可能残留的弹窗（上一段若断言失败、没走到关闭，会留下一个旧弹窗，
  // 而 querySelector(".av3-editor") 只返回第一个 → 后续断言会读错对象）
  const stale = document.body.querySelector(".av3-editor");
  if (stale) {
    const m = stale.closest(".av3-mask");
    (m || stale).remove();
  }
  const card = cardByTag(tag);
  if (!card) return false;
  card.querySelector(".edit").click();
  const ready = await waitEdReady();
  ck("同一时刻只有一个编辑弹窗",
    document.body.querySelectorAll(".av3-editor").length === 1,
    String(document.body.querySelectorAll(".av3-editor").length));
  return ready;
};
ck("打开该角色的编辑弹窗", await openEditorOn(tagTestTag));

ck("编辑弹窗里有「特征标签」区", !!editor().querySelector(".av3-tagsec"));
ck("标签区写明生效条件（体型直接生效 / 发色瞳色要没记录）",
  (editor().querySelector(".av3-tagsec")?.textContent || "").includes("体型标签")
  && (editor().querySelector(".av3-tagsec")?.textContent || "").includes("发色瞳色标签"),
  editor().querySelector(".av3-tagsec")?.textContent?.slice(0, 40) || "");
ck("标签行数 = 该角色的**全量**标签（不是列表载荷里的前 8 条）",
  tagRowInputs().length === rawTags.length && tagRowInputs().length > 8,
  `${tagRowInputs().length} vs 全量 ${rawTags.length}`);
ck("标签行预填内置内容（顺序一致）",
  tagTexts().join("|") === rawTags.join("|"), tagTexts().join("|"));
ck("头部显示内置条数",
  (editor().querySelector(".av3-taghead .av3-meta")?.textContent || "")
    .includes(String(rawTags.length)),
  editor().querySelector(".av3-taghead .av3-meta")?.textContent || "");
ck("头部有「恢复内置标签」入口", !!editor().querySelector(".av3-taghead .av3-btn"));
ck("底部有「＋ 添加标签」与「已 N 条（上限 40）」计数",
  !!editor().querySelector(".av3-tagfoot .av3-btn")
  && (editor().querySelector(".av3-tagfoot .av3-meta")?.textContent || "")
    .includes(`已 ${rawTags.length} 条`)
  && (editor().querySelector(".av3-tagfoot .av3-meta")?.textContent || "")
    .includes("上限 40"),
  editor().querySelector(".av3-tagfoot .av3-meta")?.textContent || "");
ck("每行都有一个 × 删除按钮",
  editor().querySelectorAll(".av3-tagrow").length === tagRowInputs().length
  && editor().querySelectorAll(".av3-tagrow .av3-btn").length === tagRowInputs().length);

/* 增：＋ 添加标签 */
const n0 = tagRowInputs().length;
editor().querySelector(".av3-tagfoot .av3-btn").click();
ck("点「＋ 添加标签」新增一行", tagRowInputs().length === n0 + 1,
  String(tagRowInputs().length));
ck("新增行是空的、带占位提示",
  tagRowInputs().at(-1).value === ""
  && (tagRowInputs().at(-1).placeholder || "").includes("breasts"),
  tagRowInputs().at(-1).placeholder || "");
ck("空行不计入「已 N 条」计数",
  (editor().querySelector(".av3-tagfoot .av3-meta")?.textContent || "")
    .includes(`已 ${n0} 条`),
  editor().querySelector(".av3-tagfoot .av3-meta")?.textContent || "");

/* 改：直接改那一行 */
const typeTag = (el, v) => {
  el.value = v;
  el.dispatchEvent(new dom.window.Event("input"));   // 手打会触发 input，程序赋值不会
};
typeTag(tagRowInputs().at(-1), "large breasts");
typeTag(tagRowInputs()[0], "1girl edited");
ck("填入内容后计数 +1",
  (editor().querySelector(".av3-tagfoot .av3-meta")?.textContent || "")
    .includes(`已 ${n0 + 1} 条`),
  editor().querySelector(".av3-tagfoot .av3-meta")?.textContent || "");
CALLS.length = 0;
edBtn("保存").click();
for (let i = 0; i < 80 && editor(); i++) await sleep(10);
ck("改完标签保存成功（弹窗关闭）", !editor(),
  editor()?.querySelector(".av3-eerr")?.textContent || "");
let tagBody = {};
try {
  tagBody = JSON.parse(
    CALLS.filter((c) => c.url.endsWith("/characters/save")).pop().opts.body);
} catch (e) { /* 下条断言会红 */ }
ck("保存请求带 tags 数组（新增 + 改过的都在）",
  Array.isArray(tagBody.fields?.tags)
  && tagBody.fields.tags.includes("large breasts")
  && tagBody.fields.tags.includes("1girl edited")
  && tagBody.fields.tags.length === n0 + 1,
  JSON.stringify(tagBody.fields?.tags ?? null));

/* 回读：覆盖已生效 + 头部标注 */
await openEditorOn(tagTestTag);
ck("重新打开后标签 = 改后的列表",
  tagTexts().includes("large breasts") && tagTexts().includes("1girl edited"),
  tagTexts().join("|"));
ck("头部标注「已被修改」",
  (editor().querySelector(".av3-taghead .av3-meta")?.textContent || "").includes("已被修改"),
  editor().querySelector(".av3-taghead .av3-meta")?.textContent || "");

/* 删：点该行的 × */
const beforeDel = tagRowInputs().length;
[...editor().querySelectorAll(".av3-tagrow .av3-btn")].at(-1).click();
ck("点 × 删掉最后一行", tagRowInputs().length === beforeDel - 1,
  String(tagRowInputs().length));
ck("删掉的是最后那条「large breasts」",
  !tagTexts().includes("large breasts"), tagTexts().join("|"));

/* 恢复内置标签：先弄脏，再一键还原 */
editor().querySelector(".av3-tagfoot .av3-btn").click();
tagRowInputs().at(-1).value = "huge breasts";
ck("先弄脏：当前列表与内置不同",
  tagTexts().join("|") !== rawTags.join("|"));
editor().querySelector(".av3-taghead .av3-btn").click();
ck("「恢复内置标签」把行填回内置值",
  tagTexts().join("|") === rawTags.join("|"), tagTexts().join("|"));
CALLS.length = 0;
edBtn("保存").click();
for (let i = 0; i < 80 && editor(); i++) await sleep(10);
let tagBody2 = {};
try {
  tagBody2 = JSON.parse(
    CALLS.filter((c) => c.url.endsWith("/characters/save")).pop().opts.body);
} catch (e) { /* 下条断言会红 */ }
ck("与内置一致时发空数组（真清覆盖，而不是写一份副本）",
  Array.isArray(tagBody2.fields?.tags) && tagBody2.fields.tags.length === 0,
  JSON.stringify(tagBody2.fields?.tags ?? null));
await openEditorOn(tagTestTag);
ck("清掉覆盖后头部不再标「已被修改」",
  !(editor().querySelector(".av3-taghead .av3-meta")?.textContent || "").includes("已被修改"),
  editor().querySelector(".av3-taghead .av3-meta")?.textContent || "");

/* 校验：非法标签被后端拒绝，弹窗不关 */
typeTag(tagRowInputs()[0], "中文标签");
CALLS.length = 0;
edBtn("保存").click();
for (let i = 0; i < 60 && !CALLS.some((c) => c.url.endsWith("/characters/save")); i++) {
  await sleep(10);
}
await sleep(40);
ck("非法标签被拒（弹窗不关 + 错误显示在弹窗里）",
  !!editor() && (editor().querySelector(".av3-eerr")?.textContent || "").includes("不合法"),
  editor()?.querySelector(".av3-eerr")?.textContent || "（弹窗被关了）");
ck("被拒后保存按钮重新可用（能改回去再存）",
  (() => { const b = edBtn("保存"); return !!b && !b.disabled; })());

typeTag(tagRowInputs()[0], rawTags[0] || "1girl");
edBtn("取消").click();
ck("取消关闭标签编辑弹窗", !editor());
searchIn3.value = "";
searchIn3.dispatchEvent(new dom.window.Event("input"));
await sleep(20);

/* ── 10.12 场景搭配（v3.9.0）──────────────────────────────────── */
tabBtns.find((b) => b.textContent.includes("场景搭配")).click();
for (let i = 0; i < 100 && !panel.querySelector(".av3-sec[data-scene]"); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("切到场景页后请求了 /scenes", CALLS.some((c) => c.url.endsWith("/scenes")));

const sceneCards = () => [...panel.querySelectorAll(".av3-sec[data-scene]")];
// v3.43.0：场景页改成**首屏 60 条懒加载**（190 张卡一次建 DOM 会卡）。
// 所以"全量"类断言必须先点「显示全部」把 rest 放出来。
const loadAllScenes = async () => {
  for (let i = 0; i < 20; i++) {
    const b = panel.querySelector("#av3-scene-moreall");
    if (!b) return;
    b.click();
    await new Promise((r) => setTimeout(r, 20));
  }
};
ck("首屏只渲染 60 条（懒加载生效）",
  sceneCards().length === 60 && !!panel.querySelector("#av3-scene-more"),
  `${sceneCards().length} 张 / more=${!!panel.querySelector("#av3-scene-more")}`);
await loadAllScenes();

// v3.18.0：这一页只列**场景搭配**；32 条特写搭配在第四个页签，不混排。
const nonManualCount = SCENE_FIX.scenes.filter((s) => !s.manual).length;
ck("场景卡数量 == 库里的非特写场景数",
  sceneCards().length === nonManualCount,
  `${sceneCards().length} vs ${nonManualCount}`);
/* ── v3.21.0：语义分组筛选条（全部 / 🧎 姿势场景）── */
const gbar = panel.querySelector("#av3-scene-groups");
ck("场景页有语义分组筛选条", !!gbar);
const gbtns = gbar ? [...gbar.querySelectorAll("button")] : [];
ck("筛选条两个按钮（全部 / 姿势场景）", gbtns.length === 2,
  gbtns.map((b) => b.textContent).join("|"));
ck("默认选中「全部」",
  gbtns[0]?.dataset.group === "all" && /pri/.test(gbtns[0]?.className || ""),
  `${gbtns[0]?.dataset.group} / ${gbtns[0]?.className}`);
const poseCount = SCENE_FIX.scenes.filter((s) => s.group === "pose" && !s.manual).length;
ck("夹具里确有姿势场景（group=pose）", poseCount >= 24, String(poseCount));
const clickGroup = async (gid) => {
  [...panel.querySelectorAll("#av3-scene-groups button")]
    .find((x) => x.dataset.group === gid).click();
  await new Promise((r) => setTimeout(r, 30));
};
await clickGroup("pose");
ck("切到「姿势场景」后只剩姿势卡",
  sceneCards().length === poseCount
  && sceneCards().every((c) => (c.dataset.scene || "").startsWith("sc_pose_")),
  `${sceneCards().length} vs ${poseCount}`);
ck("姿势卡带【姿势·】角标（面板上一眼可辨）",
  sceneCards().every((c) => /姿势·/.test(c.textContent)),
  sceneCards().map((c) => c.textContent.slice(0, 20)).join(" / "));
ck("筛选后按钮高亮跟着切",
  /pri/.test(panel.querySelector('#av3-scene-groups button[data-group="pose"]')?.className || ""));
await clickGroup("all");
await loadAllScenes();       // 切分组会重置懒加载上限
ck("切回「全部」恢复全量", sceneCards().length === nonManualCount,
  `${sceneCards().length} vs ${nonManualCount}`);

ck("场景页一张特写卡都没有",
  !sceneCards().some((c) => (c.dataset.scene || "").startsWith("sc_near_")),
  sceneCards().map((c) => c.dataset.scene).filter((i) => i.startsWith("sc_near_")).join("/"));
/* ── 10.12b 场景检索 / 收藏 / 浏览增强（v3.43.0）─────────────────
   一页 190 条，只靠滚动找不到东西，所以补了搜索 / 收藏 / 题材条 /
   档位折叠 / 懒加载 / 紧凑模式。这几条都只影响**视图**，不碰权重表。 */

// ① 搜索（空格分词 AND）
const sceneQ = () => panel.querySelector("#av3-scene-q");
ck("场景页有搜索框", !!sceneQ());
const typeSceneQ = async (v) => {
  const el = sceneQ();
  el.value = v;
  el.dispatchEvent(new dom.window.Event("input"));
  await sleep(30);
};
await typeSceneQ("教室 托腮");
ck("两个词是 AND：只剩同时命中的那一条",
  sceneCards().length === 1
  && sceneCards()[0].dataset.scene === "sc_classroom_chin_rest",
  `${sceneCards().length} 张：${sceneCards().map((c) => c.dataset.scene).join("/")}`);
ck("「命中 N 条」跟着搜索结果变",
  /命中 1 条/.test(panel.querySelector("#av3-scene-hits")?.textContent || ""),
  panel.querySelector("#av3-scene-hits")?.textContent || "");
ck("搜索时输入框仍是焦点（重绘没把光标弄丢）",
  dom.window.document.activeElement === sceneQ(),
  String(dom.window.document.activeElement?.id
    || dom.window.document.activeElement?.tagName || "（无）"));
await typeSceneQ("雨");
// 期望值从夹具**算**而不是写死 —— 场景库每加一条含「雨」的，写死的 4 就假红
const rainN = SCENE_FIX.scenes.filter((s) => !s.manual
  && String(s.zh || "").includes("雨")).length;
ck("中文描述 / 题材也能搜到", sceneCards().length === rainN && rainN > 0,
  `${sceneCards().length} vs ${rainN}`);
await typeSceneQ("kneeling");
ck("英文标签（字段值）同样可搜",
  sceneCards().length > 0 && sceneCards().length < 60,
  `${sceneCards().length} 张`);
await typeSceneQ("zzz这个场景不存在");
ck("搜不到时给空状态，而不是一片空白",
  !!panel.querySelector("#av3-scene-empty") && sceneCards().length === 0);
ck("空状态下不再挂「还有 N 条」", !panel.querySelector("#av3-scene-more"));
panel.querySelector("#av3-scene-clear").click();
await sleep(30);
ck("「清空筛选」把搜索词也清掉，且回到首屏 60 条",
  sceneQ().value === "" && sceneCards().length === 60,
  `「${sceneQ().value}」/ ${sceneCards().length} 张`);

// ② 题材快捷筛选条
const themeBar = () => panel.querySelector("#av3-scene-themes");
ck("有题材快捷筛选条", !!themeBar());
ck("题材条默认按条数降序、最多 18 个 + 「更多」",
  [...themeBar().querySelectorAll("button[data-theme]")].length === 18
  && !!panel.querySelector("#av3-scene-thememore"),
  `${[...themeBar().querySelectorAll("button[data-theme]")].length} 个`);
const themeBtn = (t) => [...themeBar().querySelectorAll("button")]
  .find((b) => b.dataset.theme === t);
ck("题材条里有 BDSM", !!themeBtn("BDSM"),
  [...themeBar().querySelectorAll("button")].slice(0, 6)
    .map((b) => b.textContent).join("|"));
themeBtn("BDSM").click();
await sleep(30);
ck("选题材后只剩该题材的卡",
  sceneCards().length === 18 && sceneCards().every((c) => /【BDSM】/.test(c.textContent)),
  `${sceneCards().length} 张`);
ck("选中的题材按钮高亮",
  /pri/.test(themeBtn("BDSM")?.className || ""), themeBtn("BDSM")?.className);
themeBtn("BDSM").click();
await sleep(30);
const allThemeBtn = () => [...themeBar().querySelectorAll("button")]
  .find((b) => b.textContent.startsWith("全部题材"));
ck("再点一次取消题材筛选", sceneCards().length === 60 && /pri/.test(
  allThemeBtn()?.className || ""),
  `${sceneCards().length} 张 / 按钮=${allThemeBtn()?.className} / theme="${allThemeBtn()?.textContent}"`);
ck("「更多题材」能展开被截断的题材",
  (() => {
    panel.querySelector("#av3-scene-thememore").click();
    return [...themeBar().querySelectorAll("button[data-theme]")].length > 18;
  })(),
  String([...themeBar().querySelectorAll("button[data-theme]")].length));
panel.querySelector("#av3-scene-thememore").click();
await sleep(20);

/* ⑥ 题材条整条可收起（v3.44.0）───────────────────────────────
   两级折叠必须能分开：整条 = 「▾/▸ 🏷 题材」，条内 = 「更多题材 / 只显示常用的」。
   收起后当前题材仍要看得见，否则会出现"列表被筛掉一半却看不出原因"。 */
const themeTog = () => panel.querySelector("#av3-scene-themetoggle");
const themeChips = () => [...themeBar().querySelectorAll("button[data-theme]")];
ck("题材条有整条收起按钮，默认展开",
  /▾/.test(themeTog()?.textContent || "") && themeChips().length === 18,
  `${themeTog()?.textContent} / ${themeChips().length} 个题材`);
panel.querySelector("#av3-scene-thememore").click();     // 展开到全部 62
await sleep(20);
ck("条内那颗改叫「只显示常用的」，不再与整条收起撞名",
  /只显示常用/.test(panel.querySelector("#av3-scene-thememore")?.textContent || "")
  && themeChips().length > 18,
  `${panel.querySelector("#av3-scene-thememore")?.textContent} / ${themeChips().length} 个`);
panel.querySelector("#av3-scene-thememore").click();     // 收回 18 个常用
await sleep(20);
ck("「只显示常用的」能收回到 18 个",
  themeChips().length === 18, String(themeChips().length));

themeBtn("BDSM").click();
await sleep(30);
themeTog().click();
await sleep(30);
ck("收起后题材 chip 全部消失",
  themeChips().length === 0, String(themeChips().length));
ck("收起后仍显示当前题材（不会筛掉一半却看不出原因）",
  /当前：BDSM/.test(panel.querySelector("#av3-scene-themesum")?.textContent || ""),
  panel.querySelector("#av3-scene-themesum")?.textContent || "（没有摘要）");
ck("收起后筛选仍然生效（卡片还是那 18 条 BDSM）",
  sceneCards().length === 18 && sceneCards().every((c) => /【BDSM】/.test(c.textContent)),
  `${sceneCards().length} 张`);
ck("收起态箭头变 ▸",
  /▸/.test(themeTog()?.textContent || ""), themeTog()?.textContent);
panel.querySelector("#av3-scene-themeclear").click();
await sleep(30);
ck("收起态能直接 ✕ 取消题材，不用先展开",
  !panel.querySelector("#av3-scene-themeclear") && sceneCards().length === 60,
  `${sceneCards().length} 张`);
themeTog().click();
await sleep(30);
ck("再点一次展开，题材 chip 回来",
  themeChips().length === 18 && /▾/.test(themeTog().textContent),
  `${themeChips().length} 个 / ${themeTog().textContent}`);
await loadAllScenes();

// ③ 档位分组可折叠
const lvHead = (n) => panel.querySelector("#av3-scene-lv" + n);
const levelOf = (id) => (SCENE_FIX.scenes.find((s) => s.id === id) || {}).level;
const l0Cards = () => sceneCards().filter((c) => levelOf(c.dataset.scene) === 0);
const nonManualL0 = SCENE_FIX.scenes.filter((s) => !s.manual && s.level === 0).length;
ck("档位标题行变成可折叠的（带 ▼）",
  /▼/.test(lvHead(0)?.textContent || ""), lvHead(0)?.textContent || "（没有 L0 标题）");
ck("折叠前 L0 卡在场", l0Cards().length === nonManualL0,
  `${l0Cards().length} vs ${nonManualL0}`);
lvHead(0).click();
await sleep(30);
ck("点档位标题后这一档收起（L0 卡全部消失）", l0Cards().length === 0,
  `还剩 ${l0Cards().length} 张`);
ck("收起后标题变成 ▶", /▶/.test(lvHead(0)?.textContent || ""),
  lvHead(0)?.textContent || "");
lvHead(0).click();
await sleep(30);
ck("再点一次展开回来", l0Cards().length === nonManualL0,
  `${l0Cards().length} vs ${nonManualL0}`);

// ④ 收藏（两页共用，存独立文件）
const sceneStarOf = (id) => panel.querySelector(`.av3-sec[data-scene="${id}"] .av3-sfav`);
const favId = "sc_rooftop_stretch";
ck("每张场景卡都有 ☆ 收藏按钮", sceneStarOf(favId)?.textContent === "☆",
  sceneStarOf(favId)?.textContent || "（没有星标）");
CALLS.length = 0;
sceneStarOf(favId).click();
for (let i = 0; i < 60
     && !CALLS.some((c) => c.url.endsWith("/scenes/favorites/toggle")); i++) {
  await sleep(10);
}
await sleep(50);
ck("点 ☆ 发出 /scenes/favorites/toggle（独立于角色收藏那条路由）",
  CALLS.some((c) => c.url.endsWith("/scenes/favorites/toggle")),
  CALLS.map((c) => c.url).filter((u) => u.includes("favor")).join("|"));
ck("点 ☆ 不会顺手把卡片展开（stopPropagation 生效）",
  !panel.querySelector(`.av3-sec[data-scene="${favId}"]`)?.classList.contains("open"));
ck("收藏后星标变 ★", sceneStarOf(favId)?.textContent === "★", sceneStarOf(favId)?.textContent);
ck("收藏项被置顶到「⭐ 我的收藏」区",
  /（1）/.test(panel.querySelector("#av3-scene-favsec")?.textContent || ""),
  panel.querySelector("#av3-scene-favsec")?.textContent || "（没有收藏区）");
ck("置顶区第一张就是它",
  panel.querySelector("#av3-scene-favsec")?.nextElementSibling?.dataset.scene === favId,
  panel.querySelector("#av3-scene-favsec")?.nextElementSibling?.dataset.scene || "（空）");
ck("置顶后**不在**档位分组里重复出现",
  sceneCards().filter((c) => c.dataset.scene === favId).length === 1,
  String(sceneCards().filter((c) => c.dataset.scene === favId).length));
panel.querySelector("#av3-scene-favonly").click();
await sleep(30);
ck("「⭐ 只看收藏」只剩收藏项",
  sceneCards().length === 1 && sceneCards()[0].dataset.scene === favId,
  `${sceneCards().length} 张`);
panel.querySelector("#av3-scene-favonly").click();
await sleep(30);
const nFavPost = CALLS.filter((c) => c.url.endsWith("/scenes/favorites/toggle")).length;
sceneStarOf(favId).click();
for (let i = 0; i < 60
     && CALLS.filter((c) => c.url.endsWith("/scenes/favorites/toggle")).length === nFavPost; i++) {
  await sleep(10);
}
await sleep(50);
// ⚠️ 取消收藏后它不再置顶，回到档位分组里 —— 排在 60 条之后也算正常，
//    所以先放全量再断言"回到分组"，否则测的是懒加载窗口而不是分类逻辑。
await loadAllScenes();
ck("取消收藏后置顶区消失、卡片回到档位分组",
  !panel.querySelector("#av3-scene-favsec")
  && sceneCards().filter((c) => c.dataset.scene === favId).length === 1,
  `favsec=${!!panel.querySelector("#av3-scene-favsec")}`
  + ` / 卡片数=${sceneCards().filter((c) => c.dataset.scene === favId).length}`
  + ` / 总卡=${sceneCards().length}`);

// ⑤ 紧凑模式
panel.querySelector("#av3-scene-compact").click();
await sleep(30);
ck("紧凑模式给每张卡挂 compact 类",
  sceneCards().length > 0 && sceneCards().every((c) => c.classList.contains("compact")));
ck("紧凑模式下动作行仍在（套用不必先展开）",
  !!sceneCards()[0].querySelector(".av3-sceneact .av3-btn"));
panel.querySelector("#av3-scene-compact").click();
await sleep(30);
ck("切回卡片模式去掉 compact 类",
  sceneCards().every((c) => !c.classList.contains("compact")));

// ⚠️ v3.10.0：一级分组是 **NSFW 档位**（level_groups），不是 sfw/nsfw
ck("载荷带五个档位分组", (SCENE_FIX.level_groups || []).length === 5,
  String((SCENE_FIX.level_groups || []).length));
ck("每个非空档位组都有小标题",
  (SCENE_FIX.level_groups || []).filter((g) => g.count > 0)
    .every((g) => [...panel.querySelectorAll(".av3-note")]
      .some((e) => e.textContent.includes(g.title))),
  (SCENE_FIX.level_groups || []).map((g) => `${g.title}:${g.count}`).join(" "));
ck("档位分组标题带条数",
  /（\d+）/.test([...panel.querySelectorAll(".av3-note")]
    .map((e) => e.textContent).join("")));
ck("当前档位那一组被标出来",
  [...panel.querySelectorAll(".av3-note")]
    .some((e) => e.textContent.includes("当前档位")));
ck("卡片标题显示题材标签（【…】）",
  /【.+】/.test(sceneCards()[0].querySelector(".hd").textContent),
  sceneCards()[0].querySelector(".hd").textContent.slice(0, 48));
// ⚠️ v3.11.0：场景卡**默认折叠**（87 条全展开要滚几千像素）。
//    动作行必须在 .bd **外面**，否则折叠时连「一键套用」都点不到。
ck("场景卡默认折叠", sceneCards().every((c) => !c.classList.contains("open")));
const sceneBtnOf = (card, kw) => [...card.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes(kw));
ck("折叠时动作行仍可见（一键套用 / 套用并预演都在）",
  !!sceneBtnOf(sceneCards()[0], "一键套用") && !!sceneBtnOf(sceneCards()[0], "预演"),
  [...sceneCards()[0].querySelectorAll(".av3-btn")].map((b) => b.textContent).join("/"));
ck("卡片标出档位",
  /L\d|全档/.test(sceneCards()[0].querySelector(".hd").textContent),
  sceneCards()[0].querySelector(".hd").textContent);

// 点标题行 → 展开出字段列表
sceneCards()[0].querySelector(".hd").click();
ck("点标题行后卡片展开", sceneCards()[0].classList.contains("open"));
ck("展开后列出被固定的字段（lab：值）",
  sceneCards()[0].querySelectorAll(".av3-chip").length
    >= (SCENE_FIX.scenes[0].fields || []).length,
  String(sceneCards()[0].querySelectorAll(".av3-chip").length));
sceneCards()[0].querySelector(".hd").click();
ck("再点一次收起", !sceneCards()[0].classList.contains("open"));

// 全部展开 / 全部收起
panel.querySelector("#av3-scene-expand").click();
ck("「全部展开」把每张卡都打开",
  sceneCards().every((c) => c.classList.contains("open")),
  `${sceneCards().filter((c) => c.classList.contains("open")).length} 张`);
ck("按钮文案变成「全部收起」",
  /全部收起/.test(panel.querySelector("#av3-scene-expand").textContent));
panel.querySelector("#av3-scene-expand").click();
ck("「全部收起」把每张卡都合上",
  sceneCards().every((c) => !c.classList.contains("open")));

const wjson = () => JSON.parse(
  node.widgets.find((w) => w.name === "weights_json").value || "{}");
const sceneIdOf = (card) => card.dataset.scene;

// 一键套用
const applyBtnOf = (card) => [...card.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("套用") && !b.textContent.includes("预演"));
const target = sceneCards().find((c) => sceneIdOf(c) === "sc_rooftop_stretch")
  || sceneCards()[0];
const targetId = sceneIdOf(target);
applyBtnOf(target).click();
const w1 = wjson();
ck("套用后 n_canon 字段权重 = 3.0（必现）",
  Number(w1.fields?.n_canon) === 3, JSON.stringify(w1.fields));
ck("套用后本场景选项 = 3.0",
  Number(w1.options?.n_canon?.[targetId]) === 3,
  JSON.stringify(w1.options?.n_canon?.[targetId]));
const others = Object.entries(w1.options?.n_canon || {})
  .filter(([k]) => k !== targetId);
ck("同字段其它预设全部归零（保证只出这一条）",
  others.length > 0 && others.every(([, v]) => Number(v) === 0),
  `${others.length} 项`);
ck("套用后段权重不是 0（否则段会被 disabled_sections 关掉）",
  Number(w1.sections?.canon ?? 1) !== 0, JSON.stringify(w1.sections));
ck("套用后状态条显示当前套用",
  /当前套用/.test(panel.querySelector("#av3-scene-cur")?.textContent || ""),
  panel.querySelector("#av3-scene-cur")?.textContent || "");
ck("该卡按钮变成已套用且禁用",
  applyBtnOf(panel.querySelector(`.av3-sec[data-scene="${targetId}"]`)).disabled === true);

// 套用并预演 → 应发出 /roll
const nRoll2 = CALLS.filter((c) => c.url.endsWith("/roll")).length;
const pvBtn = [...panel.querySelector(`.av3-sec[data-scene="${targetId}"]`)
  .querySelectorAll(".av3-btn")].find((b) => b.textContent.includes("预演"));
pvBtn.click();
for (let i = 0; i < 80
     && CALLS.filter((c) => c.url.endsWith("/roll")).length === nRoll2; i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("「套用并预演」真的发出了 /roll",
  CALLS.filter((c) => c.url.endsWith("/roll")).length > nRoll2);

// v3.11.0：👁 预览 = **只看不套用**（临时权重，不改权重表）
const sceneCardOf = (id) => panel.querySelector(`.av3-sec[data-scene="${id}"]`);
const pvWBefore = JSON.stringify(wjson());
const nRollPv = CALLS.filter((c) => c.url.endsWith("/roll")).length;
const pvEyeBtn = sceneBtnOf(sceneCardOf(targetId), "预览");
ck("场景卡有「👁 预览」按钮", !!pvEyeBtn,
  [...sceneCardOf(targetId).querySelectorAll(".av3-btn")].map((b) => b.textContent).join("/"));
pvEyeBtn.click();
// ⚠️ 等**内联框真的渲染出来**，不能只等 /roll 被调用 —— 请求与响应是异步的
for (let i = 0; i < 100
     && !(sceneCardOf(targetId).querySelector(".av3-sceneout")?.textContent || "")
       .includes("school uniform"); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
ck("「👁 预览」发出了 /roll",
  CALLS.filter((c) => c.url.endsWith("/roll")).length > nRollPv);
ck("「👁 预览」**不改动**权重表（与「套用并预演」的关键区别）",
  JSON.stringify(wjson()) === pvWBefore, JSON.stringify(wjson()).slice(0, 80));
const pvInlineOut = sceneCardOf(targetId).querySelector(".av3-sceneout");
ck("预览结果显示在卡片**内联**框里",
  !!pvInlineOut && pvInlineOut.style.display !== "none"
  && (pvInlineOut.textContent || "").includes("school uniform"),
  (pvInlineOut && pvInlineOut.textContent || "").slice(0, 60));
ck("内联预览带档位/自检行",
  !!pvInlineOut && /自检/.test(pvInlineOut.textContent));
pvEyeBtn.click();
ck("再点「👁 预览」收起内联框",
  sceneCardOf(targetId).querySelector(".av3-sceneout").style.display === "none",
  sceneCardOf(targetId).querySelector(".av3-sceneout").style.display);

// 取消套用
[...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("取消套用")).click();
const w2 = wjson();
ck("取消套用后 n_canon 选项清空",
  !w2.options?.n_canon || Object.keys(w2.options.n_canon).length === 0,
  JSON.stringify(w2.options?.n_canon));
ck("取消套用后字段权重回到默认（不写进权重表）",
  w2.fields?.n_canon === undefined, JSON.stringify(w2.fields));
ck("取消后状态条显示未套用",
  /未套用/.test(panel.querySelector("#av3-scene-cur")?.textContent || ""),
  panel.querySelector("#av3-scene-cur")?.textContent || "");

/* ── 10.13 特写搭配（v3.18.0）────────────────────────────────── */
const nearTab = tabBtns.find((b) => b.textContent.includes("特写搭配"));
const nearPartOf = (id) => (SCENE_FIX.scenes.find((s) => s.id === id) || {}).part || "";
const manualScenes = SCENE_FIX.scenes.filter((s) => s.manual);
const nearCards = () => [...panel.querySelectorAll(".av3-sec[data-scene^='sc_near_']")];
const btnByText = (kw) => [...panel.querySelectorAll(".av3-btn")]
  .find((b) => (b.textContent || "").trim().startsWith(kw));

nearTab.click();
for (let i = 0; i < 100 && !nearCards().length; i++) await sleep(10);
ck("特写页卡片数 == 载荷里的 manual 条数",
  nearCards().length === manualScenes.length,
  `${nearCards().length} vs ${manualScenes.length}`);
ck("特写卡都带「🔍 仅手动」角标",
  nearCards().every((c) => c.textContent.includes("仅手动")),
  nearCards().filter((c) => !c.textContent.includes("仅手动")).map((c) => c.dataset.scene).join("/"));
const LOCAL_PARTS = ["腿部", "脚部", "手部", "臀部"];
const wOfRW = () => String(node.widgets.find((w) => w.name === "role_works").value || "");
const roleSrc = panel.querySelector("#av3-near-rolesrc");
const roleIp = panel.querySelector("#av3-near-rolesrc-ip");
ck("特写页有「🎭 角色来源」栏（面部/眼唇/上半身 用）", !!roleSrc && !!roleIp,
  `${!!roleSrc} / ${!!roleIp}`);
ck("角色来源默认显示「全库随机」",
  /全库随机/.test(roleSrc?.textContent || ""), roleSrc?.textContent || "");
roleIp.value = "genshin impact";
roleIp.dispatchEvent(new dom.window.Event("input"));
await sleep(20);
ck("填作品 IP 写进同一个 role_works 控件",
  wOfRW() === "genshin impact", wOfRW());
ck("状态文案跟着变成「在作品…内随机」",
  /genshin impact/.test(roleSrc?.textContent || ""), roleSrc?.textContent || "");
roleIp.value = "";
roleIp.dispatchEvent(new dom.window.Event("input"));
await sleep(20);
ck("清空后回到全库随机",
  wOfRW() === "" && /全库随机/.test(roleSrc?.textContent || ""),
  `${wOfRW()} / ${roleSrc?.textContent}`);
/* role 锁定诊断 + 自动解锁（v3.18.4）—— 修 v3.18.3 的"只有指定角色生效" */
const lockOf = () => String(node.widgets.find((w) => w.name === "lock_fields").value || "");
const hasRoleLock = () => /(^|[,\s])role([,\s]|$)/.test(lockOf());
node.widgets.find((w) => w.name === "lock_fields").value = "role";
btnByText("面部").click();          // 触发一次 renderNear
await sleep(40);
const lockWarn = panel.querySelector("#av3-near-rolelock");
ck("role 被锁时特写页出现诊断行", !!lockWarn,
  [...panel.querySelectorAll(".av3-charbar")].map((e) => e.textContent).join(" | ").slice(0, 160));
ck("诊断行说明随机 / IP 抽角色不会生效",
  /不会生效/.test(lockWarn?.textContent || ""), lockWarn?.textContent || "");
ck("诊断行带「🔓 解除 role 锁」按钮", !!panel.querySelector("#av3-near-roleunlock"));
panel.querySelector("#av3-near-roleunlock").click();
await sleep(30);
ck("点解除后 lock_fields 里没有 role", !hasRoleLock(), lockOf());
ck("解除后诊断行消失", !panel.querySelector("#av3-near-rolelock"));

/* 套用"要角色"的条目时，自动摘掉残留的 role 锁 */
node.widgets.find((w) => w.name === "lock_fields").value = "role";
btnByText("全部").click();
await sleep(30);
const faceCard4 = nearCards().find((c) => c.dataset.scene === "sc_near_face_classroom");
ck("面部组样例卡在列表里", !!faceCard4);
applyBtnOf(faceCard4).click();
await sleep(30);
ck("套用面部条目时自动摘掉残留的 role 锁", !hasRoleLock(), lockOf());
ck("状态条说明已解除 role 锁（不静默）",
  /role 锁/.test(panel.querySelector("#av3-status")?.textContent || ""),
  panel.querySelector("#av3-status")?.textContent || "");
[...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("取消套用")).click();
await sleep(20);
node.widgets.find((w) => w.name === "lock_fields").value = "";   // 收尾，别污染后面的用例

ck("手/腿/脚/臀 卡片带「✂ 收紧取景」+「🧹 清角色」角标",
  nearCards().filter((c) => LOCAL_PARTS.includes(nearPartOf(c.dataset.scene)))
    .every((c) => c.textContent.includes("收紧取景") && c.textContent.includes("清角色")),
  nearCards().filter((c) => LOCAL_PARTS.includes(nearPartOf(c.dataset.scene))
    && !(c.textContent.includes("收紧取景") && c.textContent.includes("清角色")))
    .map((c) => c.dataset.scene).join("/"));
ck("成人向卡都带「收紧取景」，且「清角色 / 角色生效」二选一",
  nearCards().filter((c) => nearPartOf(c.dataset.scene) === "🔞 成人向")
    .every((c) => c.textContent.includes("收紧取景")
      && (c.textContent.includes("清角色") || c.textContent.includes("角色生效"))));
ck("面部卡带「收紧取景」但**不**带「清角色」（角色与表情要保留）",
  nearCards().filter((c) => nearPartOf(c.dataset.scene) === "面部")
    .every((c) => c.textContent.includes("收紧取景")
      && !c.textContent.includes("清角色")));
ck("上半身与胸卡也不清角色",
  nearCards().filter((c) => nearPartOf(c.dataset.scene) === "上半身与胸")
    .every((c) => !c.textContent.includes("清角色")));
ck("按部位分组的小标题都在（八个部位，含臀部与成人向）",
  ["面部", "眼与唇", "上半身与胸", "手部", "腿部", "脚部", "臀部", "🔞 成人向"]
    .every((p) => [...panel.querySelectorAll(".av3-note")]
      .some((e) => (e.textContent || "").startsWith(p))),
  nearCards().length + " 张卡");

/* 部位筛选：点「腿部」只剩腿组 */
btnByText("腿部").click();
await sleep(40);
const legN = manualScenes.filter((s) => s.part === "腿部").length;
ck("部位筛选「腿部」只剩腿部条目",
  nearCards().length === legN
  && nearCards().every((c) => nearPartOf(c.dataset.scene) === "腿部"),
  `${nearCards().length} vs ${legN}`);
btnByText("全部").click();
await sleep(40);
ck("筛回「全部」恢复全部特写条数", nearCards().length === manualScenes.length,
  String(nearCards().length));

/* v3.44.0：部位筛选条也能整条收起（与场景页题材条同一套手感） */
const partTog = () => panel.querySelector("#av3-near-parttoggle");
const partBtns = () => [...panel.querySelectorAll("#av3-near-parts button")];
const nParts = (SCENE_FIX.near_parts || []).length;
ck("部位条有整条收起按钮，默认展开",
  /▾/.test(partTog()?.textContent || "") && partBtns().length === nParts + 2,
  `${partTog()?.textContent} / ${partBtns().length} 颗 / near_parts=${nParts}`);
partTog().click();
await sleep(30);
ck("部位条收起后只剩一颗按钮 + 摘要",
  partBtns().length === 1
  && /全部部位/.test(panel.querySelector("#av3-near-partsun")?.textContent || ""),
  `${partBtns().length} 颗 / `
  + `${panel.querySelector("#av3-near-partsun")?.textContent || ""}`);
ck("收起部位条不影响卡片（仍是全部特写）",
  nearCards().length === manualScenes.length, String(nearCards().length));
partTog().click();
await sleep(30);
btnByText("腿部").click();
await sleep(40);
partTog().click();
await sleep(30);
ck("收起后摘要显示当前部位",
  /当前：腿部/.test(panel.querySelector("#av3-near-partsun")?.textContent || ""),
  panel.querySelector("#av3-near-partsun")?.textContent || "（没有摘要）");
ck("收起后部位筛选仍生效",
  nearCards().length === legN
  && nearCards().every((c) => nearPartOf(c.dataset.scene) === "腿部"),
  `${nearCards().length} vs ${legN}`);
panel.querySelector("#av3-near-partclear").click();
await sleep(30);
ck("收起态能直接 ✕ 取消部位",
  !panel.querySelector("#av3-near-partclear")
  && nearCards().length === manualScenes.length,
  String(nearCards().length));
partTog().click();
await sleep(30);
ck("再展开部位条回来", partBtns().length === nParts + 2, String(partBtns().length));

/* 套用腿组：n_canon 命中 + ③② 段自动关 + 角色三件套清空（全部可恢复） */
const wOf = (name) => node.widgets.find((w) => w.name === name).value;
const faceBefore = Number(wjson().sections?.face ?? 1);
const hairBefore = Number(wjson().sections?.hair ?? 1);
// 先摆一份"用户自己的角色设置"进去，才能验证"清了"和"还回来了"
node.widgets.find((w) => w.name === "selected_roles").value = "hatsune miku";
node.widgets.find((w) => w.name === "role_works").value = "genshin impact";
const rolesBefore = String(wOf("selected_roles"));
const legCard = nearCards().find((c) => c.dataset.scene === "sc_near_leg_crossed")
  || nearCards().find((c) => nearPartOf(c.dataset.scene) === "腿部");
const legId = legCard.dataset.scene;
applyBtnOf(legCard).click();
const wN = wjson();
ck("套用特写：n_canon 字段权重 = 3.0", Number(wN.fields?.n_canon) === 3,
  JSON.stringify(wN.fields));
ck("套用特写：本条选项 = 3.0",
  Number(wN.options?.n_canon?.[legId]) === 3,
  JSON.stringify(wN.options?.n_canon?.[legId]));
ck("套用腿组：③ 五官与表情段被设为 0", Number(wN.sections?.face) === 0,
  JSON.stringify(wN.sections));
ck("套用腿组：② 头发段也被设为 0（发色也会锚住脸）",
  Number(wN.sections?.hair) === 0, JSON.stringify(wN.sections));
ck("套用腿组：④ 身材 ⑤ 妆容 段也被设为 0（v3.18.1 极简）",
  Number(wN.sections?.body) === 0 && Number(wN.sections?.makeup) === 0,
  JSON.stringify(wN.sections));
ck("套用腿组：竞争字段权重被设为 0（服装/身材/动作/设备/构图）",
  ["outfit", "top", "bottom", "figure", "action", "device", "comp"]
    .every((k) => Number(wN.fields?.[k]) === 0),
  JSON.stringify(wN.fields));
ck("套用腿组：人数钉死单人（1girl, solo = 3.0，其它 0）",
  Number(wN.options?.count?.["1girl, solo"]) === 3
  && Object.entries(wN.options?.count || {})
    .filter(([k]) => k !== "1girl, solo").every(([, v]) => Number(v) === 0),
  JSON.stringify(wN.options?.count));
ck("套用腿组：已选角色被清空", String(wOf("selected_roles") || "") === "",
  String(wOf("selected_roles")));
ck("套用腿组：限定作品池被清空", String(wOf("role_works") || "") === "",
  String(wOf("role_works")));
ck("套用腿组：role 被加进锁定字段（否则引擎仍会必抽 1 位角色）",
  /(^|[,\s])role([,\s]|$)/.test(String(wOf("lock_fields") || "")),
  String(wOf("lock_fields")));
ck("套用腿组：状态条明说收紧取景（不静默）",
  /收紧取景/.test(panel.querySelector("#av3-status")?.textContent || ""),
  panel.querySelector("#av3-status")?.textContent || "");
ck("特写页状态条显示当前套用",
  /当前套用/.test(panel.querySelector("#av3-near-cur")?.textContent || ""),
  panel.querySelector("#av3-near-cur")?.textContent || "");
ck("已套用卡按钮禁用",
  applyBtnOf(panel.querySelector(`.av3-sec[data-scene="${legId}"]`)).disabled === true);

[...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("取消套用")).click();
const wN2 = wjson();
ck("取消套用：n_canon 选项清空",
  !wN2.options?.n_canon || Object.keys(wN2.options.n_canon).length === 0,
  JSON.stringify(wN2.options?.n_canon));
ck("取消套用：③ 段恢复原值",
  Number(wN2.sections?.face ?? 1) === (faceBefore === 0 ? 1 : faceBefore),
  `${wN2.sections?.face} vs ${faceBefore}`);
ck("取消套用：② 段恢复原值",
  Number(wN2.sections?.hair ?? 1) === (hairBefore === 0 ? 1 : hairBefore),
  `${wN2.sections?.hair} vs ${hairBefore}`);
ck("取消套用：④⑤ 段 / 被收的字段 / 人数袋 全部还回去",
  wN2.sections?.body === undefined && wN2.sections?.makeup === undefined
  && wN2.fields?.outfit === undefined && wN2.fields?.figure === undefined
  && wN2.options?.count === undefined,
  JSON.stringify({ s: wN2.sections, f: wN2.fields, c: wN2.options?.count }));
ck("取消套用：角色选择原样还回去",
  String(wOf("selected_roles") || "") === rolesBefore
  && String(wOf("role_works") || "") === "genshin impact",
  `${wOf("selected_roles")} / ${wOf("role_works")}`);
ck("取消套用：锁定字段表也还回去（role 不残留）",
  !/(^|[,\s])role([,\s]|$)/.test(String(wOf("lock_fields") || "")),
  String(wOf("lock_fields")));
ck("取消后特写页状态条回到未套用",
  /未套用/.test(panel.querySelector("#av3-near-cur")?.textContent || ""),
  panel.querySelector("#av3-near-cur")?.textContent || "");

/* 套用面部组：角色与表情必须**保留**（需求 1） */
const faceCard = nearCards().find((c) => nearPartOf(c.dataset.scene) === "面部");
const faceId = faceCard.dataset.scene;
node.widgets.find((w) => w.name === "selected_roles").value = "hatsune miku";
const rolesFace = String(wOf("selected_roles"));
applyBtnOf(faceCard).click();
await sleep(30);
const wF = wjson();
ck("套用面部组：selected_roles **没被清空**", String(wOf("selected_roles")) === rolesFace,
  `${wOf("selected_roles")} vs ${rolesFace}`);
ck("套用面部组：没有把 role 加进锁定字段",
  !/(^|[,\s])role([,\s]|$)/.test(String(wOf("lock_fields") || "")),
  String(wOf("lock_fields")));
ck("套用面部组：② 头发 / ③ 五官段**保持不动**",
  wF.sections?.hair === undefined && wF.sections?.face === undefined,
  JSON.stringify(wF.sections));
ck("套用面部组：④ 身材 / ⑤ 妆容段被关",
  Number(wF.sections?.body) === 0 && Number(wF.sections?.makeup) === 0,
  JSON.stringify(wF.sections));
// ⚠️ `comp` 可能被预设自己写死（sc_near_face_classroom 就写了 comp=portrait），
//    那种字段会被 slimFieldsFor 自动保留 —— 所以只断言"一定该为 0"的那几个。
ck("套用面部组：姿势/手部/设备字段被收（不再拉成上半身）",
  ["action", "arms_hands", "device"].every((k) => Number(wF.fields?.[k]) === 0),
  JSON.stringify(wF.fields));
ck("套用面部组：看不见的服装与鞋袜权重为 0（正文不再描述画面外）",
  ["outfit", "top", "bottom", "socks", "shoes", "leg"].every((k) => Number(wF.fields?.[k]) === 0),
  JSON.stringify(wF.fields));
ck("面部组状态条也是「收紧取景」",
  /收紧取景/.test(panel.querySelector("#av3-status")?.textContent || ""),
  panel.querySelector("#av3-status")?.textContent || "");
[...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("取消套用")).click();
await sleep(20);
ck("取消后角色与段权重都还回去（面部组）",
  String(wOf("selected_roles")) === rolesFace
  && wjson().sections?.body === undefined,
  JSON.stringify(wjson().sections));

/* 成人向：有脸条目保留角色 + 双女人数钉死（v3.18.3） */
btnByText("🔞 成人向").click();
await sleep(40);
ck("成人向分组里也有「🎭 角色来源」栏",
  !!panel.querySelector("#av3-near-rolesrc"),
  panel.querySelector("#av3-near-rolesrc")?.textContent || "（没有）");
ck("成人向的角色来源标题写明「仅标了角色生效的条目」",
  /角色生效/.test(panel.querySelector("#av3-near-rolelabel")?.textContent || ""),
  panel.querySelector("#av3-near-rolelabel")?.textContent || "");
const adultCard = (id) => panel.querySelector(`.av3-sec[data-scene="${id}"]`);
ck("口交特写标了「🎭 角色生效」",
  /角色生效/.test(adultCard("sc_near_nsfw_fellatio")?.textContent || ""),
  adultCard("sc_near_nsfw_fellatio")?.textContent?.slice(0, 80));
ck("乳首特写仍是「🧹 清角色」（无脸）",
  /清角色/.test(adultCard("sc_near_nsfw_nipple")?.textContent || "")
  && !/角色生效/.test(adultCard("sc_near_nsfw_nipple")?.textContent || ""),
  adultCard("sc_near_nsfw_nipple")?.textContent?.slice(0, 80));
ck("舔阴特写标了「👭 双女」",
  /双女/.test(adultCard("sc_near_nsfw_cunnilingus")?.textContent || ""),
  adultCard("sc_near_nsfw_cunnilingus")?.textContent?.slice(0, 80));

/* 切到过激档才套得动 L3 的双女条目 */
lvBtn("过激").click();
await sleep(50);
nearTab.click();
await sleep(30);
btnByText("🔞 成人向").click();
await sleep(40);
const cuCard = panel.querySelector('.av3-sec[data-scene="sc_near_nsfw_cunnilingus"]');
ck("过激档下双女条目可见", !!cuCard);
node.widgets.find((w) => w.name === "selected_roles").value = "hatsune miku";
applyBtnOf(cuCard).click();
await sleep(30);
const wCu = wjson();
ck("双女套用后人数钉死 2girls, yuri",
  Number(wCu.options?.count?.["2girls, yuri"]) === 3
  && Object.entries(wCu.options?.count || {})
    .filter(([k]) => k !== "2girls, yuri").every(([, v]) => Number(v) === 0),
  JSON.stringify(wCu.options?.count));
ck("已选角色只有 1 位 → 被清空（让引擎按 IP/全库抽两位）",
  String(wOf("selected_roles") || "") === "", String(wOf("selected_roles")));
ck("状态条说明清空原因",
  /不足 2 位/.test(panel.querySelector("#av3-status")?.textContent || ""),
  panel.querySelector("#av3-status")?.textContent || "");
ck("双女条目没有把 role 锁死（要抽两位角色）",
  !/(^|[,\s])role([,\s]|$)/.test(String(wOf("lock_fields") || "")),
  String(wOf("lock_fields")));
[...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("取消套用")).click();
await sleep(20);
ck("取消后人数袋与角色都还回去",
  wjson().options?.count === undefined
  && String(wOf("selected_roles") || "") === "hatsune miku",
  `${JSON.stringify(wjson().options?.count)} / ${wOf("selected_roles")}`);
lvBtn("全年龄").click();
await sleep(40);
nearTab.click();
await sleep(30);

/* 基线持久化（v3.18.5）—— 修"腿部服装随机不生效" */
node.widgets.find((w) => w.name === "lock_fields").value = "";
btnByText("全部").click();
await sleep(30);
const faceCard5 = nearCards().find((c) => c.dataset.scene === "sc_near_face_classroom");
applyBtnOf(faceCard5).click();
await sleep(40);
const wFace = wjson();
ck("套用面部后 socks/shoes 权重被清零（白名单不含袜鞋）",
  Number(wFace.fields?.socks) === 0 && Number(wFace.fields?.shoes) === 0,
  JSON.stringify({ socks: wFace.fields?.socks, shoes: wFace.fields?.shoes }));
ck("清零前的原值写进 weights_json 的 _nearBase（刷新也还原得回来）",
  !!(wFace._nearBase && wFace._nearBase.fields),
  Object.keys(wFace._nearBase || {}).join(","));
ck("_nearBase 记下了 socks/shoes 的原始值",
  "socks" in (wFace._nearBase?.fields || {}) && "shoes" in (wFace._nearBase?.fields || {}),
  JSON.stringify(wFace._nearBase?.fields || {}).slice(0, 120));

/* 不取消、直接换套腿部 —— 旧实现若内存快照丢了就永远恢复不回来 */
// v3.38.1：部分腿部条目改成"不穿鞋"，闭麦了 shoes —— 它们本来就会让 shoes 停在 0，
// 不能再拿"任意第一条腿部"当恢复样本，这里指定一条未闭麦鞋的腿部条目。
const legCard3 = nearCards().find((c) => c.dataset.scene === "sc_near_leg_crossed")
  || nearCards().find((c) => nearPartOf(c.dataset.scene) === "腿部");
applyBtnOf(legCard3).click();
await sleep(40);
const wLeg = wjson();
ck("换套腿部后 socks/shoes 权重恢复（不再是 0）",
  Number(wLeg.fields?.socks ?? 1) !== 0 && Number(wLeg.fields?.shoes ?? 1) !== 0,
  JSON.stringify({ socks: wLeg.fields?.socks, shoes: wLeg.fields?.shoes }));
ck("腿部条目自身仍保留袜鞋字段（白名单里没漏）",
  Number(wLeg.fields?.socks ?? 1) !== 0,
  JSON.stringify(wLeg.fields));

[...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("取消套用")).click();
await sleep(30);
const wEnd = wjson();
ck("取消套用后 _nearBase 从 weights_json 消失", !wEnd._nearBase,
  JSON.stringify(wEnd._nearBase || "none"));
ck("取消套用后 socks/shoes 不再是 0",
  Number(wEnd.fields?.socks ?? 1) !== 0 && Number(wEnd.fields?.shoes ?? 1) !== 0,
  JSON.stringify({ socks: wEnd.fields?.socks, shoes: wEnd.fields?.shoes }));

/* 切回场景页，确认两页互不干扰 */
tabBtns.find((b) => b.textContent.includes("场景搭配")).click();
await sleep(40);
await loadAllScenes();       // 懒加载：全量断言前先放出来
ck("切回场景页后卡片数仍是非特写数",
  sceneCards().length === nonManualCount, `${sceneCards().length} vs ${nonManualCount}`);

/* v3.25.0：关闭前把界面调成一个"可辨识"的状态，供后面验证记忆 */
const poseBtn = [...panel.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("姿势场景"));
if (poseBtn) { poseBtn.click(); await sleep(40); }
// ⚠️ 点完 renderScenes() 会整块重建筛选条，旧引用是**游离节点**，
//    必须重新查一次才能读到选中态（否则永远看到旧 class）。
const poseBtnAfter = [...document.body.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("姿势场景"));
ck("关闭前已切到「🧎 姿势场景」筛选",
  !!poseBtnAfter && poseBtnAfter.classList.contains("pri"),
  poseBtnAfter ? poseBtnAfter.className : "无该按钮");

/* ── 11. 关闭面板 ────────────────────────────────────────────────── */
[...panel.querySelectorAll(".av3-btn")].find((b) => b.textContent === "关闭").click();
// 10.9 之一里为兼容断言开过第二个面板（oldNode 的），一并关掉
[...document.body.querySelectorAll(".av3-mask .av3-btn")]
  .filter((b) => b.textContent === "关闭").forEach((b) => b.click());
ck("面板已关闭", !document.body.querySelector(".av3-mask"));

/* ── 12. v3.25.0 界面记忆：关掉再打开，回到上次那一幕 ─────────────── */
const memo = wjson()._ui || {};
ck("关闭时把界面记忆写进 weights_json._ui", !!memo && typeof memo === "object",
  JSON.stringify(memo).slice(0, 120));
ck("记住的页签是「场景搭配」", memo.tab === "scenes", String(memo.tab));
ck("记住的场景筛选是「姿势场景」", memo.sceneGroup === "pose", String(memo.sceneGroup));
// v3.44.0：两条筛选条的收起态也要跟着记（否则每次重开都回到展开）
ck("记住的题材条 / 部位条收起态都是布尔",
  typeof memo.sceneThemeOpen === "boolean" && typeof memo.nearPartOpen === "boolean",
  JSON.stringify({ t: memo.sceneThemeOpen, p: memo.nearPartOpen }));
ck("记住的展开态是数组（段的 openSecs）", Array.isArray(memo.openSecs),
  JSON.stringify(memo.openSecs));
ck("记住的滚动是比例 0–1（left / right）",
  !!memo.scroll && Number(memo.scroll.left) >= 0 && Number(memo.scroll.left) <= 1
  && Number(memo.scroll.right) >= 0 && Number(memo.scroll.right) <= 1,
  JSON.stringify(memo.scroll));

openBtn.callback();
for (let i = 0; i < 80 && !document.body.querySelector(".av3-panel"); i++) {
  await new Promise((r) => setTimeout(r, 10));
}
const panel2 = document.body.querySelector(".av3-panel");
ck("面板重新打开", !!panel2);
const onTab2 = panel2 && [...panel2.querySelectorAll(".av3-tabs button")]
  .find((b) => b.classList.contains("on"));
ck("重开后停在上次的页签（场景搭配）",
  !!onTab2 && onTab2.textContent.includes("场景搭配"),
  onTab2 ? onTab2.textContent : "无");
await sleep(120);
const poseBtn2 = panel2 && [...panel2.querySelectorAll(".av3-btn")]
  .find((b) => b.textContent.includes("姿势场景"));
ck("重开后「姿势场景」筛选仍是选中态",
  !!poseBtn2 && poseBtn2.classList.contains("pri"),
  poseBtn2 ? poseBtn2.className : "无");

/* 收尾前把第二个面板也关掉，避免残留 mask 影响后续断言 */
[...document.body.querySelectorAll(".av3-mask .av3-btn")]
  .filter((b) => b.textContent === "关闭").forEach((b) => b.click());
ck("重开的面板已关闭", !document.body.querySelector(".av3-mask"));

/* ── 收尾 ────────────────────────────────────────────────────────── */
fs.rmSync(TMP, { recursive: true, force: true });
console.log(`\n[av3_ui_smoke] 通过 ${PASS} / 失败 ${FAILS.length}`);
if (FAILS.length) {
  console.log("失败用例：" + FAILS.join(" · "));
  process.exit(1);
}
process.exit(0);
