# -*- coding: utf-8 -*-
"""用户角色覆盖层基线（v3.4.0：角色编辑 + 自定义角色）。

这一层存的是**用户自己攒下来的角色** —— 编辑过的内置角色、自己新增的角色、
自己上传的预览图。丢了没法重建，所以别处可以松，这几条必须钉死：

  ① 原子写：写盘不产生 0 字节文件、不留 .tmp 残留
  ② 参数校验：空 / 大写 / 中文 / 超长的 trigger、超限图片一律拒绝，且**不落盘**
  ③ 合并正确性：edits 覆盖生效、custom 入池、works.count 重算、新作品补行
  ④ 缓存纪律：写操作后**必须 clear_cache** 才看得到变化（这条证明缓存清理是必需的）
  ⑤ 删除 / 恢复默认：自定义只能删、内置只能还原，走错要报错
  ⑥ 内置文件不被改写：全程 presets/anima_v4_characters.json 逐字节不变
  ⑦ 图片：合法图落盘 + 指针写进覆盖层；非法字节 / 超大 / 路径穿越一律拒绝

⚠️ 测试把模块里的文件路径**重定向到临时目录**，全程不碰
   presets/user_characters.json 与 presets/user_thumbs/ ——
   否则跑一次测试就把用户真实的角色改动清空了。

跑法：python tests/check_v3_userdata.py
"""
import base64
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

S = _boot.load("anima_v4_store")
R = _boot.load("anima_v4_rules")

FAILS = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="av3userchars-")

# 路径重定向 —— 隔离真实用户数据
S.PRESET_DIR = TMP
S.USER_CHARS_FILE = os.path.join(TMP, "user_characters.json")
S.USER_THUMB_DIR = os.path.join(TMP, "user_thumbs")

BUILTIN = os.path.join(PLUGIN, "presets", "anima_v4_characters.json")
BUILTIN_SHA_BEFORE = None

# 1×1 PNG（合法最小图）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAF"
    "BQIAX8jx0gAAAABJRU5ErkJggg==")


def builtin_len():
    return len(json.load(open(BUILTIN, encoding="utf-8"))["characters"])


