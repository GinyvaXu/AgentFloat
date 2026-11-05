# HANDOFF · 4.0.0 收尾修复（builder 交付）

- 日期：2026-11-04
- 状态：P0 配置覆盖 + 6 项新增测试失败 + pyflakes + .gitignore + 两个 P1 已修；未 build / 未装机 / 未 push。

## 已完成

- P0：`PUT /api/config` 未声明 `llm` 时保留现有 `llm`（服务端合并）；前端进入设置/API/AI 页前重拉配置，保存后用 PUT 返回的应用结果刷新本地 `cfg`。
- 回归测试：`tests/test_llm_api.py::test_put_config_without_llm_key_keeps_providers`（存供应商→旧快照 PUT→Key 仍在；删除后→仍为空）。
- 测试/静态：design token 圆角/字号、intro 淡出测试、onboarding cleanup 顺序、quotes 菜单文案、release_channel `is_beta()` 全部修复；pyflakes 0；`node --check` 0。
- 测试版教程：`is_beta()` 每次重播恢复，环境变量仅额外强制。
- `.gitignore`：`debug_logs/`、`skills_workshop/`、`.workbuddy/`。
- P1：LLM 页切换/新增/激活前保护未保存草稿（含 Key）；余额刷新失败显示具体原因、toast 不再恒成功。
- 构建输入 `mcp_entry.py`、`skills/progress-protocol/SKILL.md` 均在（未跟踪，未处理）。

## 真实测试数字

- 全量 pytest：577 收集，**575 passed / 2 failed**；失败仅为既有 `test_floatball_integration.py::test_interaction_flow`、`::test_move_mode_enter_place_cancel`。
- pyflakes `src/agentfloat tests`：0 条。
- `node --check web/js/llm.js` / `web/js/app.js`：exit 0。

## 下一步（lead）

1. 浏览器冒烟：LLM 页切换/保存/测试/删除，再进设置页保存，确认供应商与 Key 不被回滚；余额失败路径 toast 文案。
2. 构建 + 每版本地安装（未做），安装包内核对 `web/js/llm.js`。
3. 决定是否提交 4.0 未跟踪代码（含 `mcp_entry.py`、`skills/progress-protocol/`）；提交前 `git add` 复核不被 `debug_logs/`、`skills_workshop/`、`.workbuddy/` 混入。
4. 更新 CHANGELOG 中「146+ 项通过 / pyflakes 通过」为本次真实数字（577/575 passed, 2 known failures）。
5. 复审 P2（hash 已顺手修 `llm`/`guide`；空态文案、币种 OTHER、无障碍等仍未动）。

## 关键路径

- `src/agentfloat/webshell/server.py`（put_config 合并）
- `web/js/app.js`（refreshConfig / goPage / hash 白名单）
- `web/js/llm.js`（草稿确认 / 余额错误）
- `src/agentfloat/ui/{progress_radar,intro_animation,floatball}.py`
- `tests/{test_llm_api,test_intro_animation,test_quotes}.py`

## 2026-11-04 15:30 MCP 注入与本对话联调
- `~/.config/opencode/opencode.json` 已加 `mcp.servers.agentfloat`（备份 .bak-agentfloat）
- `mcp_server.main()` 增加 stdin/stderr UTF-8 reconfigure，修复 `'utf-8' codec can't encode '\udcac'`
- af-mcp.exe 已重建（C:\AIAgentBase\AgentFloat_build\dist\mcpfix\af-mcp.exe）并覆盖安装目录
- 独立 e2e：initialize + progress plan/step/need_input（中文）rc=0，stderr 空
- 任务 `chat-live` = need_input，GUI 已枚举到贴边条窗口 21x59 @ (1232,675)
- 未闭环：当前 Desktop 会话的工具目录在启动时绑定，杀掉旧 af-mcp 后 `tools.agentfloat.progress` 不再可用，需重启 Desktop 一次
- 未重建：安装包仍不含 mcp_server.py 的 stdin 修复（需在下次 build 时包含）

## 2026-11-04 16:00 D 线进度 P0/P1 修复（builder）

- 状态：UX P0 + logic/UX P1（9 条）已修并补测试；未 build / 未装机 / 未改 VERSION / 未 push。

### 本轮改动

