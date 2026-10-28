# -*- coding: utf-8 -*-
"""Comfyui-Anima-Wardrobe-V4 :: 把插件产出的正文写进 PNG 元数据（v3.6.0 新增模块）

作者：灵冻不冻 ｜ 插件底层框架源于脚本：ANIMA提示词生成器.html 已授权开源 —— 作者：飞蓬。


【为什么要这个模块】
用户报障：出图后看图工具里这张图的「正向提示词」不完整 —— 只显示成
`masterpiece, best quality`（那只是质量词）。解剖真实出图
（output/Anima/oneObsession_00001_.png）后确认：**不是被截断，是正文一个字都没进元数据**：

    #1139 AnimaV4RandomPrompt   widgets_values 13 个值里**没有任何文本位**
                                （正文预览框是 serialize:false 的 DOM widget，从不进元数据）
    #1004 CR Text               [""] / {"text": ""}            ← 空串（text 是连线）
    #1079 StringConcatenate     ["", "", ", "]                 ← 两段都空（都是连线）
    #1044 CLIPTextEncode 正向    [""]                          ← 空串（text 是连线）
    #1052 StringConcatenate      ["masterpiece, best quality"]  ← 链上唯一"有字"的

链路：插件 → CR Text(1004) → StringConcatenate(1079「触发词+质量词 → 全局正文 拼接」)
      → CLIPTextEncode(1044 正向条件) → 采样器 → 解码 → SaveImage。
文本全程只在连线上流动，所以看图工具读不到，就退而取了链上唯一有字的质量词节点。

（这与 Comfyui-Krea2-Portrait-V3 的 `k2_v3_pngmeta.py` 是**同一个病**，
本模块是它在 Anima 链路下的适配版，思路一致。）


【怎么修：注入 extra_pnginfo】
`extra_data['extra_pnginfo']` 是**同一次执行中所有节点共享的同一个 dict**，而原生
SaveImage 是在**自己执行的那一刻**才 `json.dumps(extra_pnginfo["workflow"])`。
插件节点只要在运行时把文本写进这个 dict，SaveImage 就会照常写进 PNG：

    ✅ 当次出图就生效
    ✅ 用户工作流**一根线都不用改**
    ✅ 不碰任何第三方节点（Reroute / StringConcatenate / CR Text 都只是被"填空白"）
    ✅ 完全不影响出图结果（`workflow` 是 UI JSON，ComfyUI 从不拿它跑图）

本插件的正文链条还保证了**执行顺序**：插件在上游（正文要流到采样器），
必然早于 SaveImage 执行，不存在"注入太晚"的问题。


【写哪三个落点（与用户确认过的口径：分位置写真值）】
  ① 承载位 —— 顺着连线往下，正文真正流经的那些文本控件，写**正文原值**
     （CR Text 的 text、StringConcatenate 里接收正文的那个 string_a/string_b）；
  ② 终点位 —— 喂给采样器 `positive` 的 CLIPTextEncode.text，写**尽力还原的完整正向**
     （该流质量词 + 正文；中间若有第三方节点（如 LoraManager 触发词）运行时才有值，
      插件无从得知，按空串处理）；
  ③ 兜底位 —— 链上其它文本节点里**当前为空**的文本位，也填上**正文原值**。
     ⚠️ 只填**空位**，绝不覆盖任何已有字面量（不篡改用户写死的质量词）。
  ④ 上游拼接位（v3.7.0 追加）—— 正向上游链路上 `StringConcatenate` 里**已有字面量**
     的 `widgets_values[0]`（string_a），改写成**这条链的完整正向**（质量词 + 正文）。
     为什么非有不可：图库/看图工具（实测 ComfyUIGallery v1.4.6）读的**既不是**
     终点 CLIPTextEncode、**也不是** CR Text，而是「正向上游那个拼接节点的
     `widgets_values[0]`」；而 Anima 工作流里那个位置恰好只放着质量词 ——
     用户看到的就永远只有 `masterpiece, best quality`。
     ⚠️ 只改**原本非空**的（字面量）位；空着的（连线位）不动 —— 那才是它本来的
        样子，且工具会把空位也拼上去，写了会造成「正文正文」重复。

另外写一个**专用 tEXt 键** `anima_v4_prompt`（往 extra_pnginfo 加一个顶层键，
SaveImage 会照原生约定把它一起写进 PNG），内容是结构化 JSON：
正文原值 + 尽力完整正向 + **配对的负向**（顺着采样器的 `negative` 输入读回来）。
这样"读自定义键"的工具、以及我们自己排查，都有个明确入口。


【安全边界（很重要，改这个文件前务必读完）】
· `workflow`（UI JSON）**只用于展示** → 可以写。
· `prompt`（API JSON）**就是执行用的那张图** → **只写惰性键** `anima_v4_prompt`。
  依据：`get_input_data` 是 `for x in inputs:` 逐个查 `get_input_info()`，未声明的
  输入名拿不到 input_category、**不进 input_data_all**，执行期静默忽略。
  ⚠️ 绝不把 `CLIPTextEncode.inputs.text` 从连线改成字面量 —— 那会真的改坏出图。

本模块只依赖标准库，纯逻辑环境下也能 import 与单测。
"""

