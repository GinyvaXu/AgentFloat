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
| v1.3.0 | 安装/卸载/自动更新链路重构（参考诺丁汉警长桌游项目）：Inno Setup 按用户级安装、支持静默自动更新；多源检查更新（update.json 清单 + jsDelivr CDN + 国内 GitHub 代理 + Releases API）友好错误码；静默重装并重启 + boot 验证；mirror.json 自建镜像。设置「关于」页新增检查更新/下载更新/更新并重启。修复深色模式 API 用量与 AI 快报页白框、浅色模式输入框边框不可见；关于页重建（使用教程/下载链接/个人网站）；修复 AI 快报生成超时崩溃（返回部分结果） |
| v1.2.2 | 效率工具：剪贴板历史（轮询采集/面板复制/单条删除/清空）+ 自定义命令面板（新建/编辑/删除/运行/示例，窗口/终端/后台三种启动方式）；修复吸附隐藏与环绕菜单冲突（打开菜单与按压前自动弹出）；边缘检测条加宽 + 滑动提速，改善点击快捷打开 Agent；快报启动自动生成后自动弹窗（可设置关闭）、面板精简并默认隐藏历史；扇形菜单图标/字体/圆点随扇区数自适应防重叠；移除未读角标；自动更新链路复核（已是最新时不再提示） |
| v1.2.1 | AI 快报体验优化：关注主题定向偏好（预设/权重/彩色标注）、面板毛玻璃标题栏与分类彩色卡片排版、生成加载条；设置「应用/保存/取消」逻辑重构；未读角标美化（渐变红点） |
| v1.2.0 | AI 快报上线：多源聚合（HN/GitHub Trending/少数派/量子位/arXiv）+ 本地 Agent 摘要 + 无边框面板 + 定时/启动补生成 + 未读红点角标 + 托盘通知 |
| v1.1.0 | 环绕菜单扇区模块化（4/6/8 扇区自选功能，Agent/Skills/API/设置/AI 快报预留/退出）；修复灰色覆盖层乱飞根因（arcTo 角度约定错误）；设置页新增扇区数量与槽位动作下拉；AI 快报调研报告 + 精美 README |
| v1.0.9 | 扇形菜单命中/DPI 修复（展开可点击启动、关闭缩放同步）；Skills 手动触发说明完整展示；API 余额一键跳转平台网页；退出全新收拢动画 |
| v1.0.8 | 悬停灰显 + 按压缩放感；拖拽与环绕菜单冲突修复（拖拽冷却 500ms）；设置改为顶部标签页布局；默认启动方式支持自定义程序路径；菜单关闭向中心收拢动画 |
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

**v1.3.0** — 2026-08-09

- 安装 / 卸载 / 自动更新链路重构（参考诺丁汉警长桌游项目）：Inno Setup 按用户级安装（PrivilegesRequired=lowest，静默更新不弹 UAC）+ 卸载自动结束进程；多源检查更新（update.json + jsDelivr CDN + 国内 GitHub 代理 + Releases API）返回友好错误码；静默重装并重启 + boot 标记验证；mirror.json 自建镜像
- 设置「关于」页新增软件更新卡片：检查更新 / 下载更新（带进度条）/ 更新并重启，打开设置自动检查一次
- 修复深色模式 API 用量与 AI 快报设置页白框（白点采样 66.5% → 0%）；浅色模式输入框边框统一为 INPUT_BORDER 可见样式
- 关于页整体重建：应用信息、使用教程、下载链接（GitHub Releases / 项目主页 / 个人网站）、数据路径
- 修复 AI 快报自动生成超时崩溃：fetch_all 超时返回部分结果 + 「超时未完成」错误，不再抛异常

见 `versions/v1.3.0/CHANGELOG.md`。

**v1.2.1** — 2026-08-08

