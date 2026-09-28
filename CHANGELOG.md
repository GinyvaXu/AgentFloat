# 更新日志

## [3.2.1] - 2026-09-28（菜单跟手性与设置修复）
### Fixed
- **「扇形区域数量 / 自定义配置无法设置」**（两个真 bug）：
  ① `bindAll` 会把 `__` 虚拟控件（扇区数量 / 扇区映射 / 主 Agent 选择）**刷成空值**（保存后回显为空）；
  ② 扇区映射下标解析错误（`__slot_0` → 空串 → NaN 索引），**槽位映射从未保存成功**。均已修复并验证回显
- **「悬停检测有偏差」**：菜单命中测试改用「全局坐标 − 窗口位置」，不再用 `mapFromGlobal`
  （高分屏下后者可能返回 2 倍偏移坐标——与浮球此前的同类修复一致）
- **「不跟手 / 有延迟」**：浮球悬停检测定时器 **100ms → 16ms**（此前进入/离开最多迟半拍）；
  菜单高亮轮询 **60ms → 20ms**；按住选环期间由浮球直接转发鼠标位置（高亮零延迟跟随）
- **「画面卡顿」**：整环背景（外发光 + 毛玻璃底 + 品牌描边 + 分隔线）预渲染为单张位图，
  每帧只画一次（基准：1.78ms → **0.54ms/帧**，约 3.3 倍）
- 集成测试中依赖关闭动画信号时序的脆弱断言改为显式参考时刻

### Changed
- 环菜单开合弹簧提速（展开约 0.25s 稳定；关闭更干脆）
- 新增慢帧诊断：单帧绘制 >12ms 记一条 debug 日志（便于真机继续定位卡顿）

## [3.2.0] - 2026-09-28（环形菜单：全新交互 + 视觉重做）
### Added
- **按住选环（默认开启）**：长按弹出菜单后**不松手**，滑向目标扇区（磁吸高亮 + 悬停放大 1.06）**松开即执行**；空白处/中心孔松手取消。可在「设置 → 环绕菜单」关闭（关闭后回退为弹出再点击选择）
- **更强渐变发光视觉**：整环毛玻璃改为径向渐变底 + **品牌色环形渐变描边**（#0a84ff → #af52de）+ 外发光（有悬停扇区时更亮）；悬停/按压扇区改为品牌渐变高亮 + 描边发光
- 设置页「环绕菜单」新增三项：按住选环、悬停延迟、长按延迟

### Changed
- **手感默认值调为灵敏档**：悬停展开 400 → **180ms**、长按 500 → **300ms**；冷却窗口 0.6/0.4/0.5 → **0.35/0.25/0.30s**（旧默认值会在升级时自动迁移，自定义值不受影响）
- **扇区内容预渲染**：图标 + 标签 + 悬停光晕一次性渲染为 QPixmap 缓存，动画只做位图位移/透明度插值 → 稳定 60fps；DPI 变化自动重建缓存（跨屏/缩放安全）
- 逐扇区错峰浮现（30ms 级）与磁吸高亮保持；空菜单/关闭动画路径不变

## [3.1.1] - 2026-09-28（设置保存修复）
### Fixed
- **修复「切换选项无法保存」**：普通开关/输入没有任何变更监听 → 不触发置脏 → 保存按钮始终禁用（只改开关时存不了）。改为在 document 上统一委托监听所有 `data-bind` 控件（滑块/数字/文本输入实时置脏并实时预览）
- **修复「保存后报错」**：保存收尾调用 `renderPage()` 未定义为局部函数（只挂在 `window.App` 上）→ 明知保存成功却提示「保存失败：renderPage is not defined」。补回局部函数并让 `App.renderPage` 引用它
- **修复保存竞态（刚改的开关被打回）**：后端 apply 为异步投递（Qt 主线程 150ms 定时 drain），前端 PUT 后立即回读会拿到 apply 前的旧配置；现 `PUT /api/config` 同步等待 apply 完成并返回「应用后」的完整配置
- 修复保存时把虚拟绑定 `__wtimer_en_*` 写成配置垃圾键（现在不会产生垃圾键；喝水计时器开关改为真实路径 `water.timers.N.enabled`）
- **修复「改了存不住」的历史遗留**：`apply_settings` 未合并 `check_updates` / `hide_delay_ms` / `auto_start` 三个顶层键，保存收尾的写盘会把它们覆盖回旧值；现已补齐（`auto_start` 变更会立即创建/移除开机自启快捷方式）
- 修复 `App.resetDir()` / 主题按钮调用 `renderPage()` 同样报错的问题

