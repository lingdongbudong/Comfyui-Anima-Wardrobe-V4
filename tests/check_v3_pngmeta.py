# -*- coding: utf-8 -*-
"""PNG 元数据注入基线（v3.6.0 起：把插件正文写进 workflow / prompt）。

用户报障：出图后看图工具里「正向提示词」只有 `masterpiece, best quality`（质量词）。
解剖真实出图后确认 **不是被截断，是正文一个字都没进元数据** —— 本测试就是钉住这个病
与它的修复，外加"没把别的东西写坏"。

v3.7.0 追加：第 ⑨ 组**复刻看图工具（ComfyUIGallery v1.4.6）的读法** ——
它读的是「正向上游链路上 StringConcat 的 widgets_values[0]」，而不是终点编码。

夹具 `tests/fixtures/anima_v4_workflow.json` / `anima_v4_prompt.json`
是**从真实出图的 PNG 里导出来的**（`tools/export_pngmeta_fixture.py`）——
手搓一份工作流测的是想象出来的链路，形状必然被简化掉。

跑法：python tests/check_v3_pngmeta.py
"""
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

PM = _boot.load("anima_v4_pngmeta")

FIX = os.path.join(HERE, "fixtures")
WF_PATH = os.path.join(FIX, "anima_v4_workflow.json")
PR_PATH = os.path.join(FIX, "anima_v4_prompt.json")

FAILS = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(name)


TEXT = "1girl, solo, hakurei reimu, long black hair, red eyes, sleeping on side"
PLUGIN_NODE = "1139"          # AnimaV4RandomPrompt 在真图里的节点 id
CR_TEXT = 1004                # 承接插件输出的 CR Text
JOIN_NODES = [1070, 1073, 1076, 1079, 1082, 1085]   # 「触发词+质量词 → 全局正文 拼接」
AUTO_NODES = [1016, 1025, 1034, 1043, 1052, 1061]   # 「自动拼接：官方质量词（本流）+ 全局正文」
POS_CE = [1017, 1026, 1035, 1044, 1053, 1062]       # 「正向条件（自动拼接）」
NEG_CE = [1018, 1027, 1036, 1045, 1054, 1063]       # 「负向词（官方，本流）」


def nodes_of(wf):
    return {n["id"]: n for n in (wf.get("nodes") or [])}


def wv(node, idx=0):
    v = node.get("widgets_values")
    return v[idx] if isinstance(v, list) and idx < len(v) else None


def wvn(node, name):
    d = node.get("widgets_values_named")
    return d.get(name) if isinstance(d, dict) else None


def strip_text_widgets(wf):
    """把所有**文本控件**的值抹平，用于证明"其余控件一位没动"。"""
    d = copy.deepcopy(wf)
    for n in (d.get("nodes") or []):
        t = n.get("type")
        spec = PM.WIDGET_INDEX.get(t)
        if not spec:
            continue
        vals = n.get("widgets_values")
        if isinstance(vals, list):
            for _wn, idx in spec.items():
                if idx < len(vals):
                    vals[idx] = "§"
        named = n.get("widgets_values_named")
        if isinstance(named, dict):
            for wn in spec:
                if wn in named:
                    named[wn] = "§"
    return d