import json

# 写进 API prompt 的惰性键名（执行的节点读不到它，见上面「安全边界」）
INJECT_KEY = "anima_v4_prompt"
# v4.0.0 改名兼容：旧图（以及用户自己的外部脚本/图库工具）读的是 `anima_v3_prompt`。
# 两个键**都写** —— 读端不用改，写端零成本。将来真要废掉 v3 键，得先确认没人读。
LEGACY_INJECT_KEY = "anima_v3_prompt"

# 写进 extra_pnginfo 的顶层键 → SaveImage 会把它写成同名 PNG tEXt 块
TEXT_KEY = "anima_v4_prompt"
LEGACY_TEXT_KEY = "anima_v3_prompt"

META_SCHEMA = "anima-v3/pngmeta@1"


# ---------------------------------------------------------------------------
# 节点类型表
# ---------------------------------------------------------------------------

# 插件自己的节点：「正文」是第几个输出端口。AnimaV4RandomPrompt 的 RETURN_NAMES =
# (text, report, level, cn_summary) → text 在 0。
OWN_TEXT_OUTPUT_SLOT = {
    "AnimaV4RandomPrompt": 0,
}

# ⚠️ 故意**不**给插件节点配 OWN_TEXT_WIDGET：它的 widgets_values 前几位是
#    nsfw_level / seed / tag_cap / base_prob …，正文写进任何一位都会改坏出题参数。
OWN_TEXT_WIDGET = {}

# 每个节点类型：widget 名 → 在 `widgets_values` 里的位置索引。
# 同时充当**白名单**：表里没有的输入名一律不写（不猜、不碰别人的控件）。
WIDGET_INDEX = {
    "CLIPTextEncode": {"text": 0},
    "CR Text": {"text": 0},
    "StringConcatenate": {"string_a": 0, "string_b": 1, "delimiter": 2},
    "PrimitiveString": {"value": 0},
    "PrimitiveStringMultiline": {"value": 0},
    "String": {"value": 0},
    "ShowText|pysssss": {"text": 0},
}

# 哪些输入名可以"继续往下传"（delimiter 不在内 —— 正文不会流进分隔符）
PROPAGATE_INPUTS = {"value", "string_a", "string_b", "text", "string"}

# 只把文本往下传、不改变内容的节点（Reroute 之类）
PASS_THROUGH_TYPES = {"Reroute", "ReroutePrimitive|pysssss", "PrimitiveNode"}