### Changed
- 设置页滑块/数字/文本输入实时退出脏状态（原仅在保存时统一读取）

## [3.1.0] - 2026-09-28
### Fixed
- **修复「设置无法保存」事故（配置被误判损坏后清空）**：`save_config` 改为**原子写入**（同目录临时文件 + `os.replace`）；读取失败自动重试；解析失败只备份、**绝不覆盖原文件**；进程内读写加锁；Web 设置页改读主进程内存配置（不再每次读文件）——彻底消除「保存与读取并发 → 误判损坏 → 用户配置被重置为默认」链路（9/28 两次真实事故）

### Added
- **OpenCode 全系接入**：
  - `OpenCode CLI`（终端 TUI，默认 `--continue` 续接上次会话；跳过权限参数 `--auto`）
  - `OpenCode Desktop`（新 **`app` 启动器**：无终端窗口直接拉起；可在「设置 → Agent 管理」一键设为主 Agent，主 Agent 用户自主切换）
  - `OpenCode Web`（`opencode serve` 后台服务 + 自动开浏览器）
- **Web Agent 通用化**（`services/webagent.py`）：任意 `launcher=web` 的 Agent 统一「启动 / 状态 / 终止」；终止 = 结束进程树（taskkill /T）+ 按端口兜底清理 + 校验端口已释放（AgentFloat 重启后也能正确停止）
- **浮球右键菜单新增「Web Agent」子菜单**：按运行状态显示「启动 / 终止 / 打开页面」（DeepSeek Harness、OpenCode Web 等）
- Web 设置页 Agent 编辑器支持「桌面应用」启动器（含徽标）

### Changed
- 内置 Agent 预设自动迁移：升级后自动补齐 opencode 三件套（不覆盖用户自定义）
- `resolve_command` 支持 `%VAR%` 环境变量展开（Desktop 路径跨用户可移植）
- 新增测试：配置并发读写回归（旧实现必失败）、opencode 预设、web 规格解析等（全量 169 项）

## [3.0.2] - 2026-09-27（崩溃修复）
### Fixed
- **修复打开设置后崩溃（0xC0000409 / BEX64，故障模块 Qt5Core.dll）**：更新检查线程（QThread）在查询结束的同一瞬间被释放，Qt 触发 qFatal「QThread: Destroyed while thread is still running」→ abort，进程无提示消失、设置页随之中断（表现为「设置无法保存」）。所有 QThread worker（更新检查 / 更新下载 / 本地 AI / 自动翻译 / AI 快报）统一改为「线程真正结束后再释放引用」+ `wait` 兜底
- 崩溃诊断增强：出现该 Qt 致命消息时，自动把全部 Python 线程栈写入 `logs/faulthandler.log`，便于定位残留 worker

### Added
- **并存实例提醒**：启动时检测到旧版 / 调试版 AgentFloat 同时运行（共用 `%APPDATA%/AgentFloat/config.json`，会互相覆盖设置）时，写入警告日志并弹出托盘通知

