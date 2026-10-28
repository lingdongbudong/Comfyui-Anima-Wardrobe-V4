# -*- coding: utf-8 -*-
"""角色固定特征基线（v3.46.0）。

钉死六件事：
  ① 表里每个 key 都是真角色（没有幽灵 key，写错=永不生效）
  ② extras / pick 全是 tag_level=0 的标签（L1+ 会抬档，L3+ 直接越档）
  ③ set 的字段与值都是词库真选项（否则被静默丢弃，用户以为改了其实没改）
  ④ 开启 appearance_follow → 角色带上固定特征；关闭 → 一个字不加
  ⑤ pick 池能真的抽出多种取值（不是恒定取第一条）
  ⑥ 表里没有的角色 → `char_feat_for` 返回空三元组，state 里不长 `_char_feat`
     （这才是零漂移的判据：不注入 = 不消耗 = 逐字节不变）

跑法：python tests/check_v3_charfeat.py
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

EMILIA = "emilia, re:zero kara hajimeru isekai seikatsu"
TRIGGER = "trigger, zenless zone zero"
HERTA = "the herta, honkai: star rail"
PHOEBE = "phoebe, wuthering waves"
PHOENIX = "phoenix reffaella, zenless zone zero"
EVANESCIA = "evanescia, honkai: star rail"
JADE = "jade, honkai: star rail"
HUTAO = "hu tao, genshin impact"
SCARLET = "scarlet, goddess of victory: nikke"
HUOHUO = "huohuo, honkai: star rail"
RAM = "ram, re:zero kara hajimeru isekai seikatsu"
REM = "rem, re:zero kara hajimeru isekai seikatsu"
LYNAE = "lynae, wuthering waves"
LINGSHA = "lingsha, honkai: star rail"
POWER = "power, chainsaw man"
YAOGUANG = "yao guang, honkai: star rail"
CYRENE = "cyrene, honkai: star rail"
ROBIN = "robin, honkai: star rail"
ROBIN_S = "robin (summeretto), honkai: star rail"
LUCIA = "lucia elowen, zenless zone zero"
ROXY = "roxy ifrita pryce, zenless zone zero"
SUNNA = "sunna, zenless zone zero"
CARTETHYIA = "cartethyia, wuthering waves"
SIGRID = "sigrid de l'azur, zenless zone zero"
CISSIA = "cissia, zenless zone zero"
SEED = "seed, zenless zone zero"
YESHUN = "ye shunguang, zenless zone zero"
YESHUN_W = "ye shunguang (enlightened state), zenless zone zero"
YIXUAN = "yixuan, zenless zone zero"
HSIN = "hsin, wuthering waves"
HSIN_I = "hsin (illumining form), wuthering waves"
HSIN_M = "hsin (moon fox), wuthering waves"
MORNYE = "mornye, wuthering waves"
SHORE = "shorekeeper, wuthering waves"
QINGXIAO = "qingxiao, wuthering waves"
YANGYANG = "yangyang (xuanling), wuthering waves"
SUISUI = "suisui, wuthering waves"
ZHEZHI = "zhezhi, wuthering waves"
OUTSIDER = "saber, fate (series)"


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [X ] {name}  {note}")
        FAILS.append(name)


def draw(role, seed, follow=True):
    return R.draw(level="sfw", seed=seed, force_role=role,
                  hair_follow=True, appearance_follow=follow)


def main():
    path = os.path.join(os.path.dirname(HERE), "presets", "char_feat.json")
    doc = json.load(io.open(path, encoding="utf-8"))
    table = doc.get("feats") or {}
    meta = doc.get("_meta") or {}

    print("── ① 表结构 ──")
    ck("有 feats 段且非空", isinstance(table, dict) and len(table) > 0,
       str(type(table)))
    ck("_meta 写了 rules", bool(meta.get("rules")))

    print("── ② 每个 key 都是真角色 ──")
    known = set()
    for c in R.characters_data().get("characters", []):
        known.add(str(c.get("tag") or "").strip().lower())
        known.add(str(c.get("trigger") or "").strip().lower())
    ghost = [k for k in table if k.strip().lower() not in known]
    ck("没有幽灵角色", not ghost, str(ghost[:5]))

    print("── ③ extras / pick 全是 L0 ──")
    bad = []
    for tag, rec in table.items():
        pool_words = list(rec.get("extras") or [])
        for _n, _p in (rec.get("pick") or {}).items():
            pool_words.extend(_p or [])
        for t in pool_words:
            lv = R.tag_level(str(t))
            if lv != 0:
                bad.append((tag, t, lv))
    ck("没有抬档标签", not bad, str(bad[:6]))

    print("── ④ set 的字段与值都是词库真选项 ──")
    bad_set = []
    for tag, rec in table.items():
        for k, v in (rec.get("set") or {}).items():
            _s, fld = R.field_by_key(k)
            allowed = {str(o[1]).strip().lower() for o in (fld or {}).get("opts", [])}
            if not fld or str(v).strip().lower() not in allowed:
                bad_set.append((tag, k, v))
    ck("set 没有词库外的字段/值", not bad_set, str(bad_set[:6]))

    print("── ⑤ 开启后真的写进去 ──")
    d = draw(EMILIA, 31)
    ck("爱蜜莉雅带上 pointy ears", "pointy ears" in d["tags"], str(d["tags"][:12]))
    ck("爱蜜莉雅没有动物耳（与精灵耳互斥）",
       not any(t in ("animal ears", "rabbit ears") for t in d["tags"]))
    d = draw(TRIGGER, 31)
    ck("扳机带上黑金属面甲", "black visor" in d["tags"] and "black metal" in d["tags"])
    ck("扳机双手叉腰（不拿枪）", "hands on own hips" in d["tags"], str(d["tags"]))
    ck("扳机带上灯带色", any(t.endswith(" light") for t in d["tags"]), str(d["tags"]))
    ck("扳机 eye_gaze 被清空", not str(d["state"].get("eye_gaze") or ""),
       repr(d["state"].get("eye_gaze")))
    ck("扳机 eyes_color 被清空", not str(d["state"].get("eyes_color") or ""),
       repr(d["state"].get("eyes_color")))
    d = draw(HERTA, 31)
    ck("大黑塔带上 witch hat", "witch hat" in d["tags"], str(d["tags"][:12]))
    d = draw(PHOEBE, 31)
    ck("菲比带上黑蝴蝶结", "black hair bow" in d["tags"], str(d["tags"][:12]))
    ck("菲比瞳色被强盖成紫（APPEAR 表写的是 blue eyes）",
       d["state"].get("eyes_color") == "purple eyes", repr(d["state"].get("eyes_color")))
    d = draw(PHOENIX, 31)
    ck("菲欧妮带上双麻花辫", "twin braids" in d["tags"], str(d["tags"][:12]))
    ck("菲欧妮的随机束法被压住", not str(d["state"].get("hair_tie") or ""),
       repr(d["state"].get("hair_tie")))
    d = draw(EVANESCIA, 31)
    ck("绯英带上粉色兔耳", "pink rabbit ears" in d["tags"], str(d["tags"][:12]))
    ck("绯英没有第二组耳朵/发饰", not str(d["state"].get("hair_acc") or ""),
       repr(d["state"].get("hair_acc")))
    ck("绯英瞳色是紫", d["state"].get("eyes_color") == "purple eyes",
       repr(d["state"].get("eyes_color")))
    d = draw(JADE, 31)
    ck("翡翠带上巫师帽", "witch hat" in d["tags"], str(d["tags"][:12]))
    ck("翡翠带上熟女气质", "mature female" in d["tags"], str(d["tags"]))
    d = draw(HUTAO, 31)
    ck("胡桃带上 top hat", "top hat" in d["tags"], str(d["tags"][:12]))
    ck("胡桃带上梅花瞳", "flower-shaped pupils" in d["tags"], str(d["tags"]))
    d = draw(SCARLET, 31)
    ck("红莲发色不再被 'hair between eyes' 顶掉",
       d["state"].get("hair_color") == "white hair",
       repr(d["state"].get("hair_color")))
    ck("红莲瞳色是红", d["state"].get("eyes_color") == "red eyes",
       repr(d["state"].get("eyes_color")))
    ck("红莲带上红花发饰", "red hair flower" in d["tags"], str(d["tags"][:12]))
    d = draw(HUOHUO, 31)
    ck("藿藿带上狐耳", "fox ears" in d["tags"], str(d["tags"][:12]))
    ck("藿藿带上狐尾", "fox tail" in d["tags"], str(d["tags"]))
    for name, role in (("拉姆", RAM), ("雷姆", REM)):
        d = draw(role, 31)
        ck(f"{name}带上单眼遮挡", "hair over one eye" in d["tags"], str(d["tags"][:12]))
        ck(f"{name}是短发", "short hair" in d["tags"], str(d["tags"]))
        ck(f"{name}头发没被抽成马尾", not str(d["state"].get("hair_tie") or ""),
           repr(d["state"].get("hair_tie")))

    print("── ⑥ 关闭后一个字都不加 ──")
    off = draw(EMILIA, 31, follow=False)
    ck("关闭时不写 pointy ears", "pointy ears" not in off["tags"])
    ck("关闭时不长 _char_feat 标记", "_char_feat" not in off["state"])
    off = draw(TRIGGER, 31, follow=False)
    ck("关闭时不写 black goggles", "black goggles" not in off["tags"])

    print("── ⑦ pick 池真的在抽 ──")
    colors = set()
    for sd in range(12):
        colors |= {t for t in draw(TRIGGER, sd)["tags"] if t.endswith(" light")}
    ck("灯带至少能抽出 3 种颜色", len(colors) >= 3, str(sorted(colors)))

    print("── ⑧ 表外角色零漂移 ──")
    ck("char_feat_for 返回空三元组",
       R.char_feat_for(OUTSIDER, 41) == ([], [], {}))
    d = draw(OUTSIDER, 41)
    ck("表外角色 state 里没有 _char_feat", "_char_feat" not in d["state"])

    print()
    if FAILS:
        print(f"[check_v3_charfeat] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print(f"[check_v3_charfeat] 通过：{len(table)} 个角色特征 · 8 组语义全部符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
