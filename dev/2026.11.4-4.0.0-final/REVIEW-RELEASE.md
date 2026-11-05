# REVIEW-RELEASE · 4.0.0 发布前只读审查

- 审查时间：2026-11-04
- 审查者：独立只读（未改代码、未 push、未 tag）
- 范围：全量 pytest / pyflakes / node --check、安装包与装机目录、git diff 安全面、发布清单、LLM 回退与翻译回归
- 结论：**BLOCK**（P0 1 项、P1 4 项、P2 3 项）

## 摘要

1. **P0 仍在**：`PUT /api/config` 全量覆盖，设置页保存会把 `llm.providers` 静默回滚（我用 TestClient 独立复现：保存供应商 → PUT 旧快照 → 供应商消失）。4.0 的「删除不复活 / Key 不丢」在真实操作序列下不成立。
2. **测试证据不成立**：全量 `pytest` 为 **576 项 / 8 failed**，不是 BRIEF 允许的「2 个既有 floatball 失败」；多出 6 项（design_tokens×2、intro_animation、onboarding、quotes、release_channel）。
3. `pyflakes src/agentfloat tests` 有 **1 条**（`ui/floatball.py:2751` 导入 `is_beta` 未使用），CHANGELOG 写的「pyflakes/node 检查通过」与事实不符。
4. 其中 3 项失败是真代码问题而非陈旧断言：`progress_radar.py` 用了 6px 圆角与 9px 字号（违反 design token 白名单）；`maybe_start_onboarding` 丢掉 `is_beta()`，测试版「每次打开都当第一次打开」被改成环境变量开关（与 `docs/发布与版本策略.md` 冲突）。
5. 安装包内容齐全：`af-mcp.exe`、`_internal/skills/progress-protocol/SKILL.md`、`_internal/web/js/llm.js`（与仓库同哈希）、`VERSION=4.0.0` 均在；装机目录（`%LOCALAPPDATA%\Programs\AgentFloat`）为同一份 11-2 17:26 构建。
6. 打包产物与源码同步：从 exe 的 PYZ 里解出 `agentfloat.services.llm.has_active_provider`、`news.worker.generate_ai_with_fallback`，说明 P1-3 回退修复确实进了包。
7. 安全：diff 与全部 81 个未跟踪文件里 **没有** `sk-`/`ghp_`/`AKIA`/Bearer 明文；`config.json*` 已进 .gitignore；`_dev_no_token` 有 `_IS_FROZEN` 保护。
8. 但 `debug_logs/*.txt`、`skills_workshop/`（含 `C:\\Users\\zhenl\\...` 个人路径）、`.workbuddy/` 未被忽略，`git add -A` 会入库。
9. 发布状态正确：VERSION/CHANGELOG 均为 4.0.0、`CHANNEL=beta`、无 `v4*` tag、本地领先 origin/main 33 个提交（未 push）。
10. 但 4.0 新代码整片仍是 untracked（含 `mcp_entry.py`、`skills/progress-protocol/`——都是 `build_exe.py` 的构建输入），干净 clone 无法复现本次安装包。

## 已核对通过

- `node --check web/js/*.js` → 5 个文件全部 exit 0。
- 安装包/装机目录：`af-mcp.exe`（9,947,611 B）、`_internal/skills/progress-protocol/SKILL.md`、`_internal/web/js/llm.js`（hash 47FDDF4B…，与 `web/js/llm.js` 一致）、`_internal/VERSION` = 4.0.0。
- `dist/.build_version` = 4.0.0；`versions/v4.0.0/dist/AgentFloat-Setup-4.0.0.exe` 存在（11-2 17:27）。
- LLM 回退 CLI：`news/worker.py:96-125` 在 LLM 无效且有 agent 时切 agent 并 warning；`skills/ai_service.py:556-570` 同逻辑，且 `out is None and agent` 有守卫（无 agent 时走错误分支，不会 `_run_headless(None)`）。对应 5 项测试在全量跑中通过。
- news / skills 翻译用例（`test_news_worker.py`、`test_ai_service_pure.py`）全绿；「API 用量」页本轮无功能性改动（只有与「AI 接入」的重复入口设计问题，见 P2）。

## P0 阻断（must fix）

### P0-1 设置页/API 用量页保存会把 `llm.providers` 静默回滚（REVIEW-UI P0 未修）