## [3.0.1] - 2026-09-27（稳定性修复）
### Added
- **浮窗位置自愈**：启动时把保存坐标收敛到最近可见屏幕（整球可见）；`showEvent` 兜底——发现窗口完全离屏时自动收回并记录警告。修复更换显示器 / 修改 DPI 缩放后浮窗「失踪」、扇形菜单无法唤出的问题
- **托盘菜单新增「重置浮窗位置」**：一键把浮窗移回主屏右边缘中部（应急恢复入口）
- **单实例守卫**：重复启动不再产生双浮窗 / 双托盘 / 热键注册冲突；第二实例会请求既有浮窗显示后退出（命名互斥体 + 自定义窗口消息，不依赖已裁剪的 QtNetwork）
- **崩溃诊断强化**：`faulthandler` 记录原生崩溃堆栈；启动时检测「上一次会话未正常结束」并写入警告日志（会话报告此前从不记录退出状态）

### Fixed
- 修复 `snap_edge` 为空串等非法值时浮窗被错误「贴底隐藏」到屏幕外（现场配置 `window_x=2317` 超出缩放后屏幕 1707）的问题；新增 `ui/placement.py` 纯逻辑收敛（越界坐标 / 非法边值 / 多屏就近），含 11 项单测
- 修复正常退出不落盘：`sys.exit(app.exec_())` 抛出的 SystemExit 绕过收尾流程，导致会话报告从未记录退出状态、错误汇总报告从未导出；打包版退出改走显式 `os._exit`，规避退出期仍有 QThread 运行时被析构触发的 qFatal 崩溃（`0xC0000409`，旧版反复出现的崩溃签名）
- 修复非 ASCII（中文）项目路径下 PyQt5/Qt 插件路径解析失效导致 `QApplication` 创建卡死 / 构建失败：开发与测试启动时自动补 Qt 插件搜索路径，构建脚本提前给出明确提示

### Changed
- `build_exe.py` / `build_debug.py`：非 ASCII 路径下快速失败并给出 ASCII 目录联接建议（PyInstaller Qt 钩子无法解析乱码路径）
- `tests/conftest.py`：无头 Qt 测试自动补插件路径（中文路径下免手工设环境变量）

## [3.0.0] - 2026-09-26（Beta 预发布 · 跨设备验证）
### Added
- **测试体系（P3）**：`tests/` 共 146 项（config / registry / API 监控 / Skills / 快讯 / 更新 / 喝水 / 环菜单几何 / WebBridge / 适配层 / FastAPI 路由 / 日志 / 本地 AI / 杂项 + 浮球交互集成），纯逻辑模块覆盖 75-100%；`pyproject.toml` 增加覆盖率配置
- **构建冒烟脚本** `smoke_test.py`：隔离 APPDATA 运行产物，校验进程存活 + 日志无 ERROR，并输出启动耗时
- **Web 前端 ES 模块化**：`web/js/util.js`（DOM/转义/路径/Toast）+ `web/js/install.js`（Agent 安装页独立状态）；`app.js` 改为 ES 模块入口；真机浏览器验证 4 个页面 0 console 错误

### Changed
- **打包形态升级**：默认 onedir（启动更快，`--onefile` 可选）；onedir 安全裁剪未使用组件（conda Qt 附带 Pdf/Quick/Qml/DBus/Network/Svg 等库、Qt 翻译与冗余平台插件）+ 排除 sqlite3 / cryptography / setuptools，共 **-24.6MB**
- **实测对比**：onefile 153.5MB / 启动 4.3s → onedir 141.9MB / 启动 **1.8s**（启动耗时减半）
- Inno Setup 适配 onedir（ISPP 条件打包，兼容 onefile）；旧版归档支持目录产物
- **安装页性能**：Agent 探测并行化（4 个 CLI 版本查询并发）+ 5 秒 TTL 缓存 + 前端防重叠轮询；页面请求 8.4s → **12ms**（缓存命中），安装/卸载动作触发缓存失效
- 文档同步：README（构建/测试/路线图）、TECHSTACK（打包/测试/前端行）、VERSIONING（版本历史/目录结构/发布流程）

