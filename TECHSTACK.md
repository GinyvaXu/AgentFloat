# 技术栈 — AgentFloat

## 概览
| 维度 | 内容 |
|------|------|
| 语言/运行时 | Python 3.10+（Windows 10/11） |
| 主要框架 | PyQt5（浮窗本体/自绘面板）+ ctypes（系统集成） |
| 代码结构 | `src/agentfloat` 包分层（core / ui / services / webshell / app），根 `agent_float.py` 为兼容入口 |
| Web 套壳 | FastAPI + uvicorn + pywebview（WebView2）+ 原生 HTML/CSS/JS |
| 数据存储 | JSON 配置（%APPDATA%/AgentFloat/config.json）+ 剪贴板历史 JSON |
| 前端 | 设置 / API 用量 / AI 快报 为 Web 页面（原生 HTML/CSS + ES Module）；浮窗/环绕菜单/Skills/喝水助手仍为 Qt 自绘 |
| 构建与打包 | PyInstaller onedir（主推，`--onefile` 可选）+ onedir 安全裁剪 + Inno Setup（安装包） |
| 测试 | pytest 146 项（覆盖率 43%，纯逻辑模块 75-100%）+ pyflakes 零告警 + `smoke_test.py` 构建冒烟 |

## 核心功能实现

### 浮球与环形菜单（P2 交互/视觉重写）
- **实现逻辑**：深色玻璃浮球（品牌渐变描边 #0a84ff→#af52de + 内部光晕 + 白色旋涡，方案 C）；单击启动 / 悬停 / 长按双通道唤出环菜单；四类冷却窗口根治历史误触（拖拽中长按无效、贴边唤出后 600ms / 拖拽结束 400ms / 菜单关闭 500ms 抑制悬停展开）。
- **技术手段**：交互状态机 `ui/interaction.py`（纯逻辑可单测）+ 弹簧动效引擎 `ui/motion.py`（可打断/速度继承）；固定窗口 + idle/hover 三态位图预渲染（悬停/按压不再重建掩码与缓存）；环菜单磁吸选中 / 弹性展开 / 按压品牌色微光。

### 通用多 Agent 启动器（含 DeepSeek Harness）
- **实现逻辑**：单击启动主 Agent（Claude Code / Codex CLI / Pi / DeepSeek Harness / 自定义命令），右键或托盘快速切换；进程状态指示灯实时反馈；支持普通/跳过权限模式与 Windows Terminal。
- **技术手段**：`agent_registry` 统一注册表（含 `launcher: terminal|web` 字段）；DeepSeek Harness（dsh）走 `dsh_launcher` Web 启动器：后台静默 `dsh web` / `npx --yes @deepseek-ai/dsh web`，轮询端口就绪后自动打开浏览器，日志写入 `logs/dsh_*.log`，端口占用自动复用、可一键停止。

### Web 套壳（设置 / API 用量 / AI 快报）
- **实现逻辑**：FastAPI 后端（uvicorn 守护线程）+ pywebview（WebView2）桌面窗承载 Apple 风格 SPA；设置保存通过线程安全事件桥投递到 Qt 主线程应用（`apply_settings`），SSE 推送快报生成/API 更新/主题切换等实时事件；PyInstaller 冻结模式下自动定位 `_MEIPASS/web`。
- **技术手段**：`webshell/server.py`（FastAPI + StaticFiles + SSE）、`webshell/bridge.py`（双队列 + 状态快照）、`webshell/window.py`（pywebview 子进程 + 静默预热：隐藏创建 → 设置/快报秒开，空闲 600s 回收、关闭后 60s 再预热）、`web/`（原生 HTML/CSS + ES Module，深浅主题 CSS 变量 + 毛玻璃）。

### Skills 辅助窗与本地 AI 自检服务
- **实现逻辑**：扫描本机已安装 skills，分类树浏览 + 中英对照 + 指令一键复制；本地 AI 服务以非交互模式调用主 Agent 校验 API 配置、补齐缺失的 skills 翻译（自动部署翻译 skill，新 skill 触发受限补译）。
- **技术手段**：`skills_scanner` 递归扫描 + 分类；`local_ai_service` 非交互调用 Agent 输出结构化 JSON，文件写入由本模块校验后完成（安全隔离）。

### API 用量监控
- **实现逻辑**：通用 JSONPath 框架轮询任意 API 用量端点，浮窗角标实时显示余额，低余额变色警告；Web 用量页支持端点增删改、即时测试、模板变量说明与平台网页一键跳转。
- **技术手段**：`api_fetcher`（urllib + ssl）+ `api_monitor_config` JSONPath 提取；QThread 轮询 + 信号回传，结果快照经事件桥同步到 Web 页。

### 多功能面板（快报/剪贴板/命令/喝水）
- **实现逻辑**：AI 快报多源聚合（HN/GitHub Trending/少数派/量子位/arXiv）+ 本地 Agent 摘要 + Web 阅读页（分类彩色标注、关注主题加权、历史记录）；剪贴板历史自动记录；命令面板管理常用命令；喝水/久坐/护眼三循环计时提醒（全屏遮罩/弹窗/托盘，支持游戏进程豁免）。
- **技术手段**：`news_fetcher/news_worker`（QThread 拉取 + 缓存）；Web 端通过 `/api/news/*` 与 SSE 联动生成进度；计时器 QTimer 驱动，豁免进程独立模块管理。

### 自动更新与日志体系
- **实现逻辑**：启动检查 GitHub Releases，新版本下载安装包并执行；Debug 版每次运行生成「版本+时间戳+崩溃类型」日志与崩溃报告，关闭时统一导出。
- **技术手段**：`updater`（urllib + hashlib 校验 + QThread 下载）；RotatingFileHandler + 异常钩子导出；全局热键 Ctrl+Alt+C。