# -*- coding: utf-8 -*-
"""为角色库里的每位角色抓一张缩略图（联网，可中断可续跑）。

产物：`presets/thumbs/<slug>.webp`（160×160，约 4 KB/张）。
面板的「角色库」页签用它做图片预览；抓不到的会退化成首字母色块，
所以**这个脚本缺席不影响插件可用**，只是浏览体验差一点。

数据源与 `build_characters.py` 同源：`safebooru.donmai.us`
（danbooru.donmai.us 在国内被墙，safebooru 是它的 SFW 镜像，同一套 API）。

用法：
    python_embeded/python.exe tools/fetch_character_thumbs.py
    ... --limit 24                 # 小批量试跑
    ... --only-work "zenless zone zero"
    ... --force                    # 已有的也重抓
    ... --dry                      # 只统计不下载

⚠️ 必须用 ComfyUI 的内嵌 Python（`python_embeded`）——
   转 webp 依赖 Pillow，系统 Python 里通常没有。
   没有 Pillow 时会退化成直接存 jpg，面板两种都认。

⚠️ 为什么必须算「真实像素」而不是只看文件大小：
   镜像上存在**损坏的预览图**。实测抓到过一张 5×160 的（366 字节）——
   它是合法 webp、Pillow 也打得开，但在面板里显示成一根竖线，
   比没有图还难看。这种图只能靠 min(宽,高) 拦下来。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)

CHARS_JSON = os.path.join(PLUGIN, "presets", "anima_v4_characters.json")
THUMB_DIR = os.path.join(PLUGIN, "presets", "thumbs")

MIRROR = "https://safebooru.donmai.us"

# ⚠️ 反直觉但实测如此：safebooru 的 WAF **专门拦浏览器 UA**。
#    同一个 URL：curl 默认 UA → 200，Python 默认 UA → 200，
#    Chrome UA → **403 Forbidden**。所以这里刻意用 curl 的 UA。
UA = "curl/8.4.0"

THUMB_SIZE = 160          # 缩略图最长边（面板卡片就是这个尺寸）
WEBP_QUALITY = 82

# 预览图任一边小于这个像素数 → 视为坏图，换下一张
MIN_SIDE = 60

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_net_lock = threading.Semaphore(16)     # 最多 16 路并发
_last = [0.0]


def http_json(url, tries=4, timeout=60):
    """带退避的 GET，返回 JSON。"""
    for i in range(tries):
        with _net_lock:
            # 礼貌间隔：safebooru 是志愿者镜像，别把它打挂
            gap = 0.12 - (time.time() - _last[0])
            if gap > 0:
                time.sleep(gap)
            _last[0] = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with _opener.open(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(1.5 * (i + 1))
    return None


def http_bytes(url, tries=4, timeout=75):
    """带退避的 GET，返回原始字节。"""
    for i in range(tries):
        with _net_lock:
            gap = 0.12 - (time.time() - _last[0])
            if gap > 0:
                time.sleep(gap)
            _last[0] = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with _opener.open(req, timeout=timeout) as r:
                    return r.read()
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(1.5 * (i + 1))
    return None


def has_pillow():
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def save_webp(raw, path):
    """转 webp。没有 Pillow 就原样落盘为 .jpg（面板两种都认）。

    返回 (格式, (宽, 高))；尺寸过小由调用方判失败并删掉。
    """
    if has_pillow():
        import io as _io
        from PIL import Image
        im = Image.open(_io.BytesIO(raw)).convert("RGB")
        im.thumbnail((THUMB_SIZE, THUMB_SIZE))
        im.save(path, "WEBP", quality=WEBP_QUALITY, method=4)
        return "webp", im.size
    alt = os.path.splitext(path)[0] + ".jpg"
    with open(alt, "wb") as fh:
        fh.write(raw)
    return "jpg", (0, 0)


def pick_urls(tag):
    """取该角色按分数排序的前几张图，返回 [(url, 宽, 高), ...]。

    返回**多张**而不是一张：镜像上有坏预览图（5×160），只取第一张就可能踩到。

    用 `order:score` 而不是默认排序 —— 默认是 id 倒序（最新一张），
    实测分数常只有个位数，是随手涂鸦；按分数取才是代表作。
    """
    out = []
    for cand in (f"{MIRROR}/posts.json?tags="
                 f"{urllib.parse.quote(f'{tag} order:score')}&limit=6",
                 f"{MIRROR}/posts.json?tags="
                 f"{urllib.parse.quote(tag)}&limit=6"):
        try:
            d = http_json(cand)
        except Exception:
            continue
        for p in (d or []):
            u = (p.get("preview_file_url")
                 or p.get("large_file_url") or p.get("file_url"))
            if not u:
                continue
            out.append((u, int(p.get("image_width") or 0),
                        int(p.get("image_height") or 0)))
        if out:
            break
    return out


def fetch_one(c):
    """抓一位角色的缩略图。返回 (slug, 状态字符串)。"""
    slug = c.get("thumb") or re.sub(r"[^a-z0-9]+", "_", c["tag"].lower())
    dst = os.path.join(THUMB_DIR, f"{slug}.webp")
    cands = pick_urls(c["tag"])
    if not cands:
        return slug, "无图"

    last = "无图"
    for url, w, h in cands:
        # posts 自带宽高：过小直接跳过，省一次下载
        if w and h and min(w, h) < MIN_SIDE:
            last = f"图过小 {w}x{h}"
            continue
        try:
            raw = http_bytes(url)
        except Exception as exc:
            last = f"下载失败 {type(exc).__name__}"
            continue
        if not raw:
            last = "空响应"
            continue
        try:
            fmt, size = save_webp(raw, dst)
        except Exception as exc:
            last = f"转换失败 {exc}"
            continue
        # 落盘后再验真实像素：posts 的宽高字段偶尔与实物不符
        if fmt == "webp" and size and min(size) < MIN_SIDE:
            try:
                os.remove(dst)
            except OSError:
                pass
            last = f"图过小 {size[0]}x{size[1]}"
            continue
        return slug, ("ok" if fmt == "webp" else "ok(jpg)")
    return slug, last


def verify_existing(dry=False):
    """扫描已有缩略图，把**尺寸过小或读不出**的删掉，当作待抓重来。

    为什么要主动清理：镜像上有一批坏预览图（实测 47×160 / 160×42 / 5×160），
    它们是合法 webp、Pillow 打得开，但在面板里显示成一条细线 —— 比没有图还难看。
    脚本早期版本没有尺寸校验，这些坏图已经落盘了；不清掉的话
    「已有就跳过」的逻辑会让它们永远留着。

    只读图片头（`Image.open` 不解码像素），2600 张不到 1 秒，所以每次都跑。
    `dry=True` 时只报告不删 —— `--dry` 得保持只读语义。
    """
    if not has_pillow():
        return []
    from PIL import Image
    bad = []
    for f in os.listdir(THUMB_DIR):
        if not f.lower().endswith((".webp", ".jpg", ".png")):
            continue
        p = os.path.join(THUMB_DIR, f)
        try:
            with Image.open(p) as im:
                size = im.size
            if min(size) < MIN_SIDE:
                bad.append((f, size))
        except Exception:
            bad.append((f, "unreadable"))
    if not dry:
        for f, _s in bad:
            try:
                os.remove(os.path.join(THUMB_DIR, f))
            except OSError:
                pass
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已有的也重抓")
    ap.add_argument("--only-work", default="", help="只抓某个作品（work 字段）")
    ap.add_argument("--limit", type=int, default=0, help="最多抓几张（0 = 不限）")
    ap.add_argument("--dry", action="store_true", help="只统计不下载")
    # v3.12.0：删掉"角色库里已经没有"的缩略图。
    # 为什么需要：build_characters.py 每次重建都会换掉一批角色
    #（NPC / 男性被过滤 / 作品调整），旧图会留成孤儿 —— 白占空间，
    # 还会混进分享包。默认**不删**，要显式加 --prune。
    ap.add_argument("--prune", action="store_true",
                    help="删掉角色库里已不存在的缩略图（默认不删）")
    args = ap.parse_args()

    if not os.path.exists(CHARS_JSON):
        print("找不到 presets/anima_v4_characters.json —— 先跑 build_characters.py")
        return 2

    with open(CHARS_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    chars = data.get("characters", [])
    if args.only_work:
        chars = [c for c in chars if c.get("work") == args.only_work]

    pillow = has_pillow()
    print(f"角色 {len(chars)} 条 · Pillow {'有' if pillow else '无（将存 jpg）'}")

    os.makedirs(THUMB_DIR, exist_ok=True)

    # ── --prune：删掉角色库里已不存在的缩略图（v3.12.0）───────────
    # ⚠️ 与 --only-work 互斥：那个只筛了一个作品的角色，拿它当"全集"会把
    #    其它作品的图全判成孤儿删掉。
    if args.prune:
        if args.only_work:
            print("⚠️ --only-work 与 --prune 不能同时用（会误删其它作品的图），已跳过 prune")
        else:
            need = {c.get("thumb") for c in chars if c.get("thumb")}
            orphans = [f for f in os.listdir(THUMB_DIR)
                       if f.lower().endswith((".webp", ".jpg", ".png"))
                       and f.rsplit(".", 1)[0] not in need]
            if args.dry:
                print(f"[--dry] 会删孤儿缩略图 {len(orphans)} 张：{orphans[:6]}")
            else:
                gone = 0
                for f in orphans:
                    try:
                        os.remove(os.path.join(THUMB_DIR, f))
                        gone += 1
                    except OSError:
                        pass
                print(f"已删除孤儿缩略图 {gone} 张（角色库里已没有它们）")

    # 先自愈：清掉尺寸过小的坏图，让它们回到「待抓」里重来
    bad = verify_existing(dry=args.dry)
    if bad:
        print(f"{'发现' if args.dry else '清理'}坏图 {len(bad)} 张"
              f"（尺寸过小/读不出）：{bad[:5]}")

    # 断点续传：已有 webp / jpg / png 的都跳过。
    # 三种后缀都认 —— 面板的 /thumb 路由也会挨个试，不然重跑会把
    # 之前存成 jpg 的又抓一遍。
    todo, have = [], 0
    for c in chars:
        slug = c.get("thumb") or ""
        if not slug:
            continue
        exists = any(os.path.exists(os.path.join(THUMB_DIR, f"{slug}.{e}"))
                     for e in ("webp", "jpg", "png"))
        if exists and not args.force:
            have += 1
            continue
        todo.append(c)

    if args.limit:
        todo = todo[: args.limit]
    print(f"待抓 {len(todo)} 张（已有 {have} 张）")

    if args.dry:
        print("--dry：不下载")
        return 0
    if not todo:
        print("没有待抓的图")
        return 0

    t0 = time.time()
    ok = fail = done = 0
    fails = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for slug, st in ex.map(fetch_one, todo):
            done += 1
            if st.startswith("ok"):
                ok += 1
            else:
                fail += 1
                if len(fails) < 8:
                    fails.append((slug, st))
            if done % 100 == 0:
                print(f"   … {done}/{len(todo)}  成功 {ok} 失败 {fail}"
                      f"  用时 {time.time() - t0:.0f}s", flush=True)

    files = [f for f in os.listdir(THUMB_DIR)
             if f.lower().endswith((".webp", ".jpg", ".png"))]
    size_mb = sum(os.path.getsize(os.path.join(THUMB_DIR, f))
                  for f in files) / 1024 / 1024
    print(f"\n完成：成功 {ok} · 失败 {fail} · 用时 {time.time() - t0:.0f}s")
    print(f"thumbs 目录共 {len(files)} 个文件 · {size_mb:.1f} MB")
    if fails:
        print(f"失败样例（前 {len(fails)}）：{fails}")
        print("（失败的大多是该角色在 SFW 镜像上没有图，属正常，重跑会再试）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