- Finding：`web/js/app.js` 的 `cfg` 只在 `init()` 取一次，LLM 页全部走 `/api/llm/*` 且不回写 `cfg`；用户在设置页点保存时 `PUT /api/config` 带的是旧快照，服务端 `put_config` 不做合并直接 `save_config(cfg)`。刚添加的供应商（连同 Key）被抹掉，已删除的供应商连同 Key 复活并可能重新成为 active。
- Evidence：
  - `src/agentfloat/webshell/server.py:220-228`（无合并，直接落盘 + `apply_config`）
  - `web/js/app.js:104-125`（`save()` 只算 `changed_keys`，仍 PUT 整份 `cfg`）、`web/js/app.js:2999-3000`（`cfg` 仅 init 加载）
  - `web/js/llm.js` 全文无 `/api/config`（已 grep，仅 `/api/llm/*`）
  - 本轮独立复现（TestClient + 假 handlers，脚本在 `%TEMP%\af_probe_p0.py`）：
    `POST /api/llm/providers` → disk `['deepseek']` → `PUT /api/config {旧快照, changed_keys:["theme"]}` → disk `[]` → `GET /api/llm/providers` → `[]`
- Why：静默数据丢失（toast 仍报「已保存」），并把 P0-1 的服务端修复原地推翻——用户删掉的付费 Key 会复活并继续计费。这条直接否掉 4.0 验收「删除不复活 / Key 不丢」。
- Fix（建议 a+b 都做）：
  - a) `put_config` 合并：`if "llm" not in (changed_keys or []): cfg["llm"] = handlers.get_config().get("llm")`（`active`/`deleted_ids` 一并保）；
  - b) 进入设置 / API 用量页前重拉 `/api/config`，`/api/llm/*` 写成功后同步 `cfg.llm`；
  - 补测试：`test_put_config_without_llm_key_keeps_providers`（含「删除后再 PUT 旧配置仍为空」）。

## P1 重要

### P1-1 全量测试与静态检查不通过，且 CHANGELOG/QA 声称通过

- Finding：`pytest -q` → **576 tests / 8 failures / 0 skipped**（junit 统计，57s）。BRIEF 允许的是 2 个既有 floatball 失败，实际多出 6 项；`pyflakes src/agentfloat tests` 报 1 条未使用导入。
- Evidence：
  - 新失败：`test_design_tokens.py::test_no_stray_border_radius_values`（`ui/progress_radar.py:448,512` 6px）、`test_no_stray_font_size_values`（`progress_radar.py:144` 9px）、`test_intro_animation.py::test_intro_emits_landed_then_finished`（新增 160ms 淡出后才 emit `finished`）、`test_onboarding.py::test_onboarding_demo_cleanup_is_safe`、`test_quotes.py::test_context_menu_items_unique`（菜单项改名 `换一条语录`→`下一条语录`）、`test_release_channel.py::test_onboarding_replays_on_beta`
  - 既有/允许：`test_floatball_integration.py::test_interaction_flow`、`test_move_mode_enter_place_cancel`
  - `pyflakes`：`src/agentfloat/ui/floatball.py:2751: 'agentfloat.core.version.is_beta' imported but unused`
  - `CHANGELOG.md:10`「146+ 项通过；pyflakes/node 检查通过」
- Why：发布门禁按 BRIEF 是「无新增失败」，现在有 6 项新增；其中 3 项（design_tokens、onboarding 重播、菜单项）是代码真的改了而测试没跟上，说明这批改动没跑过全量回归。CHANGELOG 的通过声明会被带到发布说明里。
- Fix：`progress_radar.py` 改用 `RADIUS.sm/bar`、`FONT.micro`；`intro_animation` 测试改为等待淡出完成（或断言 `_fade_out_anim` 存在）；`test_quotes` 跟随新菜单文案；`maybe_start_onboarding` 恢复 `is_beta()`（见 P1-2）；删掉未用导入。改完重跑全量并把真实数字写进 CHANGELOG。

### P1-2 测试版「每次打开都当第一次打开」被改成环境变量开关

- Finding：`maybe_start_onboarding()` 不再读 `is_beta()`，只有 `AGENTFLOAT_REPLAY_ONBOARDING=1` 才重播；`is_beta` 被导入但未使用。4.0 是 beta 通道，装机版对老用户默认 **不会** 出现新教程。
- Evidence：`src/agentfloat/ui/floatball.py:2745-2759`；`docs/发布与版本策略.md:26`（「测试版每次打开都当第一次打开…`is_beta()` 时…」）；`tests/test_release_channel.py:47-53` 失败；`src/agentfloat/core/version.py:33` `CHANNEL = CHANNEL_BETA`
- Why：这是项目契约里的发布策略，且 4.0 的「首次教程居中 + 弹性动效」在装机版无法验收（用户看不到）。若是有意改成手动开关，应改策略文档与测试，而不是静默漂移。
- Fix：恢复 `if not is_beta() and onboarding_done: return False`（env 变量可作为额外强制开关）；或明确改文档+测试，并在 CHANGELOG 写「教程不再自动重播」。

### P1-3 4.0 代码未入库，构建无法复现