def main():
    for p in (WF_PATH, PR_PATH):
        if not os.path.exists(p):
            print(f"缺夹具 {os.path.basename(p)}，先跑：python tools/export_pngmeta_fixture.py")
            return 2

    raw = json.load(open(WF_PATH, encoding="utf-8"))
    raw_pr = json.load(open(PR_PATH, encoding="utf-8"))
    N0 = nodes_of(raw)

    # ── ① 先把"病"钉死：正文确实一个字都没进元数据 ──────────────────
    print("── ① 注入前：确认病存在 ──")
    ck("夹具里有本插件的节点", any(n.get("type") == "AnimaV4RandomPrompt"
                                  for n in raw["nodes"]))
    ck("插件节点自己不承载正文（正文预览是 serialize:false 的 DOM widget）",
       all(not isinstance(v, str) or len(v) < 40
           for v in (N0[1139].get("widgets_values") or [])))
    ck("CR Text(1004) 的 text 是空串（正文在连线上）",
       wv(N0[CR_TEXT]) == "" and wvn(N0[CR_TEXT], "text") == "",
       repr(wv(N0[CR_TEXT])))
    ck("6 个「拼接」节点的 string_b 全是空串",
       all(wv(N0[i], 1) == "" for i in JOIN_NODES))
    ck("6 个正向 CLIPTextEncode 的 text 全是空串",
       all(wv(N0[i]) == "" for i in POS_CE))
    ck("只有「自动拼接」节点里有质量词字面量（看图工具就挑了这种）",
       all(isinstance(wv(N0[i]), str) and wv(N0[i]).strip() for i in AUTO_NODES)
       and all(wv(N0[i], 1) == "" for i in AUTO_NODES))

    # ── ② 注入 ──────────────────────────────────────────────────────
    print("\n── ② 注入 ──")
    wf = copy.deepcopy(raw)
    extra = {"workflow": wf}
    prompt = copy.deepcopy(raw_pr)
    st = PM.inject_metadata(extra, prompt, TEXT, self_ids={PLUGIN_NODE},
                            version="3.7.0-test")
    w = st["workflow"]
    ck("注入成功（workflow ok）", bool(w and w.get("ok")), str(w))
    ck("写入了足够多的落点（≥15 处）", len(w["written"]) >= 15, str(len(w["written"])))
    ck("认出 6 个终点正向编码", w["encoders"] == 6, str(w["encoders"]))

    f = nodes_of(wf)
    ck("★ CR Text(1004).text == 正文（widgets_values + named 两份都写）",
       wv(f[CR_TEXT]) == TEXT and wvn(f[CR_TEXT], "text") == TEXT,
       f"{wv(f[CR_TEXT])!r} / {wvn(f[CR_TEXT],'text')!r}")
    ck("★ 6 个「拼接」节点的 string_b 都写成了正文",
       all(wv(f[i], 1) == TEXT for i in JOIN_NODES),
       str([wv(f[i], 1)[:20] for i in JOIN_NODES]))
    ck("★ 6 个正向 CLIPTextEncode 都是「该流质量词 + 正文」",
       all((wv(f[i]) or "").startswith(wv(N0[i], 0))
           and (wv(f[i]) or "").endswith(TEXT) for i in POS_CE),
       str([(wv(f[i]) or "")[-30:] for i in POS_CE]))
    ck("★ 看图工具实际挑的那个节点（#1052）现在能读到正文",
       TEXT in (wv(f[1052]) or "") or wv(f[1052], 1) == TEXT,
       str(wv(f[1052]))[:80])
    ck("正向编码里给出了 named 版 text",
       all(wvn(f[i], "text") == wv(f[i]) for i in POS_CE))

    # ── ③ 不越界（这是"避免影响其他现有功能"的核心）────────────────
    print("\n── ③ 不越界 ──")
    ck("★ 各流自己的质量词**仍作为前缀保留**"
       "（v3.7.0 把它扩展成完整正向，而不是覆盖掉）",
       all((wv(f[i], 0) or "").startswith(wv(N0[i], 0)) for i in AUTO_NODES),
       str([(wv(f[i], 0) or "")[:24] for i in AUTO_NODES]))
    ck("分隔符 delimiter 全都没动",
       all(wv(f[i], 2) == wv(N0[i], 2) for i in AUTO_NODES + JOIN_NODES))
    ck("负向 CLIPTextEncode 的 text 一个字都没动",
       all(wv(f[i]) == wv(N0[i]) for i in NEG_CE),
       str([wv(f[i])[:24] for i in NEG_CE]))
    ck("插件节点自己的控件值零改动（不能把正文写进出题参数）",
       f[1139].get("widgets_values") == N0[1139].get("widgets_values")
       and f[1139].get("widgets_values_named") == N0[1139].get("widgets_values_named"))
    ck("插件节点的 nsfw_level / base_prob 等仍是原值",
       wv(f[1139], 0) == "any" and wv(f[1139], 4) == 0.3,
       f"{wv(f[1139],0)!r} / {wv(f[1139],4)!r}")
    ck("★ 除文本控件外，整份工作流逐字节一致",
       json.dumps(strip_text_widgets(wf), sort_keys=True)
       == json.dumps(strip_text_widgets(raw), sort_keys=True))
    bad_writes = []
    for item in w["written"]:
        m = re.match(r"^([^#]+)#(\d+)\.([A-Za-z_]+)", item)
        if not m:
            bad_writes.append(item)
            continue
        if m.group(3) not in (PM.WIDGET_INDEX.get(m.group(1)) or {}):
            bad_writes.append(item)
    ck("每一处写入都落在白名单控件上", not bad_writes, str(bad_writes[:4]))
    ck("_set_widget 拒绝白名单外的控件名",
       PM._set_widget({"type": "UNKNOWN_NODE", "widgets_values": ["x"]},
                      "text", TEXT) is False)

    # ── ④ 专用 tEXt 键 + 配对负向 ───────────────────────────────────
    print("\n── ④ 专用键与配对负向 ──")
    meta = extra.get(PM.TEXT_KEY)
    ck("往 extra_pnginfo 加了专用键（SaveImage 会写成同名 tEXt 块）",
       isinstance(meta, dict))
    ck("专用键里 positive == 正文原值", meta.get("positive") == TEXT)
    ck("专用键里 positive_full 是「质量词 + 正文」",
       (meta.get("positive_full") or "").endswith(TEXT)
       and (meta.get("positive_full") or "").strip() != TEXT,
       str(meta.get("positive_full"))[:90])
    ck("★ 专用键里 negative 是**配对读回**的负向（非空、来自负向节点）",
       bool(meta.get("negative")) and meta["negative"].startswith("worst quality"),
       str(meta.get("negative"))[:70])
    ck("专用键带 schema / plugin / version",
       meta.get("schema") == PM.META_SCHEMA
       and meta.get("plugin") == "Comfyui-Anima-Wardrobe-V4"
       and meta.get("version") == "3.7.0-test")

    # ── ⑤ 幂等 ──────────────────────────────────────────────────────
    print("\n── ⑤ 幂等 ──")
    st2 = PM.inject_workflow_text(wf, TEXT, self_ids={PLUGIN_NODE})
    ck("同一份工作流再注入一次 → 0 处改动", len(st2["written"]) == 0,
       str(st2["written"][:3]))
    wf_b = copy.deepcopy(raw)
    PM.inject_workflow_text(wf_b, TEXT, self_ids={PLUGIN_NODE})
    ck("两次独立注入结果一致（确定性）",
       json.dumps(wf_b, sort_keys=True) == json.dumps(wf, sort_keys=True))

    # ── ⑥ API prompt：只写惰性键 ────────────────────────────────────
    print("\n── ⑥ API 执行图只加惰性键 ──")
    added = []
    for nid, nd in prompt.items():
        orig = raw_pr.get(nid, {}).get("inputs", {})
        cur = nd.get("inputs", {})
        added += sorted(set(cur) - set(orig))
    ck("新增的输入名只有惰性键", set(added) <= {PM.INJECT_KEY},
       str(sorted(set(added))))
    changed = []
    for nid, nd in prompt.items():
        oi = (raw_pr.get(nid, {}) or {}).get("inputs") or {}
        ci = nd.get("inputs") or {}
        for k, v in oi.items():
            if k not in ci or json.dumps(ci[k], sort_keys=True) != json.dumps(v, sort_keys=True):
                changed.append(f"{nid}.{k}")
    ck("★ 已声明的输入值**一个都没被改**（改了会直接改坏出图）",
       not changed, str(changed[:5]))
    ck("惰性键的值是可解析的 JSON（含 positive）",
       (lambda v: isinstance(v, str) and json.loads(v).get("positive") == TEXT)(next(
           (nd["inputs"][PM.INJECT_KEY] for nd in prompt.values()
            if isinstance(nd.get("inputs"), dict) and PM.INJECT_KEY in nd["inputs"]),
           None)))

    # ── ⑦ 异常安全 ──────────────────────────────────────────────────
    print("\n── ⑦ 异常安全（元数据写不进去绝不能把出图搞挂）──")
    for label, args in (
        ("extra_pnginfo=None", (None, prompt, TEXT)),
        ("prompt=None", ({"workflow": copy.deepcopy(raw)}, None, TEXT)),
        ("正文为空", ({"workflow": copy.deepcopy(raw)}, None, "")),
        ("workflow 是乱结构", ({"workflow": "not a dict"}, None, TEXT)),
        ("workflow 没有 nodes", ({"workflow": {"nodes": []}}, None, TEXT)),
        ("工作流里没有本插件节点",
         ({"workflow": {"nodes": [{"id": 1, "type": "KSampler"}], "links": []}},
          None, TEXT)),
    ):
        try:
            r = PM.inject_metadata(*args)
            ok = isinstance(r, dict)
        except Exception as e:
            ok = False
            r = e
        ck(f"不抛异常：{label}", ok, str(r))
    ck("空正文时 workflow 统计给出 reason 而不是崩",
       (PM.inject_workflow_text(copy.deepcopy(raw), "") or {}).get("reason") == "正文为空")

    # ── ⑧ 读回与接线 ────────────────────────────────────────────────
    print("\n── ⑧ 读回 + 节点接线 ──")
    back = PM.dump_workflow_prompt(wf)
    ck("dump_workflow_prompt 能读回含正文的串", TEXT in back, back[:70])
    src = open(os.path.join(PLUGIN, "nodes.py"), encoding="utf-8").read()
    ck("nodes.py 声明了 hidden 输入 EXTRA_PNGINFO",
       '"extra_pnginfo": "EXTRA_PNGINFO"' in src)
    ck("nodes.py 声明了 hidden 输入 PROMPT / UNIQUE_ID",
       '"prompt": "PROMPT"' in src and '"unique_id": "UNIQUE_ID"' in src)
    ck("nodes.py 真的调用了注入入口",
       bool(re.search(r"PM\.inject_metadata\(", src)))
    ck("注入被 try/except 包住（失败不影响出图）",
       bool(re.search(r"try:\s*\n\s+st = PM\.inject_metadata\(", src)))

    # ── ⑨ 复刻看图工具的读法（v3.7.0 的核心）─────────────────────────
    #
    # 实测证据（对 ComfyUIGallery v1.4.6 的 /api/inspect 做对照实验，可复现）：
    #   · 改终点 CLIPTextEncode.text / CR Text.text / API prompt / A1111 `parameters`
    #     块 / 本插件自己的 anima_v4_prompt → 它显示的**一个字都不变**；
    #   · 只改 StringConcatenate 的 `widgets_values[0]` → 它立刻跟着变；
    #   · 它不是"挑一个"，而是把正向上游链路上**每个** StringConcat 的
    #     `widgets_values[0]` 按「上游 → 下游」拼起来（打标记实验显示 "A43A79"）。
    # 所以这里把它的读法**复刻成断言**：以后谁把注入逻辑改回只写终点编码，
    # 这一组会立刻转红。
    print("\n── ⑨ 复刻看图工具的读法 ──")

    def tool_pos(wf_, ce_id):
        """复刻图库工具：正向上游链路上所有 StringConcat 的 wv[0]，上游→下游拼接。"""
        ns = nodes_of(wf_)
        _, s2 = PM._link_maps(wf_)
        chain, seen2 = [], set()

        def walk(node, d=0):
            if not isinstance(node, dict) or d > 8 or node.get("id") in seen2:
                return
            seen2.add(node.get("id"))
            if node.get("type") == "StringConcatenate":
                v = wv(node, 0)
                if isinstance(v, str):
                    chain.append(v)
            for nm in ("string_a", "string_b", "text"):
                inp = PM._input_by_name(node, nm)
                if isinstance(inp, dict) and inp.get("link") is not None:
                    up = s2.get(inp["link"])
                    if up:
                        walk(ns.get(up[0]), d + 1)

        walk(ns.get(ce_id))
        return "".join(reversed(chain))          # 上游在前

    pre = tool_pos(raw, 1044)
    ck("★ 注入前用它的读法**读不到正文**（复现用户报障）",
       TEXT not in pre and bool(pre.strip()), repr(pre[:70]))
    post = tool_pos(wf, 1044)
    ck("★ 注入后同一读法能读到**完整正向**（含正文）",
       TEXT in post and len(post) > len(pre), repr(post[:90]))
    ck("★ 完整正向以该流质量词开头（质量词没被丢掉）",
       post.startswith(wv(N0[1043], 0)), repr(post[:40]))
    ck("★ 正文只出现一次（下游连线位没被写，不会拼出重复）",
       post.count(TEXT) == 1, f"出现 {post.count(TEXT)} 次")
    ck("图库工具读的那一位（#1043.string_a）就是完整正向",
       wv(f[1043], 0) == post, repr(wv(f[1043], 0)[:60]))
    ck("上游拼接位也同步写了 named 版 string_a",
       all(wvn(f[i], "string_a") == wv(f[i], 0) for i in AUTO_NODES))

    print("\n" + "=" * 64)
    if FAILS:
        print(f"[check_v3_pngmeta] 失败 {len(FAILS)} 项：" + " · ".join(FAILS))
        return 1
    print("[check_v3_pngmeta] 通过：9 组语义全部符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
