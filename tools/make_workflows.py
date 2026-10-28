# -*- coding: utf-8 -*-
"""生成两个工作流文件，**绝不改写用户的原件**。

  ① Anima-V3_独立提示词输出.json
     4 个节点、不出图、不需任何模型或 LoRA。
     用途：验证"插件装没装成功"的最快入口（与 Krea2 系列的
     `*_独立提示词输出.json` 同一套思路）。

  ② Anima_工作流V3_接入V3随机提示词.json
     把 Anima_工作流V3.json 原样复制一份，再把
     AnimaV4RandomPrompt.text 接到 CR Text(1004) 空着的 text 输入端口。
     选这个接法是因为 1004 的 text 端口当前 link=null —— 接上去之后
     六条底模流全部自动吃到，工作流**零改动**；拔掉线就回到手写文本框。

用法：
    python tools/make_workflows.py            # 写盘
    python tools/make_workflows.py --dry      # 只预览
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)

WF_DIR = "./workflows"
SRC_WF = os.path.join(WF_DIR, "Anima_工作流V3.json")
WIRED_WF = os.path.join(WF_DIR, "Anima_工作流V3_接入V3随机提示词.json")
STANDALONE_WF = os.path.join(WF_DIR, "Anima-V3_独立提示词输出.json")

GEN_TYPE = "AnimaV4RandomPrompt"
GRADER_TYPE = "AnimaV4PromptGrader"
EXPORT_TYPE = "CR Save Text To File"

# 控件顺序 = nodes.py 里 INPUT_TYPES 的声明顺序。**必须逐一对齐**，
# 否则存盘后再打开，控件值会整体错位。
# ⚠️ v3.1.0 追加 `selected_roles`、v3.2.0 追加 `big_breasts` —— 新工作流直接带上；
#    老工作流（10 项 / 11 项）由 tools/fix_workflows_v301.py、v302.py 补。
GEN_WIDGETS = [
    "sfw",      # nsfw_level
    -1,         # seed（-1 = 每次重跑都重抽）
    "自动",      # tag_cap
    0.65,       # base_prob
    "",         # disabled_sections
    "",         # lock_fields
    "",         # force_role
    "",         # weights_json
    "",         # extra_body
    True,       # appearance_follow
    "",         # selected_roles（v3.1.0 追加：面板里点选的角色，| 分隔）
    False,      # big_breasts（v3.2.0 追加：巨乳开关，默认关）
]

GEN_WIDGETS_V310 = GEN_WIDGETS[:-1]
GEN_WIDGETS_V300 = GEN_WIDGETS[:-2]

OUT_DIR_FOR_TXT = "S:/ComfyUI LX/output/AnimaV4_prompts"


def out_ports(names_types, links=None):
    links = links or {}
    return [{"name": n, "type": t, "links": links.get(i, [])}
            for i, (n, t) in enumerate(names_types)]


def make_gen_node(nid, pos, size=(380, 240), color="#232", bgcolor="#353"):
    return {
        "id": nid,
        "type": GEN_TYPE,
        "pos": list(pos),
        "size": list(size),
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": out_ports([
            ("text", "STRING"), ("report", "STRING"),
            ("level", "STRING"), ("cn_summary", "STRING"),
        ]),
        "properties": {
            "Node name for S&R": GEN_TYPE,
            "cnr_id": "Comfyui-Anima-Wardrobe-V4",
        },
        "widgets_values": list(GEN_WIDGETS),
        "color": color,
        "bgcolor": bgcolor,
    }


def make_note(nid, pos, size, text, color="#432", bgcolor="#653"):
    return {
        "id": nid, "type": "Note", "pos": list(pos), "size": list(size),
        "flags": {}, "order": 0, "mode": 0, "inputs": [], "outputs": [],
        "properties": {"Node name for S&R": "Note"},
        "widgets_values": [text],
        "color": color, "bgcolor": bgcolor,
    }


def make_save_text(nid, pos, file_name, size=(420, 130)):
    return {
        "id": nid, "type": EXPORT_TYPE, "pos": list(pos), "size": list(size),
        "flags": {}, "order": 0, "mode": 0,
        "inputs": [{"name": "multiline_text", "type": "STRING", "link": None}],
        "outputs": out_ports([("show_help", "STRING")]),
        "properties": {"Node name for S&R": EXPORT_TYPE,
                       "cnr_id": "ComfyUI_Comfyroll_CustomNodes"},
        "widgets_values": ["", OUT_DIR_FOR_TXT, file_name, "txt"],
        "color": "#223", "bgcolor": "#335",
    }


# ---------------------------------------------------------------------------
# ① 独立提示词输出工作流
# ---------------------------------------------------------------------------
def build_standalone():
    nodes = [
        make_note(1, (-40, -300), (560, 250), """【这是什么】
