# -*- coding: utf-8 -*-
"""从**真实出图**的 PNG 里导出 workflow（UI JSON），当元数据注入的回归夹具。

为什么夹具必须是真图里的那份：
    `tests/check_v3_pngmeta.py` 要钉住的是「正文确实没进元数据」这个病、
    以及「注入了之后写进了哪几处」。如果我们自己手搓一份工作流当夹具，
    测的是想象出来的链路 —— 真实工作流里节点是 CR Text / StringConcatenate /
    Reroute 混着来的，手搓必然简化掉关键形状（本项目在角色库上就是这么翻过车的）。

用法：
    python tools/export_pngmeta_fixture.py                      # 自动挑最新的出图
    python tools/export_pngmeta_fixture.py --png <路径.png>
    python tools/export_pngmeta_fixture.py --dir "S:/ComfyUI LX/output/Anima"

输出：tests/fixtures/anima_v4_workflow.json
     （同时落一份 anima_v4_prompt.json —— 出图时 API 执行图，用于"只写惰性键"的校验）

⚠️ 只依赖标准库：系统 Python 常常没有 PIL，而解析 PNG 的 tEXt 块不需要它。
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
OUT_DIR = os.path.join(PLUGIN, "tests", "fixtures")
DEFAULT_DIRS = [
    os.environ.get("AV3_OUTPUT_DIR", ""),
    "S:/ComfyUI LX/output/Anima",
    "S:/ComfyUI LX/output/图片/Anima",
]


def png_text(path):
    """读 PNG 的 tEXt 文本块（未压缩的那种；ComfyUI 只用 tEXt）。"""
    out = {}
    with open(path, "rb") as fh:
        if fh.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("不是 PNG：%s" % path)
        while True:
            head = fh.read(8)
            if len(head) < 8:
                break
            ln, typ = struct.unpack(">I4s", head)
            data = fh.read(ln)
            fh.read(4)                                  # CRC
            if typ == b"tEXt":
                k, v = data.split(b"\x00", 1)
                out[k.decode("latin-1")] = v.decode("utf-8", "replace")
            if typ == b"IEND":
                break
    return out


def newest_png(dirs):
    best, best_t = None, -1
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.lower().endswith(".png"):
                continue
            p = os.path.join(d, name)
            try:
                t = os.path.getmtime(p)
            except OSError:
                continue
            if t > best_t:
                best, best_t = p, t
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default="", help="指定一张出图（默认自动挑最新的）")
    ap.add_argument("--dir", default="", help="在哪个目录里找（默认常见出图目录）")
    ap.add_argument("--check", action="store_true",
                    help="只校验现有夹具与真图是否一致，不写盘")
    args = ap.parse_args()

    dirs = ([args.dir] if args.dir else []) + DEFAULT_DIRS
    png = args.png or newest_png(dirs)
    if not png or not os.path.isfile(png):
        print("[export_pngmeta_fixture] 没找到出图 PNG，请用 --png 指定")
        return 2
    txt = png_text(png)
    wf = txt.get("workflow")
    pr = txt.get("prompt")
    if not wf:
        print("[export_pngmeta_fixture] 这张图里没有 workflow 元数据：%s" % png)
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    wf_obj = json.loads(wf)
    pr_obj = json.loads(pr) if pr else {}
    wf_path = os.path.join(OUT_DIR, "anima_v4_workflow.json")
    pr_path = os.path.join(OUT_DIR, "anima_v4_prompt.json")

    if args.check:
        ok = True
        for path, obj in ((wf_path, wf_obj), (pr_path, pr_obj)):
            if not os.path.exists(path):
                print("  [!!] 缺夹具 %s" % path)
                ok = False
                continue
            same = json.load(open(path, encoding="utf-8")) == obj
            print("  [%s] %s 与真图一致" % ("OK" if same else "!!", os.path.basename(path)))
            ok = ok and same
        print("[export_pngmeta_fixture] %s" % ("通过" if ok else "**不一致**"))
        return 0 if ok else 1

    for path, obj in ((wf_path, wf_obj), (pr_path, pr_obj)):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
            fh.write("\n")
        print("[export_pngmeta_fixture] 写出 %s（%.0f KB）"
              % (path, os.path.getsize(path) / 1024))
    print("  来源：%s" % png)
    print("  节点 %d 个 · 连线 %d 条 · API 节点 %d 个"
          % (len(wf_obj.get("nodes") or []), len(wf_obj.get("links") or []), len(pr_obj)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