> 说明：P1–P3 为一次完整重构的三个阶段（见 `docs/v3重构方案.md`）；2.3.0 / 2.4.0 为中间阶段版本。
> 本版以 **Beta 预发布**（GitHub Pre-release，tag `v3.0.0-beta`）上架，供跨设备验证；稳定后转正式版。

## [2.4.0] - 2026-09-26
### Added
- **P2 交互内核重写**：新增浮球交互状态机 `ui/interaction.py`（纯逻辑可单测），统一裁决单击/悬停/长按/拖拽/贴边五路输入：
  - 拖拽中长按无效（修复「拖拽误弹菜单」）
  - 贴边唤出后 600ms / 拖拽结束 400ms / 菜单关闭 500ms 内不启动悬停展开（修复「贴边唤出别扭/悬停误弹」）
  - 长按后释放不再触发启动；菜单打开时按压不重复启动
- **弹簧动效引擎** `ui/motion.py`（对齐 ProjectDock spring.js 手感）：从当前值起步、可打断、速度继承；单定时器驱动全部动效
- **环菜单三件套**：弹簧展开/收拢（扇区错峰浮现）+ 磁吸滞回选中（防边界抖动/误击）+ 按压品牌色微光
- **点按即时反馈**：启动时浮球旁弹出「启动中 · Agent 名」气泡（弹簧入场 / 自动淡出）
- **Web 壳静默预热** `webshell/window.py`：启动后隐藏创建窗口，设置/快报打开秒开；600 秒未使用自动回收内存，用户关闭后 60 秒再次预热
- **浮球重绘（方案 C）**：深色玻璃 + 品牌渐变描边（#0a84ff→#af52de）+ 内部光晕 + 白色旋涡；悬停 1.05 / 按压 0.94 全部弹簧驱动
- 测试：新增交互状态机（13 项）与弹簧引擎（5 项）单测，全量 23 项通过；2 个 offscreen 集成冒烟（交互 18 项 / 环菜单 14 项）

### Changed
- **绘制性能重构**：固定窗口（球径 + 留白）+ 三态位图预渲染 + 位图缩放动画 —— 悬停/按压不再重建掩码与渐变缓存（掉帧根因），窗口尺寸仅随设置变化
- 配置坐标改按「球体坐标」保存/解释（窗口含留白后位置精确不变）
- 贴边唤出检测条 6px → 10px 加宽（更容易命中）
- 退出动画改为弹簧弹性收拢（替代 InCubic 生硬收尾）
- 设计 token 对齐 ProjectDock：强调色统一 `#0a84ff`（亮/暗；亮按 `#0071e3`、暗按 `#409cff`），文字三级与语义色同步；`web/css/style.css` 变量一并更新
- 清理 3 处遗留未用局部变量与未使用的 `IOS_*` 旧 token，pyflakes 基线归零

## [2.3.0] - 2026-09-26
### Changed
- **架构重构（v3 计划 P1/3）**：全库迁入 `src/agentfloat` 包结构（core / ui / services / webshell / app 分层）；根 `agent_float.py` 变为瘦入口，`python agent_float.py` 与打包入口保持兼容
- 主题色板合并为唯一来源 `src/agentfloat/core/theme.py`（原 `agent_float.THEMES` 与 `af_theme.py` 两份重复定义合一）
- 路径解析收敛：配置目录 / 数据目录 / 前端目录统一走 `core.paths`（原 dsh / 本地 AI 服务 / 快讯 / 翻译各自实现一套）
- 构建脚本适配 src 结构（`--paths src` + 新 hiddenimports）；新增 `pyproject.toml`（pytest 配置）与 `requirements-dev.txt`

### Fixed
- 修复开发模式下图标资源路径解析错误（`_resolve_path` 旧实现回退到项目根上一级，导致源码运行永远走降级绘制）
- 修复 `web_server._locate_web_dir` 中的冗余候选路径（不可达的上级目录拼接）