- AI 快报面板与 Skills 辅助窗同款毛玻璃标题栏 + 精致关闭按钮；正文改为分类彩色标签卡片式排版（模型/工具/论文/产品/行业/综合）
- 设置「AI 快报」新增关注主题编辑器：预设（价格调整/新模型发布/优秀 skills 推荐/开源项目/论文突破/行业融资/产品更新/安全事件）+ 自定义名称 + 权重 1~5 + 颜色选择；注入 AI 提示词并按权重排序，纯列表模式按主题权重排序
- 「生成今日快报」增加加载进度条反馈
- 设置对话框「应用/保存/取消」逻辑重构：应用=即时生效并保存、窗口保持打开；保存=生效并保存后关闭；取消=回退到最近一次已应用的主题
- 浮窗未读角标改为精致渐变红点（去掉数字）

见 `versions/v1.2.1/CHANGELOG.md`。

**v1.2.0** — 2026-08-08

- AI 快报：新增 `news_fetcher.py`（可插拔数据源，并发抓取 + 去重 + 分类）、`news_worker.py`（QThread 生成链路，复用本地 Agent headless 调用）、`news_panel.py`（无边框面板，日期列表 + 可点击链接）
- 设置新增「AI 快报」Tab：启用开关、语言（中文/English/中英双语）、定时模式（仅手动/每天定时/启动补生成/两者）、条数上限、AI 摘要开关、摘要 Agent 选择、数据源勾选、通知与角标
- 浮窗左上角未读红点角标（带数字）；生成完成托盘通知；环绕菜单「AI 快报」扇区打开面板
- 数据纯本地：`%APPDATA%/AgentFloat/news/<日期>.json|md`，不上传

见 `versions/v1.2.0/CHANGELOG.md`。

**v1.1.0** — 2026-08-08

- 环绕菜单扇区模块化：设置 → 交互 可自选扇区数量（4/6/8）与每个扇区的功能（启动指定 Agent、Skills 辅助窗、API 余额、设置、AI 快报预留、退出）
- 修复“灰色覆盖层乱飞 / 点不到启动”：`QPainterPath.arcTo` 角度约定与数学角度相差 180°，改用 `_sector_path` 折线采样构造扇区路径，高亮/命中/图标完全一致
- AI 快报功能调研完成：`docs/AI快报与多功能浮窗助手调研报告.md`（生态方案对比 + P0-P2 扩展建议 + 路线图）
- README 全面重写：特性卡片、快捷键表、模块化菜单说明、构建/归档流程、路线图

见 `versions/v1.1.0/CHANGELOG.md`。

**v1.0.9** — 2026-08-08

- 扇形菜单命中测试修复：改用 `mapFromGlobal`（DPI 安全），命中半径与入场/关闭动画缩放严格同步，解决“展开时点不到启动”与“灰色覆盖层乱飞”
- Skills 辅助窗：手动触发 skill 在右侧正文完整展示触发说明，超出自动滚动
- 扇形菜单「API 余额」：点击跳转对应 API 平台网页（已知平台自动匹配，可自定义）
- 扇形菜单「退出」：全新收拢动画（380ms 缩小至 12% + 淡出）后退出

见 `versions/v1.0.9/CHANGELOG.md`。

**v1.0.8** — 2026-08-08

- 环绕菜单交互升级：悬停灰显无蓝色、按下内容缩小约 7% 加深灰色（真按压感），关闭动画向中心收拢 + 淡出
- 拖拽与菜单冲突修复：按住取消悬停展开、拖拽超阈值关闭已开菜单、拖拽结束 500ms 冷却
- 设置界面改为顶部横向标签页：通用 / 外观 / 交互 / Skills / API 用量 / 关于
- 默认启动方式下拉新增「自定义…」：直接选择可执行文件路径作为点击启动目标

见 `versions/v1.0.8/CHANGELOG.md`。

- 修复悬停菜单消失（悬停离开不再强行关闭）与动画抽搐（防重入）；点击菜单外立即关闭 + OutBack 轻微过冲入场 + 淡出收尾
- 翻译 skill 自动部署；新装 skill 自动触发翻译（首次跑基线，可在设置中关闭）
- 辅助窗：毛玻璃标题栏 + 精致关闭按钮 B + 分类树美化与展开动画

见 `versions/v1.0.7/CHANGELOG.md`。
