# 版本管理规范 — AgentFloat

## 版本号制度
采用 **语义化版本号 (Semantic Versioning)**：
```
v<MAJOR>.<MINOR>.<PATCH>

MAJOR — 重大架构变更或不兼容的 API 改动
MINOR — 新功能、优化（向后兼容）
PATCH — Bug 修复、安全补丁
```

### 版本历史

| 版本 | 说明 |
|------|------|
| v1.0.7 | 修复悬停菜单消失/动画抽搐；点击菜单外立即关闭 + spring 入场；翻译 skill 自动部署 + 新装 skill 自动触发翻译；辅助窗标题栏毛玻璃/关闭按钮 B/分类树美化与动画 |
| v1.0.6 | 环绕菜单整环重绘（统一配色/修复扇区重叠/2秒宽限关闭）；Skills 分类树 + 可见关闭按钮；余额角标常显；移除 AI 自动首启 |
| v1.0.5 | 本地 AI 服务（API 余额配置 + Skills 翻译）+ 悬停菜单/辅助窗/触发指令修复 |
| v1.0.4 | 修复环绕菜单弹不出；Skills 中英对照 + 去除 AI 优化 |
| v1.0.3 | 修复环绕菜单绘制崩溃（QPointF 解包） |
| v1.0.2 | 错误日志改为关闭程序时统一导出汇总报告 |
| v1.0.1 | 修复悬停动画失效；新增报错日志导出 |
| v1.0.0 | AgentFloat 首个版本：通用多 Agent 启动 + 环绕菜单 + Skills 辅助窗 |

---

## 目录结构

```
AgentFloat/
├── agent_float.py              # 主程序（浮窗 + 设置 + 托盘）
├── agent_registry.py           # 多 Agent 注册表与启动模型
├── radial_menu.py              # 悬停/长按环绕菜单（QPainter 自绘）
├── skills_scanner.py           # Skills 扫描器（SKILL.md 解析）
├── skills_panel.py             # Skills 辅助窗（无边框 + 中英对照 + 触发指令复制）
├── local_ai_service.py         # 本地 AI 服务（API 配置 / Skills 翻译）
├── agent_manager.py            # Agent 管理 / Skills 设置对话框
├── af_theme.py                 # 共享主题配色
├── api_fetcher.py              # API HTTP 请求 + 模板变量
├── api_monitor_config.py       # 配置解析 + JSONPath
├── api_monitor_worker.py       # QThread 轮询
├── api_balance_badge.py        # 余额角标浮窗
├── api_monitor_settings.py     # 设置对话框 API Tab
├── config.example.json         # 配置模板（本地 config.json 不入库）
├── VERSION                     # 纯文本版号文件
├── VERSIONING.md               # 本文件（版本管理规范）
├── README.md                   # 项目说明
├── build_exe.py                # 正式版构建
├── build_debug.py              # 调试版构建
├── build_setup_exe.py          # 安装包构建
├── build_utils.py              # 构建辅助（归档/版本）
├── AgentFloat.spec             # PyInstaller spec
├── .gitignore
├── versions/                   # 历史版本归档（本地保留，不入库）
│   └── v1.0.0/
│       ├── src/                # 源代码快照
│       ├── installer/          # 安装器源码快照
│       ├── dist/               # ★ 构建产物
│       └── CHANGELOG.md
├── installer/                  # 安装器源代码（当前工作副本）
├── dist/                       # 构建产物（当前工作副本）
├── build/                      # PyInstaller 临时文件
└── assets/                     # 图标等静态资源
```

---

## 发布流程

### 1. 开发阶段
- 每次构建 debug 版：`python build_debug.py` → `dist/AgentFloat_debug.exe`
- 构建前 `build_utils` 自动把被覆盖的旧版 exe 归档到 `versions/v<旧版本>/dist/`
- 版本号维护在 `VERSION` 文件与 `agent_float.py` 的 `VERSION` 常量

### 2. 版本升级（新功能 / 修复）
```
1. 更新 VERSION 文件 + agent_float.py 中 VERSION 常量
2. 运行 build_debug.py 构建调试版（自动归档旧版）
3. 启动验证 + 生成会话/崩溃报告
4. 确认稳定后：python build_exe.py（正式版）+ python build_setup_exe.py（安装包）
5. 将 exe 同步到 dist/ 与 versions/v<version>/dist/
6. 编写 versions/v<version>/CHANGELOG.md
7. 更新 VERSIONING.md「当前版本」
```

### 3. 发布后
- 打 Git tag: `git tag v<version>`
- 确认 `versions/v<version>/dist/` 包含 `AgentFloat.exe` 与 `AgentFloat_Setup.exe`

---

## CHANGELOG 格式

```markdown
# v1.0.1 — YYYY-MM-DD

## 安全修复 / Bug 修复 / 新功能 / UX 改进
- 具体变更描述
- **根因**：问题根因分析
- **修复**：解决方案说明

## 文件变更
| 文件 | 变更 |
|------|------|
| `agent_float.py` | 具体改动 |
| `VERSION` | x.y.z-1 → x.y.z |

## 构建产物
- `AgentFloat.exe` — 正式版
- `AgentFloat_debug.exe` — 调试版（含会话/崩溃报告）
- `AgentFloat_Setup.exe` — 安装包
```

---

## 归档规则

| 规则 | 说明 |
|------|------|
| 每次发布时必须归档 | 包含源文件、安装包、更新日志 |
| 归档内容 | `src/`（所有 `.py` `.json` `.iss` `.spec`）、`installer/`、`dist/`、`CHANGELOG.md` |
| 归档不包括 | `build/`、`__pycache__/`、`*.pyc` |
| 构建产物 | **必须**归档到 `versions/v<version>/dist/` |
| 命名规范 | 目录名严格使用 `v<MAJOR>.<MINOR>.<PATCH>` 格式 |

---

## 当前版本

**v1.0.7** — 2026-08-08

- 修复悬停菜单消失（悬停离开不再强行关闭）与动画抽搐（防重入）；点击菜单外立即关闭 + OutBack 轻微过冲入场 + 淡出收尾
- 翻译 skill 自动部署；新装 skill 自动触发翻译（首次跑基线，可在设置中关闭）
- 辅助窗：毛玻璃标题栏 + 精致关闭按钮 B + 分类树美化与展开动画

见 `versions/v1.0.7/CHANGELOG.md`。
