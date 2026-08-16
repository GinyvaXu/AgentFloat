# 更新日志

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