- Finding：`git ls-files --others` 显示 81 个未跟踪文件，包含 4.0 的全部新模块和构建输入：`mcp_entry.py`（`build_exe.py:113` 用它打 af-mcp）、`skills/progress-protocol/SKILL.md`（`build_exe.py:37` 以 `skills` 目录作 datas）、`src/agentfloat/services/llm.py`、`src/agentfloat/services/progress/`、`ui/progress_radar.py`、`web/js/llm.js` 等。
- Evidence：`git status --porcelain`；`build_exe.py:32-37,105-133`；`git ls-files --error-unmatch mcp_entry.py` → 未跟踪
- Why：现在能装机是因为工作区在；一旦换机器/干净 clone，`build_exe.py` 会因缺 `skills/`、`mcp_entry.py` 直接失败，安装包不可复现，也无法做「从源码重建验证」。
- Fix：发布前按用户确认后提交这批新文件（含 `skills/progress-protocol/`、`mcp_entry.py`），再用干净 clone 跑一次 build 校验。

### P1-4 本地运行产物会被 `git add -A` 带进仓库

- Finding：`.gitignore` 只补了 `config.json*`/`launcher_config.json*`。`debug_logs/ai_service_*.txt`（不是 `*.log`，未被忽略）、`skills_workshop/`（backups/trash/index.json，元数据里有 `C:\\Users\\zhenl\\.agents\\skills`）、`.workbuddy/memory/*.md` 都是未跟踪可提交状态。
- Evidence：`git ls-files --others --exclude-standard`；`git check-ignore debug_logs/x.log` 命中但 `debug_logs/ai_service_20261029_183930.txt` 不命中；`skills_workshop/backups/.../.agentfloat-skill.json` 含 `"root": "C:\\\\Users\\\\zhenl\\\\.agents\\\\skills"`
- Why：个人路径/本机运行状态入库属不可回收的信息泄露；`skills_workshop` 里还有第三方 skill 内容（授权与噪声）。
- Fix：`.gitignore` 增 `debug_logs/`、`skills_workshop/`、`.workbuddy/`；`skills/` 是构建输入要保留跟踪，别一起忽略。

## P2 建议

### P2-1 `GET /api/config` 仍返回 `llm.api_key` 明文

- Finding：LLM 页「不回显 Key」只对 `/api/llm/*` 成立；设置页读取的 `/api/config` 含明文 Key，且设置页保存会把整份再 POST 回来。
- Evidence：`src/agentfloat/webshell/server.py:216-218`；`web/js/app.js:2999`
- Why：与 4.0 安全表述冲突；有本地 token + Host/Origin 限制，风险面小。
- Fix：至少写进发布说明与验收范围；后续给 `/api/config` 做 provider 掩码 + 空 Key 保留。

### P2-2 启动动画淡出依赖动画完成才 emit `finished`

- Finding：`_finish()` 改成先跑 160ms `QPropertyAnimation`，在 `anim.finished` 里才 `hide()+finished.emit()+deleteLater()`；异常路径有兜底，但单测/无动画环境会一直等不到 `finished`（当前 test 就是这么挂的）。
- Evidence：`src/agentfloat/ui/intro_animation.py:286-318`；`tests/test_intro_animation.py:134`
- Why：`finished` 是浮球交接触发点；若动画被系统禁用或窗口不可见导致 `finished` 不触发，会出现「启动画面停住」。
- Fix：加一个 160ms 的 `QTimer.singleShot` 兜底（幂等 `_done`），并把测试改成真实事件循环等待。

### P2-3 引导 cleanup 的复位顺序

- Finding：`_onboarding_demo_cleanup` 先 `self._hold_timer.stop()` 再 `self.is_hovered = False`，同一个 try 块里；`_hold_timer` 缺失/异常时悬停态不复位（当前 test 的 stub 就缺它）。
- Evidence：`src/agentfloat/ui/floatball.py` `_onboarding_demo_cleanup`（diff 2585 附近）；`tests/test_onboarding.py:183`
- Fix：先复位 `is_hovered`/`_hold_progress`，再单独 try 停 timer。

## 未验证（不猜）

- 未启动装机版 GUI：进度雷达 L0/L1、启动动画淡出、引导重播在打包环境里的实际表现未跑（只做了文件级核对）。
- 未连真实 DeepSeek / OpenRouter / OpenCode Go；订阅 `percent` 量纲（0-100 还是 0-1）仍未证实。
- 未对 `af-mcp.exe` 做 MCP 握手（未启动 stdio 会话）。
- 未复跑浏览器冒烟（QA 自己已注明）；`state.dirty` 修复的运行期行为仍只有代码走查。
- 「2 个既有 floatball 失败」是否在本次改动前就存在，未用 HEAD 独立跑验证（只按 BRIEF 认定）。

## 结论

**BLOCK**。P0-1 未修（数据丢失 + 付费 Key 复活），另有 6 项新增测试失败、1 条 pyflakes、测试版引导策略漂移、发布代码未入库。修完 P0-1 + P1-1/P1-2 后重跑全量，再重建包并复跑一次冒烟。