- `core/config.py`：默认值补 `progress: {enabled: True}`。
- `ui/floatball.py::apply_settings`：合并 `progress` 子树并即时 `radar.resume()/pause()`（修「开关存不住」）；`_popup_context_menu_demo` 改用 `onboarding.context_menu_pos()`（菜单放左侧，不压气泡）。
- `services/progress/store.py`：`plan` 重置 createdAt/finishedAt/error/question；`done/fail/cancel` 写 session finishedAt；`step/next/need_input/retry` 清 finishedAt；新增 `retry` action（复用原步骤）；`_atomic_write` 3 次退避重试 + `shutil.move` 兜底。
- `services/progress/cli.py`：捕获 `OSError` 输出可读 `{"ok": false}`（exit 1），不再 traceback。
- `ui/progress_radar.py`：折叠态尊重 dismissed（Esc/× 不被 tick 撤销）；`_expand` 清 dismissed 防空面板；新增 `reset_dismissed()`（设置页重新开启进度条时清标记）；头部加 ×；动作行改 1 主 + 驾驶舱 + 更多…；明细区 QScrollArea + 高度 clamp；`_overlay()` 修浅色主题白叠白。
- `ui/floatball.py::apply_settings`：`progress` 变化时同步 `reset_dismissed()/resume()/pause()`。
- `ui/progress_cockpit.py`：`session_elapsed` 终态回退 updatedAt；`_resume` 改 retry；回放期间暂停刷新（`_replaying`）；补 disabled/focus 样式。
- `ui/onboarding.py`：新增 `context_menu_pos()`。
- 测试：`test_progress_store.py`（+5）、`test_progress_cockpit.py`（+3，含修假通过）、`test_progress_radar_ui.py`（新，5 项）、`test_onboarding.py`（+1）、`test_floatball_integration.py`（+1）。

### 真实测试数字

- 全量：`.venv\Scripts\python -m pytest -o addopts="" -q` → **590 passed / 2 failed**；失败仍仅为既有 `test_floatball_integration.py::test_interaction_flow`、`::test_move_mode_enter_place_cancel`。
- pyflakes `src/agentfloat tests`：0 条。
- 未跑 `node --check`（本轮未改 JS）。

### 下一步（lead）

1. 真实 GUI 复核：浅色主题 L1、4 任务+20 步滚动、Esc/× 关闭与重启后行为、驾驶舱回放、引导第 5 步菜单位置。
2. 若接受，构建 + 每版本地安装；CHANGELOG 的测试数字改为 590/588 passed（2 known failures）。
3. 双进程真实并发写入压测（本轮只模拟 PermissionError）。
4. P2（行结构/6 段色块等）按任务要求未动。


## 2026-11-04 16:05 进度显示修复 + 重建安装
- 两轮进度审验：UX=BLOCK（P0 设置开关不持久），LOGIC=PASS WITH NOTES（P1x5），已派 builder 修 P0+P1
- 设计约定纠偏：builder 曾加「×」关闭按钮，已按用户决策移除（无 X/圆点，只保留 — 与设置开关），测试改为断言无 ×
- 全量：592 收集 / 590 通过 / 2 个既有 floatball 失败；pyflakes 0
- 4.0.0 重建并安装：旧包归档 versions/v4.0.0/dist/archive/AgentFloat-Setup-4.0.0-20261104-155345.exe
- 安装版已运行 v4.0.0；af-mcp.exe 15:56 构建（含 stdin UTF-8 修复）；llm.js 哈希一致
- GUI 实测（窗口几何，非截图）：教程 Esc 关闭后贴边条 21x59 @ (1232,675)；点击展开面板 347x211 @ (901,599)
- 局限：本会话屏幕捕获只返回壁纸（会话/桌面限制），无法提供视觉截图证据
- 待办：复审 REVIEW-PROGRESS-RECHECK 结果；MCP 工具需重启 Desktop 才回到本会话；LLM 页面浏览器冒烟仍未做

## 2026-11-04 16:20 复审后收尾
- REVIEW-PROGRESS-RECHECK：PASS WITH NOTES，P0=0，新增 P1 一条（引导结束 resume 忽略 progress.enabled）
- 已修：floatball._on_onboarding_finished 仅在 enabled 时 resume；新增 test_onboarding_finish_respects_progress_disabled
- 全量：593 收集 / 591 通过 / 2 个既有 floatball 失败；pyflakes 0
- 4.0.0 再次重建安装（旧包归档 archive/AgentFloat-Setup-4.0.0-20261104-161436.exe），进程运行中
- 剩余 P2（未修，留到下轮）：驾驶舱浅色白叠白；dismiss 遇 updatedAt 变化即复现；重启后无「重新显示」入口（需去设置开关）；retry 空步骤 0/0；窄屏菜单回落；QA/设置文案漂移；测试耦合色值
- 局限：无截图证据（本会话屏幕捕获仅壁纸）；MCP 工具需重启 Desktop