# 终点：它的输出是 CONDITIONING 而不是文本，跟进它没有意义
TERMINAL_TYPES = {"CLIPTextEncode", "CLIPTextEncodeSDXL",
                  "CLIPTextEncodeSDXLRefiner", "BNK_CLIPTextEncodeAdvanced"}

# 单文本控件节点的"文本控件名"（按优先级）
SINGLE_TEXT_KEYS = ("text", "string", "value")


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _node_index(workflow):
    out = {}
    for n in (workflow.get("nodes") or []):
        if isinstance(n, dict) and n.get("id") is not None:
            out[n["id"]] = n
    return out


def _link_maps(workflow):
    """返回 (下游表, 上游表)。

    下游表：(起点节点 id, 起点槽位) -> [(终点节点 id, 终点槽位), …]
    上游表：link_id -> (起点节点 id, 起点槽位)
    """
    downstream, src = {}, {}
    for L in (workflow.get("links") or []):
        if not isinstance(L, (list, tuple)) or len(L) < 5:
            continue
        downstream.setdefault((L[1], L[2]), []).append((L[3], L[4]))
        src[L[0]] = (L[1], L[2])
    return downstream, src


def _input_at(node, slot):
    """取节点第 slot 个输入定义（dict）；越界返回 {}。"""
    ins = node.get("inputs") or []
    if isinstance(slot, int) and 0 <= slot < len(ins) and isinstance(ins[slot], dict):
        return ins[slot]
    return {}


def _input_by_name(node, name):
    for inp in (node.get("inputs") or []):
        if isinstance(inp, dict) and inp.get("name") == name:
            return inp
    return None


def _input_name_at(node, slot):
    """输入名。

    ⚠️ 优先取 `inputs[slot].widget.name` —— 新版前端会把「这个输入其实是个控件」
       显式写出来（实测 CR Text 的输入是 {"name":"text","widget":{"name":"text"}}）。
       有它就说明"该输入对应的控件名"，比按类型查表可靠得多；
       没有（老工作流）再退回 name。
    """
    inp = _input_at(node, slot)
    w = inp.get("widget")
    if isinstance(w, dict) and w.get("name"):
        return w["name"]
    return inp.get("name")


def _widget_index(node, widget_name):
    return (WIDGET_INDEX.get(node.get("type")) or {}).get(widget_name)


def _set_widget(node, widget_name, value):
    """按 widget 名把值写进 `widgets_values` 与 `widgets_values_named`。

    ⚠️ **两份都要写**：新版前端（0.37+）除了数组版还写了 named 版，而且优先读后者
       —— 只改数组等于白改。

    返回 True 表示确实改了东西（用来统计"写了几处"，方便自检与排障）。
    """
    idx = _widget_index(node, widget_name)
    if idx is None:
        return False                      # 白名单外的控件：一个字都不碰
    changed = False
    wv = node.get("widgets_values")
    if isinstance(wv, list):
        # 短了就补齐：ComfyUI 加载时按索引取，缺位会当成 undefined
        while len(wv) <= idx:
            wv.append(None)
        if wv[idx] != value:
            wv[idx] = value
            changed = True
    wvn = node.get("widgets_values_named")
    if isinstance(wvn, dict) and widget_name in wvn and wvn[widget_name] != value:
        wvn[widget_name] = value
        changed = True
    return changed


def _current_widget(node, widget_name):
    """读控件当前值；该输入是连线时返回 None（运行时有值，元数据里读不到）。"""
    inp = _input_by_name(node, widget_name)
    if isinstance(inp, dict) and inp.get("link") is not None:
        idx = _widget_index(node, widget_name)
        wv = node.get("widgets_values")
        # 连线时控件位通常是空串；把空串当"未知"处理，别当成有效内容
        if idx is None:
            return None
        if isinstance(wv, list) and idx < len(wv) and isinstance(wv[idx], str) and wv[idx].strip():
            return wv[idx]
        return None
    idx = _widget_index(node, widget_name)
    wv = node.get("widgets_values")
    if idx is not None and isinstance(wv, list) and idx < len(wv):
        v = wv[idx]
        return v if isinstance(v, str) else ""
    wvn = node.get("widgets_values_named")
    if isinstance(wvn, dict) and isinstance(wvn.get(widget_name), str):
        return wvn[widget_name]
    return None