### Removed
- 移除死代码约 3,330 行：`SettingsDialog`（2,040 行，v2.1 迁 Web 设置后无任何实例化）、`api_monitor_settings.py`、`agent_manager.py`、`news_panel.py` 及 26 个死导入

> 说明：P1 目标为「行为零变化」的结构重构；交互与视觉重写在 v2.4（P2），测试与打包瘦身在 v3.0（P3）。详见 `docs/v3重构方案.md`。

## [2.2.2] - 2026-08-16
### Fixed
- 修复新电脑首次启动 DeepSeek Harness 报「启动超时或已退出」（日志 `ERR_MODULE_NOT_FOUND` / `plugin tree failed to load`）：dsh 0.1.0-rc 在 Windows 首次运行需要为 `~/.dsh/profiles` 建立插件链接（healProfilesModuleFallback），部分环境（npm 全局安装 + 首次初始化）链接未生成导致 100+ 插件解析失败。AgentFloat 现在自动检测该错误 → 调用 dsh 的 healProfiles 重建 `$DSH_HOME/profiles/node_modules` 链接 → 自动重启 dsh；仍失败才弹窗并给出日志路径

## [2.2.1] - 2026-08-16
### Fixed
- 修复 Web 壳打开时加载指示器「一直转」：`web_ui.open_window` 中 `_ready_evt` 未声明为全局变量（局部变量遮蔽模块级），导致 `is_ready()` 恒 False、`has_pending()` 在窗口子进程存活期间恒 True，加载条（旋转环 + 线性条）永不退出。修复后 Web 壳就绪即切换为成功提示，约 1 秒自动关闭
- 修复加载指示器线性进度条蓝色块超出条外：块位置计算 `x0 = bar.left() + (offset - seg)` 在 offset 小于块宽时块左缘越过条左界。改为在条内循环滚动（`offset % 100 / 100 * (bar.width() - seg)`），整块始终位于条内

### Added
- 新增启动窗口动画（StartupSplash）：程序每次启动时屏幕居中显示毛玻璃启动卡片（品牌蓝旋转环 + 「AgentFloat」+ 启动状态文案 + 底部进度条），主窗口就绪后切换为绿色对勾「启动完成，已就绪」，约 1 秒后淡出关闭，向用户明确告知程序已启动

## [2.2.0] - 2026-08-16
### Added
- 新增「Agent 安装」模块（Web 设置侧边栏独立页面）：Claude Code / Codex CLI / Pi Coding Agent / DeepSeek Harness 一键安装、升级、卸载。基于 npm 全局安装（`@anthropic-ai/claude-code` / `@openai/codex` / `@earendil-works/pi-coding-agent` / `@deepseek-ai/dsh`），国内镜像（registry.npmmirror.com）优先、失败自动回退官方源；页面实时显示安装状态（已装/未装/处理中）、版本号与完整日志，支持展开查看

## [2.1.1] - 2026-08-16
### Fixed
- 修复 Web 套壳设置页 / API 用量 / AI 快报打不开（浏览器报 127.0.0.1 拒绝访问）：根因是 uvicorn 0.52 在 PyInstaller 冻结环境下启动时执行 `logging.config.dictConfig` 配置自身 formatter 抛 `ValueError: Unable to configure formatter 'default'`，Web 后端线程启动即崩溃且异常被 windowed 模式静默吞掉。修复：`web_server._run_server` 改为 `uvicorn.run(..., log_config=None)` 禁用 uvicorn 日志自配置，并给 uvicorn 启动包 try/except，异常完整写入 AgentFloat 日志；`start_server_thread` 增加 6 秒端口就绪探测，返回 (thread, port, ok)，主程序据此真实记录启动成功/失败，不再误报「已启动」
- 修复冻结 exe 启动时 PyInstaller `pyi_rth__tkinter` 钩子崩溃（`Tk data directory "_tk_data" not found`）：构建脚本（build_exe.py / build_debug.py）EXCLUDES 追加 `tkinter` / `_tkinter` / `Tkinter` / `tcl` / `tk`，AgentFloat 仅用 Qt，不依赖 tkinter
- 修复 Web 设置页 JS 报错 `TypeError: $(...).forEach is not a function`（app.js 用单元素 `$` 调 forEach，应为 `$$`），避免启动模式/主题 radio 冗余绑定报错
- 修复加载提示动画逻辑混乱：`LoadingIndicator` 状态切换时未取消旧的隐藏计时器，可能导致加载中卡片被上一个任务的隐藏计划突然关闭；`_poll_loading` 中 dsh 与 Web 壳两个状态机互相覆盖（dsh 启动中 Web 壳会抢占指示器）。修复后：状态切换统一作废旧隐藏计划；dsh 启动期间 Web 壳不接管；启动成功显示绿色对勾，约 1 秒后自动关闭（原 2600/1800ms），失败保持 7 秒

