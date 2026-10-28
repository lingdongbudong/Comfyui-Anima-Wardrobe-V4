# -*- coding: utf-8 -*-
"""用户数据存储基线（命名预设 与 角色收藏）。

这三块存的是**用户自己攒下来的东西** —— 丢了没法重建。所以别处可以松，
这几条必须钉死：

  ① 预设：保存 / 列表 / 同名覆盖 / 删除幂等
  ② 参数校验：空名 / 非对象一律拒绝，且**不落盘**
  ③ 角色收藏：切换幂等（重复收藏不产生两条）
  ④ 场景收藏（v3.43.0）：**独立文件**，值域是场景 id（sc_xxx）——
     与角色收藏（user_favorites.json，值域是角色 tag）**必须互不污染**，
     混在一起会让「仅收藏内随机」拿场景 id 去角色库比对，退化链直接空池
  ⑤ 原子写：写盘不产生 0 字节文件、不留 .tmp 残留
  ⑥ 容错：JSON 损坏 → 备份成 .broken + 降级成空结构，绝不抛异常
  ⑦ 上限保护：预设条数超限时拒绝写入

⚠️ 测试把模块里的文件路径**重定向到临时目录**，全程不碰
   `presets/user_presets.json` / `user_favorites.json` /
   `user_scene_favorites.json` ——
   否则跑一次测试就把用户真实的预设和收藏清空了。

跑法：python tests/check_v3_store.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _boot  # noqa: E402

S = _boot.load("anima_v4_store")

FAILS = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="av3store-")

# 把存储路径重定向到临时目录 —— 隔离真实用户数据
S.PRESET_DIR = TMP
S.PRESETS_FILE = os.path.join(TMP, "user_presets.json")
S.FAVORITES_FILE = os.path.join(TMP, "user_favorites.json")
# v3.43.0：场景收藏是**另一个文件**，也要重定向，否则测试会写用户真实收藏
S.SCENE_FAV_FILE = os.path.join(TMP, "user_scene_favorites.json")


def main():
    D1 = {
        "level": "sfw",
        "weights": {"fields": {"hair_color": 3.0}},
        "selected_roles": "a|b",
        "tag_cap": "自动",
        "base_prob": 0.65,
        "appearance_follow": True,
        "extra_body": "",
        "force_role": "",
    }

    print("── ① 预设：保存 / 列表 / 覆盖 / 删除 ──")
    ck("初始列表为空", S.list_presets() == [], str(S.list_presets()))

    r = S.save_preset("我的常用", D1)
    ck("保存后能读到 1 条", len(r) == 1 and r[0]["name"] == "我的常用", str(r))
    ck("返回的内容完整（前端一次拿全，不用再 GET）",
       r[0]["data"]["level"] == "sfw"
       and r[0]["data"]["weights"]["fields"]["hair_color"] == 3.0,
       json.dumps(r[0]["data"], ensure_ascii=False)[:80])
    ck("带 saved_at 时间戳", bool(r[0]["saved_at"]), r[0]["saved_at"])
    ck("摘要含档位与角色数",
       "sfw" in r[0]["summary"] and "2 位角色" in r[0]["summary"], r[0]["summary"])

    r = S.save_preset("我的常用", {**D1, "level": "hardcore"})
    ck("同名覆盖只留一条", len(r) == 1, str([x["name"] for x in r]))
    ck("覆盖后内容是新值", r[0]["data"]["level"] == "hardcore", r[0]["data"]["level"])

    r = S.save_preset("另一套", {"level": "suggestive"})
    ck("不同名各留一条", len(r) == 2, str([x["name"] for x in r]))
    r = S.delete_preset("另一套")
    ck("删除后只剩一条", len(r) == 1, str([x["name"] for x in r]))
    ck("删不存在的名字幂等（不报错）",
       len(S.delete_preset("压根没有")) == 1)

    print("\n── ② 参数校验（拒绝且不落盘）──")
    before = S.list_presets()
    for bad in ("", "   ", None, "   \n  "):
        try:
            S.save_preset(bad, D1)
            ck(f"空名 {bad!r} 被拒", False, "竟然存进去了")
        except ValueError:
            ck(f"空名 {bad!r} 被拒", True)
    try:
        S.save_preset("x", "not a dict")
        ck("非对象内容被拒", False, "竟然存进去了")
    except ValueError:
        ck("非对象内容被拒", True)
    ck("被拒的写入没有污染已有数据",
       S.list_presets() == before, str([x["name"] for x in S.list_presets()]))

    print("\n── ③ 收藏：切换 / 幂等 ──")
    ck("初始为空", S.list_favorites() == [], str(S.list_favorites()))
    ck("收藏 A", S.toggle_favorite("hakurei_reimu") == ["hakurei_reimu"])
    ck("收藏 B", S.toggle_favorite("kirisame_marisa")
       == ["hakurei_reimu", "kirisame_marisa"])
    ck("重复收藏 A 不产生两条（幂等）",
       S.toggle_favorite("hakurei_reimu", True) == ["hakurei_reimu", "kirisame_marisa"],
       str(S.list_favorites()))
    ck("取消 A", S.toggle_favorite("hakurei_reimu", False) == ["kirisame_marisa"])
    ck("再取消同一条幂等",
       S.toggle_favorite("hakurei_reimu", False) == ["kirisame_marisa"])
    ck("不带 on 时按当前状态取反",
       S.toggle_favorite("hakurei_reimu") == ["kirisame_marisa", "hakurei_reimu"])
    for bad in ("", "   ", None):
        try:
            S.toggle_favorite(bad)
            ck(f"空 tag {bad!r} 被拒", False, "竟然写进去了")
        except ValueError:
            ck(f"空 tag {bad!r} 被拒", True)

    print("\n── ④ 场景收藏（v3.43.0：独立文件、值域是场景 id）──")
    ck("初始为空", S.list_scene_favorites() == [], str(S.list_scene_favorites()))
    ck("收藏一条",
       S.toggle_scene_favorite("sc_rooftop_stretch") == ["sc_rooftop_stretch"])
    ck("再收藏一条（按收藏先后）",
       S.toggle_scene_favorite("sc_classroom_chin_rest")
       == ["sc_rooftop_stretch", "sc_classroom_chin_rest"])
    ck("重复收藏同一条不产生两条（幂等）",
       S.toggle_scene_favorite("sc_rooftop_stretch", True)
       == ["sc_rooftop_stretch", "sc_classroom_chin_rest"],
       str(S.list_scene_favorites()))
    ck("不带 on 时按当前状态取反（取消）",
       S.toggle_scene_favorite("sc_rooftop_stretch")
       == ["sc_classroom_chin_rest"])
    ck("取消一条本来就不在的收藏也算成功（面板连点两下不报错）",
       S.toggle_scene_favorite("sc_no_such_scene", False)
       == ["sc_classroom_chin_rest"])
    ck("再收藏回来",
       S.toggle_scene_favorite("sc_rooftop_stretch")
       == ["sc_classroom_chin_rest", "sc_rooftop_stretch"])
    for bad in ("", "   ", None, "../etc/passwd", "SC_UPPER", "rooftop",
                "sc_" + "a" * 90):
        try:
            S.toggle_scene_favorite(bad)
            ck(f"非法场景 id {bad!r} 被拒", False, "竟然写进去了")
        except ValueError:
            ck(f"非法场景 id {str(bad)[:18]!r} 被拒", True)
    # ⚠️ 关键：两份收藏**不能互相污染** —— 混文件会让「仅收藏内随机」
    #    拿场景 id 去角色库比对，退化链直接空池。
    ck("场景收藏没有写进角色收藏文件",
       "sc_rooftop_stretch" not in S.list_favorites(),
       str(S.list_favorites()))
    ck("角色收藏没有写进场景收藏文件",
       "hakurei_reimu" not in S.list_scene_favorites(),
       str(S.list_scene_favorites()))
    ck("两个文件各自独立存在",
       os.path.exists(S.FAVORITES_FILE) and os.path.exists(S.SCENE_FAV_FILE))
    _sfav = json.load(open(S.SCENE_FAV_FILE, encoding="utf-8"))
    ck("场景收藏文件带自己的 schema（不与角色收藏混用 @1）",
       _sfav.get("_meta", {}).get("schema") == "anima-wardrobe-v4/scene-favorites@1",
       str(_sfav.get("_meta")))

    print("\n── ⑤ 原子写：不留临时文件 ──")
    leftover = [f for f in os.listdir(TMP) if f.endswith(".tmp")]
    ck("没有 .tmp 残留", not leftover, str(leftover))
    ck("盘上文件是合法 JSON",
       all(isinstance(json.load(open(os.path.join(TMP, f), encoding="utf-8")), dict)
           for f in os.listdir(TMP) if f.endswith(".json")))

    print("\n── ⑥ 容错：文件损坏不把面板带崩 ──")
    with open(S.FAVORITES_FILE, "w", encoding="utf-8") as fh:
        fh.write("{这不是合法 JSON")
    ck("坏 JSON → 降级成空列表（不抛异常）", S.list_favorites() == [],
       str(S.list_favorites()))
    ck("坏文件被另存为 .broken 便于排查",
       os.path.exists(S.FAVORITES_FILE + ".broken"))
    ck("坏文件不会让后续写入失败",
       S.toggle_favorite("hakurei_reimu") == ["hakurei_reimu"])

    with open(S.SCENE_FAV_FILE, "w", encoding="utf-8") as fh:
        fh.write("{坏掉的场景收藏")
    ck("场景收藏坏 JSON → 同样降级成空列表",
       S.list_scene_favorites() == [], str(S.list_scene_favorites()))
    ck("坏条目（不是 sc_ 形态）被静默滤掉，不抛异常",
       (lambda: (
           open(S.SCENE_FAV_FILE, "w", encoding="utf-8").write(
               '{"favorites": ["sc_ok_one", "角色名", 42, null]}'),
           S.list_scene_favorites() == ["sc_ok_one"]))()[-1],
       str(S.list_scene_favorites()))

    with open(S.PRESETS_FILE, "w", encoding="utf-8") as fh:
        fh.write("[1,2,3]")          # 合法 JSON，但顶层不是对象
    ck("顶层非对象也降级成空", S.list_presets() == [], str(S.list_presets()))

    print("\n── ⑦ 上限保护 ──")
    real_max = S.MAX_PRESETS
    try:
        S.MAX_PRESETS = 3
        for i in range(3):
            S.save_preset(f"p{i}", {"level": "sfw"})
        ck("达到上限后仍可覆盖已有条目", bool(S.save_preset("p0", {"level": "sfw"})))
        try:
            S.save_preset("溢出的一条", {"level": "sfw"})
            ck("超出上限时拒绝新增", False, "竟然写进去了")
        except ValueError as exc:
            ck("超出上限时拒绝新增", "上限" in str(exc), str(exc))
    finally:
        S.MAX_PRESETS = real_max

    print()
    if FAILS:
        print(f"[check_v3_store] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print("[check_v3_store] 通过：7 组语义全部符合预期")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