def _resolve_output_text(ctx, node, depth=0):
    """尽力还原「某节点输出」的运行时文本。

    能确定的就用确定值；确定不了（第三方节点运行时才有值，如 LoraManager 触发词）
    按**空串**处理 —— 宁可少一段，也不编一段假的。
    """
    if not isinstance(node, dict) or depth > 8:
        return ""
    if str(node.get("id")) in ctx["self_ids"]:
        return ctx["text"]
    t = node.get("type")

    if t in PASS_THROUGH_TYPES:
        for inp in (node.get("inputs") or []):
            if isinstance(inp, dict) and inp.get("link") is not None:
                up = ctx["by_id"].get(ctx["src"].get(inp["link"], (None,))[0])
                return _resolve_output_text(ctx, up, depth + 1)
        return ""

    if t == "StringConcatenate":
        parts = []
        for name in ("string_a", "string_b"):
            inp = _input_by_name(node, name)
            if isinstance(inp, dict) and inp.get("link") is not None:
                up = ctx["by_id"].get(ctx["src"].get(inp["link"], (None,))[0])
                parts.append(_resolve_output_text(ctx, up, depth + 1))
            else:
                parts.append(_current_widget(node, name) or "")
        delim = _current_widget(node, "delimiter")
        delim = delim if isinstance(delim, str) else ", "
        parts = [p.strip() for p in parts if p and p.strip()]
        return delim.join(parts)

    for name in SINGLE_TEXT_KEYS:
        if _widget_index(node, name) is None:
            continue
        inp = _input_by_name(node, name)
        if isinstance(inp, dict) and inp.get("link") is not None:
            up = ctx["by_id"].get(ctx["src"].get(inp["link"], (None,))[0])
            return _resolve_output_text(ctx, up, depth + 1)
        return _current_widget(node, name) or ""
    return ""


def _paired_negative(ctx, positive_ce_id):
    """顺着"消费这个正向编码的采样器"的 `negative` 输入，读回配对的负向提示词。

    没有这一步，"正负成对"就只能靠看图工具自己猜（实测它会把正负配到
    不是这张图的那条流上）。返回 "" 表示找不着（不编）。
    """
    for n in (ctx["workflow"].get("nodes") or []):
        if not isinstance(n, dict):
            continue
        pos = _input_by_name(n, "positive")
        if not (isinstance(pos, dict) and pos.get("link") is not None):
            continue
        s = ctx["src"].get(pos["link"])
        if not s or s[0] != positive_ce_id:
            continue
        neg = _input_by_name(n, "negative")
        if not (isinstance(neg, dict) and neg.get("link") is not None):
            continue
        ns = ctx["src"].get(neg["link"])
        up = ctx["by_id"].get(ns[0]) if ns else None
        txt = _resolve_output_text(ctx, up)
        if txt:
            return txt
    return ""


# ---------------------------------------------------------------------------
# 对外：注入
# ---------------------------------------------------------------------------