## [2.1.0] - 2026-08-15
### Added
- 新增 DeepSeek Harness（dsh）启动兼容：统一 Agent 框架支持 Claude Code / Codex CLI / Pi / DeepSeek Harness；dsh 以 Web UI 模式启动（后台 `dsh web` / `npx @deepseek-ai/dsh web`，就绪后自动打开浏览器，端口占用自动复用，日志落盘 `logs/dsh_*.log`）
- 设置 / API 用量 / AI 快报 全面迁移为 Web 套壳（FastAPI + pywebview + 原生 HTML/CSS/JS，参考 ProjectDock 技术栈）：Apple 风格侧边栏界面、深浅双主题、实时预览、SSE 事件推送、保存后变更摘要
- 新增 `requirements.txt` 运行时依赖清单

### Changed
- 环绕菜单「API 用量」扇区改为打开 Web 用量页（页内一键跳转平台网页）；「AI 快报」扇区与托盘入口打开 Web 快报页
- Agent 内置预设新增 launcher 字段（terminal/web）；旧配置自动迁移补齐
- 构建脚本（debug/release）纳入 `web/` 静态资源与 fastapi/uvicorn/pywebview 依赖收集
- 版本号 1.6.0 → 2.1.0（按用户要求；含 Web 套壳这一架构级变更）

### Fixed
- 修复历史遗留「兼容 Pi 启动」仅在 AgentFloat 落地、ClaudeFloat 分支未同步的问题（以 AgentFloat 为当前主线）
- 修复 Web 设置页主题单选保存失效（radio 绑定误读 value，浅色主题保存后仍为深色）；补 theme 实时切换监听
- 修复 Web 壳窗口无法打开：pywebview 要求 `webview.start()` 在主线程运行，改为由 multiprocessing 子进程承载 Web 壳窗口（子进程主线程跑 pywebview，主进程经 Queue 下发路由/聚焦/关闭命令），冻结环境已加 `freeze_support`，并新增 `--open-web` 调试参数
- 修复点击启动 DeepSeek Harness 后程序未响应：`launch_dsh_web` 原在主线程同步轮询端口最长 120 秒，改为立即返回、后台守护线程轮询就绪后自动开浏览器（超时弹窗同样在后台线程），并增加“启动中”去重防止重复拉起 npx
- 配置防护：`load_config` 检测到损坏的 config.json 时先备份为 `config.json.corrupt_<时间戳>.bak` 再重置，避免并发写入导致自定义设置被静默清空
- 新增动画加载指示器：dsh 启动 / Web 壳打开时在浮窗附近显示毛玻璃进度卡片（旋转加载环 + 无限进度条 + 阶段文案 + 已等待秒数 + 淡入淡出动画；成功绿勾 / 失败红叉自动淡出）；`dsh_launcher` 增加启动状态机供 UI 轮询，`web_ui` 增加窗口就绪事件

## [0.1.0] - 2026-08-12
### Added
- 项目初始化（由 ProjectDock 预设生成）