def main():
    global BUILTIN_SHA_BEFORE
    import hashlib
    BUILTIN_SHA_BEFORE = hashlib.sha256(open(BUILTIN, "rb").read()).hexdigest()

    R.clear_cache()
    base_n = len(R.characters_data()["characters"])
    ck("初始合并结果 == 内置条数（还没有覆盖层）", base_n == builtin_len(),
       f"{base_n} vs {builtin_len()}")

    # ── ① 容错 ──────────────────────────────────────────────────────
    print("\n── ① 容错 ──")
    ov = S.load_user_characters()
    ck("文件不存在 → 空结构", ov == {"edits": {}, "custom": []}, str(ov))
    with open(S.USER_CHARS_FILE, "w", encoding="utf-8") as fh:
        fh.write("{ 这不是 JSON")
    ov = S.load_user_characters()
    ck("坏 JSON → 降级空结构，不抛", ov == {"edits": {}, "custom": []}, str(ov))
    ck("坏文件被另存为 .broken", os.path.exists(S.USER_CHARS_FILE + ".broken"))
    if os.path.exists(S.USER_CHARS_FILE + ".broken"):
        os.remove(S.USER_CHARS_FILE + ".broken")
    if os.path.exists(S.USER_CHARS_FILE):
        os.remove(S.USER_CHARS_FILE)
    R.clear_cache()

    # ── ② 参数校验 ──────────────────────────────────────────────────
    print("\n── ② 参数校验（拒绝时必须不落盘）──")

    def rejected(fields, note=""):
        try:
            S.save_user_character("create", "", fields)
            return False
        except ValueError:
            return True

    ck("空 trigger 被拒", rejected({"trigger": "  "}))
    ck("含大写字母的 trigger 被拒", rejected({"trigger": "Alice"}), "danbooru 全小写")
    ck("含中文的 trigger 被拒", rejected({"trigger": "初音未来"}))
    ck("超长 trigger 被拒", rejected({"trigger": "a" * 200}))
    ck("被拒时没有落盘", not os.path.exists(S.USER_CHARS_FILE))

    # ── ③ 新增（create）与合并 ──────────────────────────────────────
    print("\n── ③ 新增 + 合并 ──")
    # 先把缓存热起来，才能验证"不清缓存就看不到变化"
    warm = len(R.characters_data()["characters"])
    rec, _ = S.save_user_character("create", "", {
        "trigger": "my custom girl, my series", "zh": "自捏妹子", "work": "my series"})
    ck("新增返回的 tag 带 user_ 前缀", rec["tag"].startswith("user_"), rec["tag"])
    ck("thumb 默认等于 tag（没图时退化成首字母色块）",
       rec["thumb"] == rec["tag"], rec["thumb"])

    merged = R.characters_data()
    ck("未清缓存时合并结果**不变**（证明缓存确实存在）",
       len(merged["characters"]) == warm, str(len(merged["characters"])))
    R.clear_cache()
    merged = R.characters_data()
    ck("clear_cache 后新角色出现", len(merged["characters"]) == warm + 1,
       f"{len(merged['characters'])} vs {warm + 1}")

    got = [c for c in merged["characters"] if c["tag"] == rec["tag"]]
    ck("合并结果里能找到新角色", len(got) == 1)
    ck("新角色标记为 user", bool(got) and got[0].get("src") == "user",
       str(got[0].get("src")) if got else "")

    w = [x for x in merged["works"] if x["en"] == "my series"]
    ck("库里没有的作品名 → 自动补一行作品", len(w) == 1,
       str([x["en"] for x in merged["works"] if "my" in x["en"]]))
    ck("补出的作品 count 计入该角色", w and w[0]["count"] == 1,
       str(w[0]["count"]) if w else "")

    # works.count 与 characters 实际条数必须处处一致（前端有条断言依赖它）
    ids = {x["id"] for x in merged["works"]}
    cnt = {}
    for c in merged["characters"]:
        wid = next((x["id"] for x in merged["works"]
                    if x["en"] == c.get("work", "")), "")
        if wid:
            cnt[wid] = cnt.get(wid, 0) + 1
    bad = [x["id"] for x in merged["works"] if cnt.get(x["id"], 0) != x["count"]]
    ck("每个 works.count 与实际条数一致", not bad, str(bad[:4]))
    ck("所有角色的 work 都能落到 works.id", all(
        (c.get("work", "") == "")
        or any(x["en"] == c.get("work", "") for x in merged["works"])
        for c in merged["characters"]))

    # 新角色进 role 候选池（用 trigger）
    pool_trigs = {o[1] for o in R.role_pool(99)}
    ck("新角色进入 role 随机候选池", rec["trigger"] in pool_trigs)

    # ── ④ trigger 去重（与内置撞名）──────────────────────────────────
    print("\n── ④ 自定义 tag 去重 ──")
    taken = [c.get("tag") for c in merged["characters"]]
    dup, _ = S.save_user_character("create", "", {"trigger": "my custom girl, my series"},
                                   taken_tags=taken)
    ck("同 trigger 再建一个不会撞 tag", dup["tag"] != rec["tag"], dup["tag"])
    ck("撞名时追加序号", dup["tag"].endswith("_2"), dup["tag"])
    R.clear_cache()

    # ── ⑤ 编辑内置角色 ──────────────────────────────────────────────
    print("\n── ⑤ 编辑内置角色 ──")
    builtin_tag = next(c["tag"] for c in R.characters_data()["characters"]
                       if c.get("src") != "user")
    orig = next(c for c in R.characters_data()["characters"] if c["tag"] == builtin_tag)
    orig_trigger = orig["trigger"]

    S.save_user_character("edit", builtin_tag, {
        "trigger": "edited trigger, some series", "zh": "改过的中文名", "work": "some series"})
    R.clear_cache()
    cur = next(c for c in R.characters_data()["characters"] if c["tag"] == builtin_tag)
    ck("内置角色 trigger 覆盖生效", cur["trigger"] == "edited trigger, some series",
       cur["trigger"])
    ck("内置角色中文名覆盖生效", cur["zh"] == "改过的中文名", cur["zh"])
    ck("未改的字段（如 pop）保持内置值", cur["pop"] == orig["pop"])
    ck("覆盖项落在 edits 里", builtin_tag in S.load_user_characters()["edits"])

    # 留空 = 清除覆盖、回退内置值
    S.save_user_character("edit", builtin_tag, {
        "trigger": orig_trigger, "zh": "", "work": ""})
    R.clear_cache()
    cur = next(c for c in R.characters_data()["characters"] if c["tag"] == builtin_tag)
    ck("中文名留空 → 清除覆盖、回退内置值", cur["zh"] == orig["zh"],
       f"{cur['zh']} vs {orig['zh']}")
    ck("作品留空 → 回退内置值", cur["work"] == orig["work"], cur["work"])
    ck("trigger 仍被保留（它是必填）",
       S.load_user_characters()["edits"][builtin_tag].get("trigger") == orig_trigger)

    # ── ⑥ 自定义角色可直接编辑 ──────────────────────────────────────
    print("\n── ⑥ 编辑自定义角色 ──")
    S.save_user_character("edit", rec["tag"], {
        "trigger": "renamed girl, my series", "zh": "改名了", "work": "my series"})
    R.clear_cache()
    cur = next(c for c in R.characters_data()["characters"] if c["tag"] == rec["tag"])
    ck("自定义角色 trigger 直接改记录", cur["trigger"] == "renamed girl, my series",
       cur["trigger"])
    ck("自定义角色编辑不写进 edits（它本来就是 custom 记录）",
       rec["tag"] not in S.load_user_characters()["edits"])

    # ── ⑦ 图片 ──────────────────────────────────────────────────────
    print("\n── ⑦ 预览图 ──")
    slug = S.set_user_thumb(builtin_tag, PNG_1PX)
    files = [f for f in os.listdir(S.USER_THUMB_DIR) if f.startswith(slug + ".")]
    ck("合法图落盘成 webp/jpg/png 之一", len(files) == 1, str(os.listdir(S.USER_THUMB_DIR)))
    ck("图 slug 带 user_ 前缀（不覆盖内置原图）", slug.startswith("user_"), slug)
    ck("图片指针写进覆盖层",
       S.load_user_characters()["edits"][builtin_tag].get("thumb") == slug)
    ck("落盘过程不留 .tmp 残留",
       not [f for f in os.listdir(S.USER_THUMB_DIR) if f.endswith(".tmp")])

    try:
        S.set_user_thumb(builtin_tag, b"this is not an image")
        ck("非法图片字节被拒", False)
    except ValueError:
        ck("非法图片字节被拒", True)

    try:
        S.set_user_thumb(builtin_tag, b"\x89PNG\r\n\x1a\n" + b"0" * (3 * 1024 * 1024))
        ck("超大图片被拒", False)
    except ValueError:
        ck("超大图片被拒", True)

    S.clear_user_thumb(builtin_tag)
    R.clear_cache()
    ck("清除图后文件被删掉",
       not [f for f in os.listdir(S.USER_THUMB_DIR) if f.startswith(slug + ".")])
    ck("清除图后覆盖层指针也清掉",
       not S.load_user_characters()["edits"].get(builtin_tag, {}).get("thumb"))

    # ── ⑧ 删除 / 恢复默认 ───────────────────────────────────────────
    print("\n── ⑧ 删除与恢复默认 ──")
    try:
        S.delete_user_character(builtin_tag)
        ck("内置角色不能走删除", False)
    except ValueError:
        ck("内置角色不能走删除（提示改用恢复默认）", True)

    S.delete_user_character(rec["tag"])
    R.clear_cache()
    ck("自定义角色删除后从合并结果消失",
       not any(c["tag"] == rec["tag"] for c in R.characters_data()["characters"]))

    try:
        S.reset_user_character(dup["tag"])
        ck("自定义角色不能走恢复默认", False)
    except ValueError:
        ck("自定义角色不能走恢复默认（提示改用删除）", True)

    S.reset_user_character(builtin_tag)
    R.clear_cache()
    cur = next(c for c in R.characters_data()["characters"] if c["tag"] == builtin_tag)
    ck("恢复默认后 trigger 回到内置值", cur["trigger"] == orig_trigger, cur["trigger"])
    ck("恢复默认后 edits 里不再有它",
       builtin_tag not in S.load_user_characters()["edits"])

    # ── ⑨ 原子写 / 上限 ─────────────────────────────────────────────
    print("\n── ⑨ 原子写与上限 ──")
    S.save_user_character("edit", builtin_tag, {"trigger": "x, y", "zh": "", "work": ""})
    raw = open(S.USER_CHARS_FILE, encoding="utf-8").read()
    ok_json = True
    try:
        json.loads(raw)
    except Exception:
        ok_json = False
    ck("落盘内容是合法 JSON", ok_json)
    ck("文件末尾有换行（与其它 user_*.json 一致）", raw.endswith("\n"))
    ck("目录里没有 .tmp 残留",
       not [f for f in os.listdir(TMP) if f.endswith(".tmp")], str(os.listdir(TMP)))

    old_max = S.MAX_USER_CHARS
    S.MAX_USER_CHARS = len(S.load_user_characters()["custom"])
    try:
        S.save_user_character("create", "", {"trigger": "one more, s"})
        ck("达到上限后拒绝新增", False)
    except ValueError:
        ck("达到上限后拒绝新增", True)
    S.MAX_USER_CHARS = old_max

    # ── ⑩ 路径穿越防护 ──────────────────────────────────────────────
    print("\n── ⑩ 图片名安全 ──")
    try:
        S._write_thumb_file("../../evil", PNG_1PX)
        ck("非法 slug 被拒（路径穿越）", False)
    except ValueError:
        ck("非法 slug 被拒（路径穿越）", True)

    # ── ⑪ 特征标签（v3.5.0：列表型字段）────────────────────────────
    print("\n── ⑪ 特征标签 ──")

    def pick_builtin_without_figure():
        """挑一个"APPEAR 表管不到、且当前没有体型标签"的内置角色。

        ⚠️ 两个前提缺一不可：
          ① 不能落在源 HTML 的 APPEAR 表里 —— appearance_for 对那 221 条
             是**整表优先**，根本不会去看 tags，拿它们测等于没测；
          ② 当前 figure 必须是空 —— 否则"加了 large breasts 变成 large breasts"
             是恒真的。
        """
        ap = R.appear()
        for c in R.characters_data()["characters"]:
            if str(c.get("src") or "") == "user":
                continue
            trig = (c.get("trigger") or "").strip()
            if not trig or trig.lower() in ap:
                continue
            if R.appearance_for(trig).get("figure"):
                continue
            return c
        return None

    tc = pick_builtin_without_figure()
    ck("找到一个可用于验证「标签 → 体型」的内置角色", bool(tc),
       str(tc and tc.get("tag")))
    t_tag, t_trig, t_tags = tc["tag"], tc["trigger"], list(tc.get("tags") or [])

    S.save_user_character("edit", t_tag,
                          {"trigger": t_trig, "zh": "", "work": "",
                           "tags": ["large breasts"]})
    R.clear_cache()
    edited = S.load_user_characters()["edits"][t_tag]
    ck("tags 以**列表**形态落进覆盖层", isinstance(edited.get("tags"), list),
       repr(edited.get("tags")))
    cur = next(x for x in R.characters_data()["characters"] if x["tag"] == t_tag)
    ck("合并结果里 tags 被**整条替换**（不是并集）",
       cur["tags"] == ["large breasts"], str(cur["tags"]))
    ck("内置原文的 tags 未被改动",
       R.builtin_char_index()[t_tag]["tags"] == t_tags)

    # ★ 最关键的一条：改动真的进了引擎，而不只是躺在 JSON 里
    ck("引擎（外貌对齐）采用了新标签 → figure = large breasts",
       R.appearance_for(t_trig).get("figure") == "large breasts",
       str(R.appearance_for(t_trig)))

    # 空列表 = 清除覆盖、回退内置（与中文名/作品同一套语义）
    S.save_user_character("edit", t_tag, {"trigger": t_trig, "tags": []})
    R.clear_cache()
    cur = next(x for x in R.characters_data()["characters"] if x["tag"] == t_tag)
    ck("tags 传空 → 回退内置标签", cur["tags"] == t_tags, str(cur["tags"])[:70])
    ck("清掉覆盖后引擎也不再用它",
       R.appearance_for(t_trig).get("figure") is None,
       str(R.appearance_for(t_trig)))
    ck("edits 里不再残留 tags 键",
       "tags" not in S.load_user_characters()["edits"][t_tag])

    def rejects_tags(v, note=""):
        try:
            S.save_user_character("edit", t_tag, {"trigger": t_trig, "tags": v})
            return False, ""
        except ValueError as exc:
            return True, str(exc)

    ok, msg = rejects_tags(["a" * 41])
    ck("单条超 40 字符被拒（引擎会忽略更长的）", ok and "40" in msg, msg)
    ok, msg = rejects_tags(["初音"])
    ck("含中文的标签被拒", ok, msg)
    ok, msg = rejects_tags([f"t{i} item" for i in range(41)])
    ck("超过 40 条被拒", ok and "40" in msg, msg)
    ck("被拒时不落盘", "tags" not in (S.load_user_characters()["edits"]
                                     .get(t_tag) or {}))

    # 逗号分隔字符串自动拆分 + 大写归一为小写
    S.save_user_character("edit", t_tag,
                          {"trigger": t_trig, "tags": "Large Breasts, aqua eyes"})
    R.clear_cache()
    cur = next(x for x in R.characters_data()["characters"] if x["tag"] == t_tag)
    ck("逗号分隔字符串被拆成多条", cur["tags"] == ["large breasts", "aqua eyes"],
       str(cur["tags"]))
    ck("大写输入被归一为小写（标签比 trigger 宽松）",
       cur["tags"] == [t.lower() for t in cur["tags"]], str(cur["tags"]))

    # 自定义角色的空标签 = 真的没有标签（不是"回退内置"，它没有内置）
    crec, _ = S.save_user_character("create", "", {
        "trigger": "tag test girl, tag series", "tags": ["solo", "smile"]})
    R.clear_cache()
    mc = next(x for x in R.characters_data()["characters"] if x["tag"] == crec["tag"])
    ck("自定义角色能自带特征标签", mc["tags"] == ["solo", "smile"], str(mc["tags"]))
    S.save_user_character("edit", crec["tag"], {
        "trigger": "tag test girl, tag series", "tags": []})
    R.clear_cache()
    mc = next(x for x in R.characters_data()["characters"] if x["tag"] == crec["tag"])
    ck("自定义角色清空标签 = 真的没有标签", mc["tags"] == [], str(mc["tags"]))

    S.reset_user_character(t_tag)
    S.delete_user_character(crec["tag"])
    R.clear_cache()

    # ── ⑫ 内置文件零改动 ────────────────────────────────────────────
    print("\n── ⑫ 内置角色库零改动 ──")
    import hashlib
    after = hashlib.sha256(open(BUILTIN, "rb").read()).hexdigest()
    ck("presets/anima_v4_characters.json 逐字节未变", after == BUILTIN_SHA_BEFORE)

    print("\n" + "=" * 64)
    if FAILS:
        print(f"[check_v3_userdata] 失败 {len(FAILS)} 项：" + " · ".join(FAILS))
        return 1
    print("[check_v3_userdata] 通过：11 组语义全部符合预期")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
