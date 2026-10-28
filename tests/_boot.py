# -*- coding: utf-8 -*-
"""测试专用的插件加载器。

为什么不能直接 `import Comfyui-Anima-Wardrobe-V4.anima_v4_rules`：
  ① 目录名带 `-`，不是合法标识符；
  ② 直接跑 `__init__.py` 会一路 import 到 ComfyUI 的 server / aiohttp，
     裸 Python 环境里必然 ImportError —— 我们要测的是规则层，不是节点注册。

做法：手工造一个「只有 __path__ 的空包」塞进 sys.modules，
     再 import_module 子模块。相对导入 `from . import anima_v4_nsfw`
     靠 __path__ 就能解析，全程不碰 __init__.py。
"""
import importlib
import os
import sys
import types

PKG = "Comfyui-Anima-Wardrobe-V4"
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)


def _ensure_pkg():
    if PKG in sys.modules:
        return sys.modules[PKG]
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [PLUGIN_DIR]
    pkg.__package__ = PKG
    sys.modules[PKG] = pkg
    return pkg


def load(name: str):
    """加载插件里的某个模块，例如 load("anima_v4_rules")。"""
    _ensure_pkg()
    full = f"{PKG}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    return importlib.import_module(full)