def inject_workflow_text(workflow, text, self_ids=frozenset()):
    """把 `text` 写进 UI 工作流（`workflow` 键）里所有该有它的位置。

    返回统计 dict（ok / written / encoders / positive / negative / reason）。
    """
    st = {"ok": False, "written": [], "encoders": 0,
          "positive": "", "negative": "", "reason": ""}
    if not isinstance(workflow, dict):
        st["reason"] = "没有 workflow 元数据"
        return st
    text = str(text or "").strip()
    if not text:
        st["reason"] = "正文为空"
        return st
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        st["reason"] = "workflow 里没有 nodes"
        return st

    by_id = _node_index(workflow)
    downstream, src = _link_maps(workflow)
    ctx = {"workflow": workflow, "by_id": by_id, "src": src,
           "text": text, "self_ids": {str(i) for i in self_ids}}
    written = []

    def write(node, name):
        if not isinstance(node, dict) or _widget_index(node, name) is None:
            return False
        if _set_widget(node, name, text):
            written.append("%s#%s.%s" % (node.get("type"), node.get("id"), name))
            return True
        return False

    # ---- 起点：插件自己的节点（定位 + 找到 text 输出端口）----
    seeds = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        t = n.get("type")
        if t in OWN_TEXT_WIDGET:
            write(n, OWN_TEXT_WIDGET[t])
        if t in OWN_TEXT_OUTPUT_SLOT:
            seeds.append((n.get("id"), OWN_TEXT_OUTPUT_SLOT[t]))
            ctx["self_ids"].add(str(n.get("id")))
    if not seeds:
        st["reason"] = "工作流里没有本插件的节点"
        return st

    # ---- ① 承载位：顺链往下，写"正文原值" ----
    seen = set()
    stack = list(seeds)
    encoders = []                       # 终点的正向 CLIPTextEncode
    while stack:
        oid, oslot = stack.pop()
        for (tid, tslot) in downstream.get((oid, oslot), []):
            tn = by_id.get(tid)
            if not isinstance(tn, dict):
                continue
            iname = _input_name_at(tn, tslot)
            if iname not in PROPAGATE_INPUTS:
                continue
            key = (tid, iname)
            if key in seen:
                continue
            seen.add(key)
            ttype = tn.get("type")
            if ttype in TERMINAL_TYPES:
                if tid not in [e.get("id") for e in encoders]:
                    encoders.append(tn)
                continue                     # 终点：交给 ② 写"尽力完整值"，不再下探
            write(tn, iname)
            # 值经过拼接后已不是纯正文，但继续往下走是为了覆盖到下游
            stack.append((tid, 0))

    # ---- ② 终点位：喂 positive 的 CLIPTextEncode 写"尽力还原的完整正向" ----
    # 别只认走链找到的那几个 —— 有些工作流是"采样器 ← 正向编码"直连，走链也能到；
    # 但为稳妥起见，把所有"被当作 positive 喂进采样器"的编码节点都收进来。
    enc_ids = {e.get("id") for e in encoders}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        for inp in (n.get("inputs") or []):
            if not isinstance(inp, dict) or inp.get("name") != "positive":
                continue
            if inp.get("link") is None:
                continue
            s = src.get(inp["link"])
            pn = by_id.get(s[0]) if s else None
            if isinstance(pn, dict) and pn.get("type") in TERMINAL_TYPES:
                enc_ids.add(pn.get("id"))
    positives, negatives = [], []
    best_by_nid = {}
    for nid in enc_ids:
        pn = by_id.get(nid)
        best = _resolve_output_text(ctx, pn)
        if not best:
            best = text
        best_by_nid[nid] = best
        # ⚠️ 幂等守卫：这一位已经带着正文了，就说明**上一轮已经写过**（工具能看到的
        #    也正是它）。再写一次会因为「链上那个字面量被解析重复拼一遍」而越写越长
        #    （实测：best 会变成 `质量词 + 正文 + 正文`，正文每轮多一份）。
        cur = _current_widget(pn, "text")
        if isinstance(cur, str) and text in cur:
            pass
        elif _set_widget(pn, "text", best):
            written.append("%s#%s.text" % (pn.get("type"), nid))
        if best not in positives:
            positives.append(best)
        neg = _paired_negative(ctx, nid)
        if neg and neg not in negatives:
            negatives.append(neg)

    # ---- ③ 兜底位：正向链上游的其它文本节点，把**空着**的文本位填上正文 ----
    #
    # 为什么必须有这一条：看图工具挑哪个节点是不确定的。实测它挑的是
    # 「自动拼接：官方质量词（本流）+ 全局正文」那个节点 —— 而那个节点里
    # 只有质量词是**字面量**，接收触发词的那一位是**连线**（元数据里空串）。
    # 不填它，工具读到的还是只有质量词，用户看到的现象**一点没变**。
    #
    # ⚠️ 三条边界，缺一不可：
    #   ① 只填**当前为空**的位置 —— 绝不覆盖用户写死的质量词等字面量；
    #   ② 只填**正向链上游**的文本节点 —— 不碰其它无关链路（例如别的模型流）；
    #   ③ 不碰终点 CLIPTextEncode —— 负向也是 CLIPTextEncode，
    #      往里写正向正文会把负向污染成正向。
    # 连线位在 ComfyUI 界面里由插槽接管、不显示控件值，所以填进去**不会被用户看到**，
    # 只对"读 widget 值"的看图工具有效。
    reachable = set()

    def _collect_upstream(node, depth=0):
        if not isinstance(node, dict) or depth > 8:
            return
        nid = node.get("id")
        if nid in reachable:
            return
        reachable.add(nid)
        for name in SINGLE_TEXT_KEYS + ("string_a", "string_b"):
            if _widget_index(node, name) is None:
                continue
            inp = _input_by_name(node, name)
            if isinstance(inp, dict) and inp.get("link") is not None:
                s = src.get(inp["link"])
                if s:
                    _collect_upstream(by_id.get(s[0]), depth + 1)

    for nid in enc_ids:
        _collect_upstream(by_id.get(nid))
    filled = 0
    path_nodes = {tid for (tid, _i) in seen}      # ① 已经写过的节点（正文流经处）
    for nid in reachable:
        n = by_id.get(nid)
        if not isinstance(n, dict):
            continue
        # ⚠️ ① 写过的节点不再补空位：它已经有正文了，再补会把同一段写成两份
        #    （拼接型看图工具会显示成「正文, 正文」）。
        if nid in path_nodes:
            continue
        t = n.get("type")
        if t not in WIDGET_INDEX or t in TERMINAL_TYPES:
            continue
        for wname in WIDGET_INDEX[t]:
            if wname == "delimiter":
                continue
            cur = _current_widget(n, wname)
            if cur is not None and cur.strip():
                continue                     # 有字面量内容 → 不动
            inp = _input_by_name(n, wname)
            if isinstance(inp, dict) and inp.get("link") is None and cur is None:
                continue                     # 没有这个输入、也不是控件 → 跳过
            if _set_widget(n, wname, text):
                written.append("%s#%s.%s(空位)" % (t, n.get("id"), wname))
                filled += 1

    # ---- ④ 上游拼接位：看图工具实际读的那个位置（v3.7.0）----
    #
    # 实测（对 ComfyUIGallery v1.4.6 的 /api/inspect 做对照实验，结论可复现）：
    #   · 改终点 CLIPTextEncode.text / CR Text.text / API prompt / A1111 `parameters`
    #     块 / 我们自己的 anima_v4_prompt → 它显示的**一个字都不变**；
    #   · 只改 StringConcatenate#1043 的 `widgets_values[0]` → 它立刻跟着变。
    #   而且它不是"挑一个"，而是把正向上游链路上**每个** StringConcat 的
    #   `widgets_values[0]` 按「上游 → 下游」顺序**拼起来**（实验：给两个都打标记
    #   → 显示 "A43A79"）。
    #
    # Anima 工作流里这条链是：
    #   CLIPTextEncode(终点) ← 拼接「触发词+质量词 → 全局正文」 ← 拼接「自动拼接：
    #   官方质量词（本流）+ 全局正文」 ← LoraManager 触发词
    # 其中只有「自动拼接」那个节点的 string_a 是**字面量**（= 质量词），
    # 这就是用户永远只看到 `masterpiece, best quality` 的原因。
    #
    # 修法：把该链的**完整正向**（= ②里算好的 best，质量词 + 正文）写进
    #       「该链上 wv[0] 原本非空」的 StringConcat 的 string_a。
    #
    # ⚠️ 边界：
    #   · 只改**原本非空**的（真字面量）；空的是连线位，写了会让工具拼出重复；
    #   · 只动 `string_a`（`widgets_values[0]`）——工具读的就是这一位；
    #   · `workflow` 只用于展示，ComfyUI 从不拿它跑图，所以**不影响出图结果**。
    strcat_types = {t for t in WIDGET_INDEX if "StringConcat" in t}
    reached = set()

    def _chain_strcats(node, depth=0, acc=None):
        """从 node 沿"文本输入"向上走，收集遇到的 StringConcat（近 → 远）。"""
        if acc is None:
            acc = []
        if not isinstance(node, dict) or depth > 8:
            return acc
        nid = node.get("id")
        if nid in reached:
            return acc
        reached.add(nid)
        if node.get("type") in strcat_types:
            acc.append(node)
        for name in ("string_a", "string_b", "text", "value", "string"):
            if _widget_index(node, name) is None:
                continue
            inp = _input_by_name(node, name)
            if isinstance(inp, dict) and inp.get("link") is not None:
                s = src.get(inp["link"])
                if s:
                    _chain_strcats(by_id.get(s[0]), depth + 1, acc)
        return acc

    for nid, best in best_by_nid.items():
        for sc in _chain_strcats(by_id.get(nid)):
            cur = _current_widget(sc, "string_a")
            if not (isinstance(cur, str) and cur.strip()):
                continue                     # 连线位/空位 → 保持原样
            if text in cur:
                continue                     # 幂等：已经写过了（同上②的守卫）
            if _set_widget(sc, "string_a", best):
                written.append("%s#%s.string_a(上游拼接位)"
                               % (sc.get("type"), sc.get("id")))

    st["written"] = written
    st["filled_blanks"] = filled
    st["encoders"] = len(enc_ids)
    st["positive"] = positives[0] if positives else text
    st["all_positives"] = positives
    st["negative"] = "\n".join(negatives)
    st["ok"] = bool(written)
    if not written:
        st["reason"] = "没找到可写的位置"
    return st


