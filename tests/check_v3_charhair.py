# -*- coding: utf-8 -*-
"""角色官方发型对齐基线（v3.45.0）。

钉死四件事：
  ① 发型表里每个 key 都是真角色、每个值都是词库现成选项（写错=静默失效）
  ② 开关打开 → hair_len / hair_tie / hair_curl 被写成该角色的官方值
  ③ 开关关闭 → 一个字都不写（state 里没有 _hair_style_applied）
  ④ 表里没有的角色 → 开关开/关的抽取结果**逐字段相同**（零漂移）

跑法：python tests/check_v3_charhair.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")

FAILS = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [X ] {name}  {note}")
        FAILS.append(name)


def main():
    path = os.path.join(os.path.dirname(HERE), "presets", "char_hair_style.json")
    doc = json.load(io.open(path, encoding="utf-8"))
    styles = doc.get("styles") or {}

    print("── ① 表结构 ──")
    ck("有 styles 段且非空", isinstance(styles, dict) and len(styles) > 0,
       str(type(styles)))
    ck("_meta 声明来源", bool((doc.get("_meta") or {}).get("derived_from")))

    print("── ② 每个 key 都是真角色 ──")
    known = set()
    for c in R.characters_data().get("characters", []):
        known.add(str(c.get("tag") or "").strip().lower())
        known.add(str(c.get("trigger") or "").strip().lower())
    unknown = [k for k in styles if k.strip().lower() not in known]
    ck("没有幽灵角色", not unknown, str(unknown[:5]))

    print("── ③ 每个值都是词库选项 ──")
    allowed = {}
    for key in R.HAIR_STYLE_FIELDS:
        _s, fld = R.field_by_key(key)
        allowed[key] = {str(o[1]).strip().lower()
                        for o in (fld or {}).get("opts", [])}
    bad = []
    # v3.45.0：四个 HAIR_STYLE_FIELDS **都**接受哨兵 none —— `hair_style_for()`
    # 在词库校验之前就把哨兵收下，`apply_hair_style()` 再把它翻成空串（不输出任何标签）。
    # 业务上 hair_tie 用它表达「不束发」（13 个选项全是"束起来"，没有"散开"这一档），
    # hair_acc 用它表达「明确不加发饰」（否则机器人 / 短发角色会被随机塞兔耳、发圈）。
    # 早先这里限定 `key == "hair_tie"`，把 aria_(robot) 的 hair_acc="none" 误判成词库外值。
    SENTINEL = {"none", "散开", "不束发", "loose"}
    for tag, rec in styles.items():
        for key, val in (rec or {}).items():
            v = str(val).strip().lower()
            if key not in allowed:
                bad.append((tag, key, "未知字段"))
            elif v in SENTINEL:
                continue
            elif v not in allowed[key]:
                bad.append((tag, key, val))
    ck("没有词库外的值", not bad, str(bad[:5]))

    print("── ④ 开启后写入官方发型 ──")
    tag = "2b_(nier:automata)"
    st = R.draw(level="sfw", seed=7, force_role=tag, hair_follow=True)["state"]
    ck("2B 的长度被写成 short hair",
       st.get("hair_len") == "short hair", str(st.get("hair_len")))
    ck("报告里记了 applied", st.get("_hair_style") == "applied",
       str(st.get("_hair_style")))
    ck("打了不被裁剪的保护标记", bool(st.get("_hair_style_applied")))

    print("── ⑤ 关闭后一个字都不写 ──")
    st2 = R.draw(level="sfw", seed=7, force_role=tag, hair_follow=False)["state"]
    ck("报告里记了 off", st2.get("_hair_style") == "off", str(st2.get("_hair_style")))
    ck("没有保护标记", not st2.get("_hair_style_applied"))

    print("── ⑥ 权重 0 时不写（显式关闭优先）──")
    w = R.parse_weights('{"fields":{"hair_len":0}}')
    st3 = R.draw(level="sfw", seed=7, force_role=tag, weights=w,
                 hair_follow=True)["state"]
    ck("hair_len 权重 0 → 不写该字段", st3.get("hair_len") != "short hair",
       str(st3.get("hair_len")))

    print("── ⑦ 表里没有的角色：开/关逐字段相同（零漂移）──")
    missing = None
    for c in R.characters_data().get("characters", []):
        t = str(c.get("tag") or "")
        if t and t.lower() not in {k.lower() for k in styles}:
            missing = t
            break
    if not missing:
        ck("找一个无发型数据的角色", False, "全库都有数据")
    else:
        a = R.draw(level="sfw", seed=11, force_role=missing, hair_follow=True)["state"]
        b = R.draw(level="sfw", seed=11, force_role=missing, hair_follow=False)["state"]
        diff = [k for k in set(a) | set(b)
                if not str(k).startswith("_") and a.get(k) != b.get(k)]
        ck(f"「{missing}」开/关结果一致", not diff, str(diff[:6]))

    # ── 8. 发型选择器（v3.47.0）─────────────────────────────────────
    # 用雷姆验证：她是短发、且 char_feat 的 drop 里含 hair_tie/hair_len，
    # 是这套机制最容易翻车的组合（drop 会静默清掉选择器写的值）。
    REM = "rem, re:zero kara hajimeru isekai seikatsu"

    def _txt(picks):
        return R.draw(level="sfw", seed=31, force_role=REM, hair_picks=picks)["text"]

    base = _txt({})
    same = _txt({"hair_len": R.HAIR_PICK_AUTO, "hair_tie": R.HAIR_PICK_AUTO,
                 "hair_curl": R.HAIR_PICK_AUTO, "hair_acc": R.HAIR_PICK_AUTO})
    ck("全「角色标签发型」与旧行为逐字一致", base == same,
       f"{len(base)} vs {len(same)}")

    tie = _txt({"hair_tie": "twintails"})
    ck("显式双马尾能进正文（不被 drop 清掉）", "twintails" in tie, tie[:60])
    ck("双马尾自动配长发（G2 互斥组要求）",
       "long hair" in tie and "short hair" not in tie, tie[:60])

    cut = _txt({"hair_len": "bob cut"})
    ck("显式 bob cut 能进正文", "bob cut" in cut, cut[:60])
    ck("显式长度时 extras 的 short hair 被剔掉", "short hair" not in cut, cut[:60])

    # 选项文本是「中文｜英文」，取值必须还原成英文；裸标签（老工作流）也不能坏
    ck("带中文的选项还原成英文标签",
       R.hair_pick_strip("及腰超长发｜very long hair") == "very long hair",
       R.hair_pick_strip("及腰超长发｜very long hair"))
    ck("裸标签不受影响（老工作流兼容）",
       R.hair_pick_strip("twintails") == "twintails"
       and R.hair_pick_strip(R.HAIR_PICK_AUTO) == R.HAIR_PICK_AUTO,
       R.hair_pick_strip("twintails"))
    ck("中文选项能直接驱动出图",
       "twintails" in _txt({"hair_tie": "双马尾｜twintails"}), "中文选项未生效")

    rnd = _txt({"hair_tie": R.HAIR_PICK_RANDOM})
    ck("束法选「随机」时不写束法标签",
       not any(t in rnd for t in ("twintails", "ponytail", "braid")), rnd[:60])

    print()
    if FAILS:
        print(f"[check_v3_charhair] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print(f"[check_v3_charhair] 通过：{len(styles)} 条发型数据 · 7 组语义全部符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
