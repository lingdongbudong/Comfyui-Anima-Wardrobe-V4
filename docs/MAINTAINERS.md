# 维护者指南（改代码前必读）

> 面向想给本插件提交 PR 或自行改数据的开发者。使用说明看根目录 README.md。

## 目录结构

```
├── __init__.py              # 节点注册 + HTTP 路由入口（版本号在这里）
├── nodes.py                 # 4 个节点的定义与 INPUT_TYPES
├── anima_v4_rules.py        # 核心规则：候选池收敛 / 档位闸门 / 互斥 / 权重
├── anima_v4_nsfw.py         # NSFW 判定表（与 AnimaNSFWGrader 逐字切片对拍）
├── anima_v4_link.py         # 字段联动 / 上肢单槽 / 派生种子
├── anima_v4_outfit_style.py # 服装风格系统（STYLES / STYLE_COMPAT / STYLE_OF）
├── anima_v4_store.py        # 持久化：权重表 / 收藏 / 用户角色覆盖层
├── anima_v4_overrides.py    # 显式覆盖逻辑
├── anima_v4_pngmeta.py      # PNG 元数据读写（双键 anima_v4_prompt / anima_v3_prompt）
├── js/anima_wardrobe_v4_studio.js   # 前端面板（随机面板 / 角色选择器 / 场景库）
├── locales/{zh,en}/         # 节点显示名中文化（en 也放中文，界面恒中文）
├── presets/                 # 数据池：角色库 / 场景库 / 词池 / 档位 / 发型 / 特征
│   └── thumbs/              # 角色缩略图（萌娘百科/wiki 抓取，版权归原权利人）
├── tools/                   # 数据构建脚本（词库真源 → JSON 的生成链）
├── tests/                   # 22 项测试 + UI 冒烟 + 夹具
└── workflows/               # 4 个示例工作流（已内嵌本插件节点）
```

## 铁律（每条都踩过坑）

1. **零漂移**：关闭的控件/选项一次 rng 都不能消耗。改随机逻辑前先跑
   `tests/run_all.py`（22 项）确认基线全绿，改完必须仍然全绿。
   ⚠️ 新增随机字段必然重排 rng —— 固定 seed 的基线会全漂，属预期，
   需同步重建夹具（`tools/dump_ui_fixtures.py`）。
2. **数据文件是派生产物**：`presets/anima_v4_*.json` 里的派生字段由
   `tools/build_*.py` 生成，**人只写人写的内容**（zh/desc/tags/extra 等源字段），
   改完跑构建脚本，不要手改派生字段。
3. **改盘前备份，备份名精确到毫秒**：`xxx.json.bak-before-<主题>-YYYYMMDD-HHMMSS-mmm`。
4. **词库/场景/角色/发型/特征 JSON 会进内存缓存** —— 改盘必须重启 ComfyUI 才生效。
5. **`nodes.py` 是 CRLF 换行**：批量替换脚本里写 `\n` 匹配串会静默不匹配。
   判据：`nl = "\r\n" if "\r\n" in s else "\n"`。
6. **NSFW 判定表（anima_v4_nsfw.py）与 AnimaNSFWGrader 字节级对齐**：
   动它之前先跑 `tests/check_nsfw_parity.py`，口径漂移 = 事故。
7. **前端控件只许追加不许删除**：控件顺序是 `widgets_values` 的契约，
   删控件 = 老工作流整体错位。退役控件用 `hidden + computeSize=()=>[0,-4]` 隐藏。
8. **改 JS 的 `wget/wset(node, "新控件")` 要同步 `tests/av3_ui_smoke.mjs` 的
   `BACKEND_WIDGETS`**。
9. **`ban_tags` 只能填词库合法选项**（如只有 `cargo pants`/`jeans`/`shorts`，
   没有 `pants`），写错 = 静默失效。
10. **`extra` 禁止自造主体名词**（如 `giver`），CLIP 会拆碎片、姿势崩；
    词库外标签只能进 `extra`，否定句无效要写落点。

## 测试基线

```bash
# 22 项离线测试（不需要 ComfyUI 运行）
python tests/run_all.py

# 单项示例
python tests/check_v3_scenes.py        # 场景库结构 + 档位 + 丝袜专项
python tests/check_nsfw_parity.py      # NSFW 口径对拍
python tests/check_v3_userdata.py      # 用户覆盖层不污染内置库

# UI 冒烟（需要 ComfyUI 跑在 8188，Node.js）
node tests/av3_ui_smoke.mjs
```

`run_all.py` 汇总 22 项；任何一项红了都不允许合入。
`tests/fixtures/` 是测试夹具（词池/场景/角色快照 + 工作流），
改词库后用 `tools/dump_ui_fixtures.py` 重建。

## 数据再生成链

| 想改什么 | 改哪里 | 然后跑 |
|---|---|---|
| 场景库 | `presets/anima_v4_scenes.json`（源字段） | `tools/build_scenes.py` → `tests/check_v3_scenes.py` |
| 角色库 | 联网重建：`tools/build_characters.py`（勿手改内置库；个人编辑走界面，落 `user_characters.json`） | `tests/check_v3_chars.py` |
| 词池 | HTML 真源 → `tools/export_v3_pools.mjs` → `tools/classify_v3_levels.py` | `tests/check_v3_pools.py` |
| 发型 | `tools/derive_char_hair_style.py` | `tests/check_v3_charhair.py` |
| 角色固定特征 | `presets/char_feat.json`（唯一入口，只改 JSON） | `tests/check_v3_charfeat.py` |
| NSFW 表 | 与 AnimaNSFWGrader 同步：`tools/sync_nsfw_tables.py` | `tests/check_nsfw_parity.py` |

## 新增随机字段的四件套

HTML 真源 → `tools/export_v3_pools.mjs` → `tools/classify_v3_levels.py`
→ `tests/check_v3_pools.py` 的 `EXPECT` + `FIELD_SLOT`（服装类字段还要登记 `STYLE_OF`）。
漏一步的表现通常是「面板不显示」或「抽不到」。