def inject_api_prompt(prompt, text, meta=None):
    """把正文写进 API 格式的 prompt（`prompt` 键）—— **只写惰性键**。

    ⚠️ 绝不改动 `inputs` 里已声明的输入（那会改变执行结果）。
    """
    st = {"ok": False, "written": []}
    text = str(text or "").strip()
    if not isinstance(prompt, dict) or not text:
        return st
    payload = json.dumps(meta if meta is not None else {"positive": text},
                         ensure_ascii=False)

    targets = set()
    for nid, nd in prompt.items():
        if not isinstance(nd, dict):
            continue
        # ① 插件自己的节点
        if (nd.get("class_type") or "") in OWN_TEXT_OUTPUT_SLOT:
            targets.add(str(nid))
        # ② 喂 positive 的 CLIPTextEncode（挂在它身上，方便只翻这个节点的工具看到）
        ins = nd.get("inputs")
        if not isinstance(ins, dict):
            continue
        pos = ins.get("positive")
        if isinstance(pos, (list, tuple)) and len(pos) >= 1:
            up = prompt.get(str(pos[0]))
            if isinstance(up, dict) and up.get("class_type") in TERMINAL_TYPES:
                targets.add(str(pos[0]))

    for nid in targets:
        ins = prompt[nid].setdefault("inputs", {})
        if ins.get(INJECT_KEY) != payload:
            ins[INJECT_KEY] = payload
            st["written"].append("%s#%s" % (prompt[nid].get("class_type"), nid))
    st["ok"] = bool(st["written"])
    return st