Anima 提示词随机生成（V4）的「独立提示词输出」工作流。

不出图、**不需要任何模型或 LoRA**，是验证"插件装没装成功"最快的方式：
装好插件重启 ComfyUI，打开这份工作流点「运行」，看下面两个文本框有没有出东西。

① 出题 —— 唯一需要你调的节点。
   点节点上的「⚙ 打开随机面板」可视化调档位与三层权重；
   也可以直接改控件：nsfw_level（档位）/ seed（-1=每次重抽）/ tag_cap 等。

② 审查 —— 把抽出来的提示词喂回造型台那套判定表，
   告诉你它实际落在第几档、命中了哪些成人向分类。

③ 导出 —— 写盘到 output/AnimaV4_prompts/ 下。

【改词库】
词库唯一真源是 S:/ComfyUI/提示词/ANIMA提示词生成器.html。
改完要重跑 node tools/export_v3_pools.mjs 与
python tools/classify_v3_levels.py，再跑 python tests/run_all.py 确认没漂移。
"""),
        make_note(2, (-40, 20), (560, 130), """【怎么接进真正的出图工作流】
打开 Anima_工作流V3_接入V3随机提示词.json（本插件附带的接入版），
或照下面两步手动接：

  1. 拖入本插件的「Anima 提示词随机生成（V4）」节点；
  2. 把它的 text 输出连到 CR Text 节点（编号 1004，即「全局正文」）
     那个**空着的 text 输入端口**。

