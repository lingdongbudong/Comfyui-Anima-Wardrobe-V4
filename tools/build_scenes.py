# -*- coding: utf-8 -*-
"""场景搭配预设库：**校验 + 派生档位**，产出 presets/anima_v4_scenes.json。

为什么要一个脚本而不是手写 JSON：
  1. 每个预设的 `level` 必须由**内容**算出来（取所有标签里最高档），
     手写必然漂移 —— 而它决定"这个搭配在哪些档位可用"，写错就等于闸门漏；
  2. `tags` 里的字段名 / 选项原文必须**真实存在**，写错一个词就是静默失效
     （value 不匹配任何选项 → apply_preset 里的 field_by_key 找不到 →
      那个字段悄悄不生效，而且不报错）；
  3. 与「词库零漂移」同一套纪律：派生数据由脚本算，JSON 只存**人写的内容**。

用法：
    python tools/build_scenes.py            # 校验 + 回写（幂等）
    python tools/build_scenes.py --check    # 只校验，不写（测试用）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)

# ⚠️ 不能直接 `from anima_v4_rules import ...` —— 那个模块里有包内相对导入
#    （`from . import anima_v4_nsfw`），裸脚本运行会 ImportError:
#    "attempted relative import with no known parent package"。
#    本仓库的统一做法是复用 tests/_boot.py 造一个"只有 __path__ 的空包"
#    再 import_module（见 tools/dump_ui_fixtures.py）。
sys.path.insert(0, os.path.join(PLUGIN, "tests"))

import _boot  # noqa: E402

_R = _boot.load("anima_v4_rules")
field_by_key = _R.field_by_key
option_level = _R.option_level
tag_level = _R.tag_level

SCENES = os.path.join(PLUGIN, "presets", "anima_v4_scenes.json")


def _variant_items(raw) -> list:
    """把 `random_variants` 的两种写法统一成扁平条目数组。

    · 数组        → 单池（v3.24.0）
    · 对象        → 多池，每个键一个池，值可以是数组或 `{"label", "items"}`（v3.27.0）
    """
    out = []
    if isinstance(raw, list):
        out = [v for v in raw if isinstance(v, dict)]
    elif isinstance(raw, dict):
        for v in raw.values():
            body = v.get("items") if (isinstance(v, dict) and "items" in v) else v
            if isinstance(body, list):
                out += [x for x in body if isinstance(x, dict)]
    return out


def scene_level(tags: dict, extra: str, random_fields: dict = None,
                random_variants: list = None) -> int:
    """预设档位 = max(每个字段值的准入档位, extra 里每个标签的档位, 随机候选的档位)。

    ⚠️ 用 `option_level`（含段下限与逐选项上抬）而不是裸的 grade_nsfw：
       那正是 `apply_preset` 写入时用的口径（`_field_ok_under`），
       两边必须同一个数，否则会出现「预设被放进了候选池、写的时候却被挡」
       这种半吊子状态。
    ⚠️ v3.22.0：`random_fields` 的候选**也要算进档位** —— 否则某些档位下
       候选会被 `_field_ok_under` 静默过滤掉一半，而条目本身却还挂在低档。
    """
    lv = 0
    for k, v in (tags or {}).items():
        lv = max(lv, int(option_level(k, v)))
    for t in str(extra or "").split(","):
        t = t.strip().lower()
        if t:
            lv = max(lv, int(tag_level(t)))
    for k, cands in (random_fields or {}).items():
        for v in (cands or []):
            lv = max(lv, int(option_level(k, v)))
    # ⚠️ v3.24.0：变体短语同样要算 —— 它会在套用时并进 extra，
    #    若里面藏了高档词，条目本身却挂在低档，就是"写的时候被静默 cut"。
    for v in _variant_items(random_variants):
        for t in str(v.get("extra") or "").split(","):
            t = t.strip().lower()
            if t:
                lv = max(lv, int(tag_level(t)))
    return lv


def validate(data: dict) -> list:
    """返回错误列表（空 = 全部合法）。"""
    errs = []
    ids = set()
    groups = {g["id"] for g in data.get("groups", [])}
    for i, sc in enumerate(data.get("scenes", [])):
        sid = str(sc.get("id") or "")
        where = f"scenes[{i}] {sid or '(缺 id)'}"
        if not sid:
            errs.append(f"{where}: 缺 id")
        elif not sid.startswith("sc_"):
            errs.append(f"{where}: id 必须以 sc_ 开头（与法典 c1..c14 区分）")
        elif sid in ids:
            errs.append(f"{where}: id 重复")
        else:
            ids.add(sid)
        if not str(sc.get("zh") or "").strip():
            errs.append(f"{where}: 缺中文名 zh")
        if sc.get("group") not in groups:
            errs.append(f"{where}: group {sc.get('group')!r} 不在 groups 里")
        tags = sc.get("tags")
        if not isinstance(tags, dict) or not tags:
            errs.append(f"{where}: tags 必须是非空对象")
            continue
        # v3.32.0：`no_role` —— "这一条的画框里没有脸"。
        # 用于第一人称自我视角：观众就是本人在低头看自己身体，角色 tag
        # （`herta` / `siege` …）会把镜头从"自己的身体"拉回一张脸。
        # ⚠️ 必须是**布尔**，不能写 "true"/"false" 字符串 —— 引擎侧
        #    `scene_says_no_role()` 只认 `is True`，字符串会让开关静默失效
        #    （v3.11.0 布尔开关被 str() 化那个坑的同一类错误）。
        nr = sc.get("no_role")
        if nr is not None:
            if not isinstance(nr, bool):
                errs.append(f"{where}: no_role 必须是布尔值（true / false），不能写字符串")
            elif nr and sc.get("role_ok"):
                errs.append(f"{where}: no_role 与 role_ok 自相矛盾"
                            "（一个说画框里没有脸，一个说有脸）")
        # ⚠️ 人数与角色是"地基"，预设不得代填（见 _meta.rules）
        for forbidden in ("count", "role"):
            if forbidden in tags:
                errs.append(f"{where}: 不得设置 {forbidden}（人数/角色由用户或自动抽取负责）")
        for k, v in tags.items():
            _sec, fld = field_by_key(k)
            if not fld:
                errs.append(f"{where}: 字段 {k!r} 不存在")
                continue
            opts = [en for _zh, en in fld.get("opts", [])]
            if v not in opts:
                errs.append(f"{where}: 字段 {k} 的取值 {v!r} 不是合法选项")
        # v3.22.1：`count_lock` 必须是合法的 count 选项，且档位不能高于条目档位 ——
        # 高于条目档位时 `apply_preset` 的闸门会静默跳过它（等于没钉），
        # 而"人手写的、看着像钉住了"是最难查的那种失效。
        cl = sc.get("count_lock")
        # v3.22.3（用户口径：非必要多人的场景尽量只有一名女性）：
        # **每条非特写场景都必须声明人数**。不声明就等于把人数交给随机，
        # 而随机池里有 `2girls, yuri` / `multiple girls, orgy` —— 单人写真会变双人。
        if cl is None and sc.get("group") != "near":
            errs.append(f"{where}: 未声明 count_lock（非特写场景必须钉人数）")
        if cl is not None:
            _sec, cfld = field_by_key("count")
            copts = [en for _zh, en in (cfld or {}).get("opts", [])]
            if not str(cl).strip():
                errs.append(f"{where}: count_lock 不能是空串（不钉就不写这个键）")
            elif cl not in copts:
                errs.append(f"{where}: count_lock {cl!r} 不是合法的 count 选项")
            elif option_level("count", cl) > int(sc.get("level", 0)):
                errs.append(f"{where}: count_lock 档位 {option_level('count', cl)} "
                            f"高于条目档位 {sc.get('level')}，会被闸门静默跳过")
            elif cl in tags:
                errs.append(f"{where}: count 同时写在 tags 与 count_lock")
        # v3.22.0：`drop_fields` —— 套用时**强制清零**的字段（不是"写成某个值"）。
        # 用途：特写要保持画框纯净，但又不能给字段钉一个和取景矛盾的值
        #（口交特写就是典型：写 `kneeling` 会把全身画进来，写任何值都不对，
        #  正确做法是"这个字段别说话"）。
        drop = sc.get("drop_fields")
        if drop is not None:
            if not isinstance(drop, list) or not all(isinstance(x, str) for x in drop):
                errs.append(f"{where}: drop_fields 必须是字符串数组")
            else:
                for k in drop:
                    if k in ("count", "role"):
                        errs.append(f"{where}: drop_fields 不得包含 {k}（地基字段）")
                    elif not field_by_key(k)[1]:
                        errs.append(f"{where}: drop_fields 里的字段 {k!r} 不存在")
                    elif k in tags:
                        errs.append(f"{where}: {k} 同时写在 tags 与 drop_fields（自相矛盾）")
        # v3.38.0：`ban_tags` —— 条目点名"这些标签在本条里绝对不要"。
        # `apply_preset` 会在最后扫一遍 state，抽到就清空（不重抽，rng 消耗不变）。
        # 为什么需要它：字段"不写在 tags 里"不等于不出现 —— 权重仍是 1.0，
        # 照样随机抽。姿势场景里 `own hands clasped` 这类"双手合拢"动作
        # 实测会从 `arms_hands` 的抽签里漏进 5–8% 的画面。
        # ⚠️ 校验必须挡住拼写错误：不存在的标签等于没写，而且不报错。
        bans = sc.get("ban_tags")
        if bans is not None:
            if not isinstance(bans, list) or not all(isinstance(x, str) for x in bans):
                errs.append(f"{where}: ban_tags 必须是字符串数组")
            else:
                _all_opts = set()
                for _s in _R.sections():
                    for _f in _s.get("fields", []):
                        _all_opts |= {en for _zh, en in (_f.get("opts") or [])}
                for t in bans:
                    if t in ("count", "role", "n_canon"):
                        errs.append(f"{where}: ban_tags 不得包含地基字段 {t!r}")
                    elif t not in _all_opts:
                        errs.append(f"{where}: ban_tags 里的 {t!r} 不是任何字段的合法选项"
                                    "（拼写错误会让它静默失效）")
                clash = [t for t in bans if t in set(tags.values())]
                if clash:
                    errs.append(f"{where}: ban_tags 与 tags 写死的值冲突 {clash!r}"
                                "（自己禁自己，那条永远不生效）")
        # v3.22.0：`random_fields` —— 套用时**从候选里抽一个**的字段。
        # 与 tags 的区别只有一个：tags 写死值，random_fields 每次随机。
        rf = sc.get("random_fields")
        if rf is not None:
            if not isinstance(rf, dict) or not rf:
                errs.append(f"{where}: random_fields 必须是非空对象")
            else:
                for k, cands in rf.items():
                    if k in ("count", "role", "n_canon"):
                        errs.append(f"{where}: random_fields 不得包含 {k}")
                        continue
                    _sec, fld = field_by_key(k)
                    if not fld:
                        errs.append(f"{where}: random_fields 里的字段 {k!r} 不存在")
                        continue
                    if k in tags:
                        errs.append(f"{where}: {k} 同时写在 tags 与 random_fields"
                                    "（要么写死、要么随机，不能两头都要）")
                    if k in (drop or []):
                        errs.append(f"{where}: {k} 同时写在 drop_fields 与 random_fields")
                    if not isinstance(cands, list) or not cands:
                        errs.append(f"{where}: random_fields[{k}] 必须是候选值数组")
                        continue
                    opts = [en for _zh, en in fld.get("opts", [])]
                    bad = [v for v in cands if v not in opts]
                    if bad:
                        errs.append(f"{where}: random_fields[{k}] 的取值 {bad!r} 不是合法选项")
    return errs


def main():
    check_only = "--check" in sys.argv
    with open(SCENES, "r", encoding="utf-8") as fh:
        raw = fh.read()
    data = json.loads(raw)

    errs = validate(data)
    if errs:
        print(f"[build_scenes] 校验失败 {len(errs)} 条：")
        for e in errs:
            print("  · " + e)
        return 1

    # 派生 level（并核对：预设 id 不能与法典预设撞名）
    # ⚠️ 必须比 `pools['canon']`（**法典原文**），不能比 `R.canon()` ——
    #    后者 v3.9.0 起已经把场景库合并进去了，拿它比对等于"自己跟自己撞名"。
    canon_ids = set(_R.pools().get("canon", {}).keys())
    changed = 0
    for sc in data["scenes"]:
        if sc["id"] in canon_ids:
            print(f"[build_scenes] 预设 id 与法典撞名：{sc['id']}")
            return 1
        # v3.24.0：`random_variants` —— 套用时**从候选里抽一段短语**并进 extra。
        # 与 random_fields 的区别：那个抽字段选项（必须在词库里），这个抽自由短语
        # （用于"我坐着 / 我躺着"这类词库没有对应字段的构图差异）。
        rv = sc.get("random_variants")
        if rv is not None:
            if not isinstance(rv, (list, dict)) or not rv:
                errs.append(f"{where}: random_variants 必须是非空数组或对象")
            elif isinstance(rv, dict):
                # 多池：每个键一个池，池内独立抽一条
                for pk, body in rv.items():
                    items = body.get("items") if (isinstance(body, dict) and "items" in body) else body
                    if not isinstance(items, list) or not items:
                        errs.append(f"{where}: random_variants[{pk!r}] 必须是条目数组（或 {{label, items}}）")
                        continue
                    seen = set()
                    for j, v in enumerate(items):
                        if not isinstance(v, dict):
                            errs.append(f"{where}: random_variants[{pk!r}][{j}] 必须是 {{zh, extra}} 对象")
                            continue
                        if not str(v.get("extra") or "").strip():
                            errs.append(f"{where}: random_variants[{pk!r}][{j}] 的 extra 不能为空")
                        zh = str(v.get("zh") or "").strip()
                        if not zh:
                            errs.append(f"{where}: random_variants[{pk!r}][{j}] 缺 zh（面板要显示名字）")
                        elif zh in seen:
                            errs.append(f"{where}: random_variants[{pk!r}] 的 zh {zh!r} 重复")
                        else:
                            seen.add(zh)
            else:
                seen_zh = set()
                for j, v in enumerate(rv):
                    if not isinstance(v, dict):
                        errs.append(f"{where}: random_variants[{j}] 必须是 {{zh, extra}} 对象")
                        continue
                    ex = str(v.get("extra") or "").strip()
                    zh = str(v.get("zh") or "").strip()
                    if not ex:
                        errs.append(f"{where}: random_variants[{j}] 的 extra 不能为空")
                    if not zh:
                        errs.append(f"{where}: random_variants[{j}] 缺 zh（面板要显示名字）")
                    elif zh in seen_zh:
                        errs.append(f"{where}: random_variants 的 zh {zh!r} 重复")
                    else:
                        seen_zh.add(zh)
        lv = scene_level(sc["tags"], sc.get("extra", ""), sc.get("random_fields"),
                         sc.get("random_variants"))
        if int(sc.get("level", -1)) != lv:
            sc["level"] = lv
            changed += 1

    scenes = data["scenes"]
    data["_meta"]["counters"] = {
        "scenes": len(scenes),
        "groups": len(data.get("groups", [])),
        "by_group": {g["id"]: sum(1 for s in scenes if s["group"] == g["id"])
                     for g in data.get("groups", [])},
        "by_level": {str(n): sum(1 for s in scenes if s["level"] == n)
                     for n in range(5)},
    }
    data["_meta"]["levels_note"] = (
        "level 由 tools/build_scenes.py 按内容派生，勿手改；"
        "= max(各字段值的准入档位, extra 各标签档位)")

    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if check_only:
        if payload != raw:
            print("[build_scenes] --check 失败：磁盘 JSON 与派生结果不一致"
                  "（跑一次 python tools/build_scenes.py 重写）")
            return 1
        print(f"[build_scenes] --check 通过：{len(scenes)} 个预设，档位分布 "
              + " ".join(f"L{k}:{v}" for k, v in data["_meta"]["counters"]["by_level"].items()))
        return 0

    if payload != raw:
        with open(SCENES, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)

    print(f"[build_scenes] 已写出 {SCENES}"
          + (f"（派生档位更新 {changed} 条）" if changed else "（内容无变化）"))
    print(f"  预设 {len(scenes)} 个 · 分组 "
          + " / ".join(f"{k}={v}" for k, v in data["_meta"]["counters"]["by_group"].items()))
    print("  档位分布：" + "  ".join(
        f"L{k}={v}" for k, v in sorted(data["_meta"]["counters"]["by_level"].items())))
    print()
    print(f"  {'id':32s} {'档':>2s}  {'组':4s} 中文名")
    for sc in scenes:
        print(f"  {sc['id']:32s} L{sc['level']:<2d} {sc['group']:4s} {sc['zh']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