def inject_metadata(extra_pnginfo, prompt, text, self_ids=frozenset(),
                    version=""):
    """节点侧的**唯一入口**：把正文写进 `workflow` 与 `prompt` 两处元数据。

    · `extra_pnginfo` 是 hidden 输入 EXTRA_PNGINFO（同一次执行内共享的 dict）；
    · `prompt` 是 hidden 输入 PROMPT（同一份 API 图）；
    · `self_ids` 是本插件节点 id（用于在图上认出自己）；
    · 两者都可能是 None（例如用 API 方式提交、没带 extra_data），此时静默跳过。

    ⚠️ 本函数**永不抛异常** —— 元数据写不进去是小事，把出图搞挂是大事。
    """
    text = str(text or "").strip()
    st = {"workflow": None, "prompt": None, "meta": None}
    wf_st = None
    try:
        if isinstance(extra_pnginfo, dict):
            wf_st = inject_workflow_text(extra_pnginfo.get("workflow"), text, self_ids)
            st["workflow"] = wf_st
    except Exception as e:                     # pragma: no cover
        wf_st = {"ok": False, "reason": "异常：%s" % e}
        st["workflow"] = wf_st

    meta = {
        "schema": META_SCHEMA,
        "plugin": "Comfyui-Anima-Wardrobe-V4",
        "version": version,
        "positive": text,                       # 插件产出的正文**原值**
        "positive_full": (wf_st or {}).get("positive", ""),   # 尽力还原的完整正向
        "negative": (wf_st or {}).get("negative", ""),        # 配对读回的负向
        "written": len((wf_st or {}).get("written") or []),
        "workflow_ok": bool((wf_st or {}).get("ok")),
    }
    st["meta"] = meta
    try:
        if isinstance(extra_pnginfo, dict):
            extra_pnginfo[TEXT_KEY] = meta          # SaveImage 会写成同名 tEXt 块
            extra_pnginfo[LEGACY_TEXT_KEY] = meta   # v4.0.0：同时写 v3 键，读端零改动
    except Exception:                               # pragma: no cover
        pass
    try:
        st["prompt"] = inject_api_prompt(prompt, text, meta)
    except Exception as e:                     # pragma: no cover
        st["prompt"] = {"ok": False, "reason": "异常：%s" % e}
    return st