连上之后六条底模流会自动全部吃到；拔掉线就回到手写文本框，可随时对照。
"""),
        make_gen_node(100, (-40, 210), (380, 250)),
        {
            "id": 101, "type": GRADER_TYPE, "pos": (400, 210),
            "size": (420, 160), "flags": {}, "order": 0, "mode": 0,
            "inputs": [{"name": "text", "type": "STRING", "link": 1}],
            "outputs": out_ports([("text", "STRING"), ("num", "INT"),
                                  ("level", "STRING"), ("report", "STRING")],
                                 {3: [3]}),
            "properties": {"Node name for S&R": GRADER_TYPE,
                           "cnr_id": "Comfyui-Anima-Wardrobe-V4"},
            "widgets_values": [True],
            "color": "#232", "bgcolor": "#353",
        },
        make_save_text(102, (880, 210), "V3_正文"),
        make_save_text(103, (880, 380), "V3_审查"),
    ]

    # 连线：出题 → 审查；出题 → 正文落盘；审查 → 报告落盘
    nodes[2]["outputs"][0]["links"] = [1, 2]
    nodes[4]["inputs"][0]["link"] = 2
    nodes[5]["inputs"][0]["link"] = 3

    links = [
        [1, 100, 0, 101, 0, "STRING"],   # 出题.text   → 审查.text
        [2, 100, 0, 102, 0, "STRING"],   # 出题.text   → 导出正文
        [3, 101, 3, 103, 0, "STRING"],   # 审查.report → 导出审查
    ]

    for i, n in enumerate(nodes):
        n["order"] = i

    return {
        "id": "anima-v3-standalone-prompt",
        "revision": 0,
        "last_node_id": 103,
        "last_link_id": 3,
        "nodes": nodes,
        "links": links,
        "groups": [{
            "id": 1, "title": "ANIMA-V3 提示词独立输出链路（不出图）",
            "bounding": [-70, 180, 1400, 380],
            "color": "#3f789e", "flags": {},
        }],
        "config": {},
        "extra": {"ds": {"scale": 0.75, "offset": [200, 300]}},
        "version": 0.4,
    }


# ---------------------------------------------------------------------------
# ② 接入版：原件 + 新节点，接 1004 的空 text 端口
# ---------------------------------------------------------------------------
def build_wired():
    if not os.path.exists(SRC_WF):
        raise SystemExit(f"找不到源工作流：{SRC_WF}")
    with open(SRC_WF, "r", encoding="utf-8") as fh:
        raw = fh.read()
    d = json.loads(raw)

    nodes = {n["id"]: n for n in d["nodes"]}
    target = None
    for n in d["nodes"]:
        if n["type"] == "CR Text" and n.get("title", "") == "":
            target = n
            break
    if target is None:
        # 退一步：id 1004（已知的「全局正文」节点）
        target = nodes.get(1004)
    if target is None:
        raise SystemExit("找不到「全局正文」CR Text 节点（1004）")

    # 幂等：已经接过就不再重复加节点
    existing = [n for n in d["nodes"] if n["type"] == GEN_TYPE]
    if existing:
        print("  [SKIP] 该工作流里已经存在 AnimaV4RandomPrompt，未改动")
        return None

    new_id = int(d.get("last_node_id", 0)) + 10
    new_link = int(d.get("last_link_id", 0)) + 1

    gen = make_gen_node(new_id, (target["pos"][0] - 420, target["pos"][1]),
                        size=(380, 240))
    gen["order"] = len(d["nodes"])
    gen["outputs"][0]["links"] = [new_link]

    # 目标端口：找到 name == "text" 的输入；它现在是 link=null
    slot = None
    for i, inp in enumerate(target.get("inputs", [])):
        if inp.get("name") == "text":
            slot = i
            break
    if slot is None:
        raise SystemExit("1004 上没有 text 输入端口")
    if target["inputs"][slot].get("link") is not None:
        print(f"  [WARN] 1004 的 text 端口已被占用（link="
              f"{target['inputs'][slot]['link']}），将覆盖为新的连线")

    target["inputs"][slot]["link"] = new_link
    d["nodes"].append(gen)
    d["links"].append([new_link, new_id, 0, target["id"], slot, "STRING"])
    d["last_node_id"] = new_id
    d["last_link_id"] = new_link

    note = make_note(new_id + 1,
                     (gen["pos"][0] - 20, gen["pos"][1] - 320),
                     (420, 290), """【接入说明 · 这个节点是新加的】

Anima 提示词随机生成（V4）的 text 输出接到了右边 CR Text(1004)
那个原本空着的 text 输入端口 —— 也就是「全局正文」。

· 接上之后六条底模流自动全部分发，工作流**没动过一根线**。
· 拔掉这根线，1004 就回到手动文本框模式，出图结果与接入前逐字节一致。
· 节点上四个按钮：打开随机面板 / 换种子 / 每次重抽 / 清空权重。
· 档位与三层权重都在面板里调，节点控件保持极简（同一个设置只留一个入口）。

⚠️ 想恢复原样：删掉这个新节点和它右边那根线即可，
   其余节点一个都没改过。
""")
    note["order"] = len(d["nodes"])
    d["nodes"].append(note)
    d["last_node_id"] = new_id + 1

    return d


def main():
    dry = "--dry" in sys.argv
    print("① 独立提示词输出工作流")
    sa = build_standalone()
    print(f"   节点 {len(sa['nodes'])} · 链接 {len(sa['links'])}")

    print("② 接入版工作流")
    wired = build_wired()
    if wired is None:
        print("   已存在接入节点，跳过")
    else:
        new = [n for n in wired["nodes"] if n["type"] == GEN_TYPE]
        print(f"   总节点 {len(wired['nodes'])}（新增 {len(new)} 个）"
              f" · 链接 {len(wired['links'])}")

    if dry:
        print("\n--dry：不写盘")
        return 0

    with open(STANDALONE_WF, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sa, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"\n已写出 {STANDALONE_WF}")

    if wired is not None:
        with open(WIRED_WF, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(wired, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"已写出 {WIRED_WF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