## 2026-11-05 12:50 用 agent-desktop 实测并重做面板视觉
- 用 agent-desktop（screenshot --screen 0）拿到真实屏幕：面板背景完全透明、▰▱ 糊成小点、行无层级、贴边条像滚动条
- 已重做 progress_radar.py：面板 WA_StyledBackground + 阴影、SegBar 6 段自绘、TaskRow(dot/name/meta/seg/计数)、贴边条 ••• + 数量 + hover 16→20、行高 60、右侧固定 done/total、ETA 归入 meta
- offscreen 渲染证据：evidence/radar-after-dark.png、radar-after-light.png、radar-tab-dark.png
- 全量 pytest 仅 2 个既有 floatball 失败；pyflakes 0
- 已重建并安装 4.0.0（旧包 archive/AgentFloat-Setup-4.0.0-20261105-123753.exe），进程运行中
- 待办：用户退出全屏游戏后做实机截图复核；贴边条目前会浮在全屏游戏上（未做全屏隐藏）

## 2026-11-05 14:05 实机验证通过 + 安装踩坑
- 发现：Inno 虽写了 ignoreversion，但同版本静默安装时若进程未完全退出，文件不会替换 → 12:44 那次安装实际仍是 11-4 15:56 的包（面板还是旧的）
- 处置：结束进程 + 把安装目录改名备份 + 全新安装；确认 AgentFloat.exe 时间戳为当次构建
- 实机验证（agent-desktop screenshot --screen 0 + 裁剪）：
  - 面板不透明、无背景透字；圆点/标题/次要信息/6 段进度/0-3 计数/打开驾驶舱均正常
  - 贴边条为 ••• + 数量 + 顶部琥珀色，hover 变宽
  - 证据：evidence/live-panel-zoom.png、live-panel-zoom2.png
- 透明残留修复：面板底色由 rgba(27,27,31,.97) 改为不透明 #1B1B1F / #FAFAFC（无 backdrop blur 时 0.97 仍会透字）
- 发布注意：安装前必须确认没有 AgentFloat 进程，否则同版本文件不会被替换（建议加进发布检查清单）

## 2026-11-05 14:20 修「点行后面板塌陷」
- 复现：点任务行展开明细后，面板从 327 变成 112，两行内容叠在一起（evidence/bug-zoom.png）
- 根因：`_rebuild` 里刚 addWidget 完就 `_fit`，`_panel.sizeHint()` 还是旧缓存 → 高度按 44 算
- 修复：`_fit` 先 activate 布局；`_rebuild` 末尾再用 `QTimer.singleShot(0, ...)` 量一次真实高度
- 验证：offscreen 复现脚本 collapsed 245 → expanded 369（修复前 84）；实机 244 → 408，明细/步骤/按钮正常（evidence/fix-zoom.png）
- 已重建安装（AgentFloat.exe 14:10），进程运行中

## 2026-11-05 14:40 展开动画 + 不再强制居中
- 问题：展开时窗口按高度重新垂直居中 → 整窗跳动；且高度瞬间变化无过渡
- 改法：
  - `_place()` 非 force 时沿用上次顶边（`_last_pos`），只有首次展开才按浮球居中
  - 新增 `panelHeight` 动画属性（200ms OutCubic），展开/收起用高度动画
  - 新增 `_clip` 裁切容器：面板按最终高度排版，窗口由小变大把内容「揭开」，行不会被压扁，也不会被布局最小高度瞬间撑大
- 实机测量：展开 244→280→359→385→404→407→408，收起 408→343→315→295→280→257→251→247→245；y 全程 583 不变
- 已重建安装（AgentFloat.exe 14:31），进度测试 15 passed，pyflakes 0

## 2026-11-05 21:20 模拟任务实跑体验
- 脚本化跑完整生命周期：plan(6 步) → 3 次 step → need_input → step → done，逐步截图 sim-1..sim-6
- 同时用本会话 MCP 工具 tools.agentfloat.progress 实跑，确认工具可用
- 发现并修：`step` 只把目标步设为 running，旧步不收尾 → 同时多个 running、进度永远 0/N；已改为进入第 N 步时收尾前面步骤，补 test_step_closes_previous_running
- 全量：仅 2 个既有 floatball 失败；pyflakes 0
- 已重建安装（AgentFloat.exe 21:06），测试任务全部 done 清理
- 体验层待决策：①2 分钟门槛导致 40-60s 任务完全不显示 ②面板 10s 自动隐藏 ③陈旧任务计入数量 ④need_input 置顶会让正在看的行跳动 ⑤af-mcp 被杀/升级后本会话工具消失需重启 Desktop

## 2026-11-05 21:47 LLM 页面冒烟 3 项修复
- 深链：app.js 增加 hashchange 监听（#/llm 同文档跳转不再无效）；实测 #/settings→#/llm 正常
- /api/llm/test 失败改回 200 + {ok:false,error}（原 400 会在控制台报红）；实测 status 200、errors 空
- #dirtyHint 增加 aria-hidden 切换；实测 true→false→true
- 源码实例验证后恢复配置、重建安装（AgentFloat.exe 21:46）
- 未验证：窄屏视觉（窗口无法改尺寸）