def dump_workflow_prompt(workflow):
    """从 workflow 里读回"当前写在元数据里的正向提示词"（校验脚本用，不参与出图）。

    优先级：终点正向编码 → 承载位（CR Text / 拼接节点）里最长的那段。
    """
    if not isinstance(workflow, dict):
        return ""
    by_id = _node_index(workflow)
    _, src = _link_maps(workflow)

    def val(node, name):
        idx = _widget_index(node, name)
        wvn = node.get("widgets_values_named")
        if isinstance(wvn, dict) and isinstance(wvn.get(name), str) and wvn[name]:
            return wvn[name]
        wv = node.get("widgets_values")
        if isinstance(wv, list) and idx is not None and idx < len(wv):
            return wv[idx] if isinstance(wv[idx], str) else ""
        return ""

    for n in (workflow.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        for inp in (n.get("inputs") or []):
            if not isinstance(inp, dict) or inp.get("name") != "positive":
                continue
            if inp.get("link") is None:
                continue
            s = src.get(inp["link"])
            pn = by_id.get(s[0]) if s else None
            if isinstance(pn, dict) and pn.get("type") in TERMINAL_TYPES:
                v = val(pn, "text")
                if v:
                    return v
    best = ""
    for n in (workflow.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        for name in SINGLE_TEXT_KEYS:
            if _widget_index(n, name) is None:
                continue
            v = val(n, name)
            if len(v) > len(best):
                best = v
    return best


__all__ = ["INJECT_KEY", "TEXT_KEY", "META_SCHEMA", "WIDGET_INDEX",
           "inject_workflow_text", "inject_api_prompt", "inject_metadata",
           "dump_workflow_prompt", "json"]
