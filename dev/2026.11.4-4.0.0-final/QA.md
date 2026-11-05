# QA · 4.0.0 收尾修复验证

- 日期：2026-11-04
- 执行者：schiz-builder（只改代码/测试，未 build、未装机、未改 VERSION、未 push）
- 环境：Windows / `.venv\Scripts\python`

## 1. 命令与结果（真实输出）

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量 pytest | `.venv\Scripts\python -m pytest -q` | **577 项收集 / 575 passed / 2 failed**（仅 `test_floatball_integration.py::test_interaction_flow`、`::test_move_mode_enter_place_cancel`，与修复前一致的既有失败） |
| 定向回归 | `.venv\Scripts\python -m pytest tests/test_design_tokens.py tests/test_intro_animation.py tests/test_onboarding.py tests/test_quotes.py tests/test_release_channel.py tests/test_llm_api.py tests/test_server_api.py -q` | 全部通过（进度 100%，无 F） |
| pyflakes | `.venv\Scripts\python -m pyflakes src/agentfloat tests` | exit 0，无输出 |
| JS 语法 | `node --check web/js/llm.js`、`node --check web/js/app.js` | exit 0 |
| 忽略规则 | `git check-ignore -v debug_logs\... skills_workshop\... .workbuddy\...` | 三条均命中 `.gitignore:88-90` |
| 构建输入 | `Test-Path mcp_entry.py`、`Test-Path skills\progress-protocol\SKILL.md` | 均 `True` |

## 2. 修复清单

1. **P0 配置覆盖**
   - `src/agentfloat/webshell/server.py::put_config`：`changed_keys` 不含 `llm` 时，用 `handlers.get_config()` 里的现有 `llm` 深拷贝回填，再落盘/应用。
   - `web/js/app.js`：新增 `refreshConfig()`；进入 `settings` / `api` / `llm` 前重新 GET `/api/config`（有未保存修改时跳过，避免丢编辑）；启动 hash 白名单补 `llm`、`guide`。
   - 新增回归测试 `tests/test_llm_api.py::test_put_config_without_llm_key_keeps_providers`：存供应商 → PUT 旧快照（changed_keys=["theme"]）→ 供应商与 Key 仍在；删除后再 PUT 旧快照 → 仍为空。
2. **测试/静态红**
   - `ui/progress_radar.py`：6px → 8px（RADIUS.sm）、9px → 10px（FONT.micro）。
   - `ui/intro_animation.py::_finish`：160ms 淡出增加幂等 `_done` + 200ms `QTimer.singleShot` 兜底；`tests/test_intro_animation.py` 改为等待真实事件循环。
   - `ui/floatball.py::_onboarding_demo_cleanup`：先复位 `is_hovered`/`_hold_progress`，再单独 try 停 `_hold_timer`。
   - `tests/test_quotes.py`：菜单文案跟随为「下一条语录」。
   - pyflakes：`is_beta` 已实际使用，未用导入告警消失。
3. **beta 教程策略**：`maybe_start_onboarding()` 恢复 `not is_beta() and not replay and onboarding_done` 才阻断；`AGENTFLOAT_REPLAY_ONBOARDING=1` 仅作额外强制。
4. **`.gitignore`**：新增 `debug_logs/`、`skills_workshop/`、`.workbuddy/`。
5. **P1 草稿丢失**：`web/js/llm.js` 新增 `confirmDiscardDraft()`；切换卡片 / +添加 / 激活其他供应商前，若 `state.dirty` 先弹统一确认；激活当前供应商保留草稿。
6. **P1 余额刷新错误**：`refreshBalances()` 检查 `load(true)` 后的 `state.error` 与各 provider `balance.ok`，失败时 toast 具体原因（401 / 字段未命中 / 网络）；卡片失败显示错误小字 + `title` 全文；禁用/未刷新状态不计入失败。
7. 构建输入存在性已确认（见第 1 节），未提交、未改动。

## 3. 未验证（不夸大）

- 未跑浏览器冒烟（未起 GUI / 未点击真实页面），前端改动仅 `node --check` + 代码走查。
- 未连真实 DeepSeek / OpenRouter / OpenCode Go，余额 401/字段缺失路径使用服务层既有错误文本核对。
- 未 build、未装机、未拆包核对，未复测深色/窄屏。
- 未提交 4.0 新代码（含 `mcp_entry.py`、`skills/progress-protocol/`）；按指令留给 lead 决定。

## 4. D 线进度 P0/P1 修复（2026-11-04 第二轮 builder）

### 逐条对照（问题 → 修法 → 证据）

| # | 问题 | 修法 | 证据（测试） |
|---|---|---|---|
| P0-1 | 设置页「进度贴边条」开关保存即丢 | `floatball.py::apply_settings` 增加 `progress` 子树深拷贝合并，并即时 `radar.resume()/pause()`；`config.py` 默认值补 `progress.enabled=True` | `test_floatball_integration.py::test_apply_settings_merges_progress_toggle`（enabled=False → 合并 → 落盘快照 → `load_config()` 仍 False） |
| P1-2 | Esc/× 关闭 1.2s 后被 tick 撤销；dismissed 重启后点条出现空面板 | 折叠态也按内容签名判断 `dismissed`；内容变化才清除并重现；`_expand` 先清 dismissed 保证必然 `_rebuild`；头部补 × 并在展开时 `activateWindow/setFocus`；设置页重新开启进度条时 `reset_dismissed()` | `test_progress_radar_ui.py::test_close_button_persists_and_tick_does_not_undo`（含 Esc 与重新开启）、`::test_restored_dismissed_does_not_open_empty_panel` |
| P1-3 | 驾驶舱「重试」追加伪步骤 | `store.py` 新增 `retry` action：按 currentStepId → 首个 failed/running 复用原步骤，复位 running、清 finishedAt/error、重计时；驾驶舱与雷达 `_resume` 改用 retry | `test_progress_store.py::test_retry_reuses_failed_step_without_adding`、`test_progress_cockpit.py::test_cockpit_retry_does_not_add_step` |
| P1-4 | session 级 finishedAt 从不写，「已用」永远在涨 | `done/fail/cancel` 写 `finishedAt`；`step/next/need_input/retry/plan` 清空；`session_elapsed` 对旧终态数据回退 `updatedAt` | `test_progress_store.py::test_terminal_actions_write_session_finished_at`、`test_progress_cockpit.py::test_session_elapsed_uses_store_finished_at`（只走 `store.update`，5 小时后仍 600s）；原 `test_session_elapsed_and_signature` 补 legacy 断言，不再靠手造 finishedAt |
| P1-5 | 复用 session id 再 plan 不重置 createdAt | `plan` 重置 `createdAt/finishedAt/error/question/currentStepId`，固定 id（skill-install）同规则 | `test_progress_store.py::test_plan_resets_session_timestamps` |
| P1-6 | `os.replace` 无重试 → 双进程 PermissionError + CLI traceback | `_atomic_write` 3 次 20/40/60ms 退避 + `shutil.move` 兜底；CLI 捕获 `OSError` 输出 `{"ok": false, "error": "进度写入失败…"}` 并退出 1 | `test_progress_store.py::test_atomic_write_retries_transient_permission_error`、`::test_cli_reports_write_error_readably` |
| P1-7a | L1 5 按钮挤 238px | 动作行改「1 主（继续/重试/中断）+ 驾驶舱 + 更多…」；复制 ID / 聚焦窗口 / 收起进 QMenu | `test_progress_radar_ui.py::test_detail_actions_are_one_primary_one_secondary_plus_more`（断言 3 个按钮、总宽 ≤ 238-20） |
| P1-7b | 4 任务+20 步 688px 出屏且无滚动 | `_fit` 明细步骤高度封顶 160px 且整窗 ≤ 可用高−40；明细区 `QScrollArea` | `test_progress_radar_ui.py::test_panel_height_clamped_and_steps_scroll` |
| P1-7c | 浅色主题白叠白 | 新增 `_overlay()`：dark 白 / light 黑系低透明度；明细块、头部悬停、底部/动作按钮描边全部走它 | `test_progress_radar_ui.py::test_light_theme_uses_black_overlays` |
| P1-8 | 驾驶舱回放每 1.5s 被刷新重建打断 | 新增 `_replaying`；回放时停 `_timer`，`_refresh` 早退；手动刷新/切换任务才强制停回放并恢复刷新；补 `:disabled` / `:focus` 样式 | `test_progress_cockpit.py::test_cockpit_replay_is_not_interrupted_by_refresh` |
| P1-9 | 引导第 5 步右键菜单压住气泡 | 新增 `onboarding.context_menu_pos()`：菜单优先放浮球左侧并夹进屏幕；`floatball._popup_context_menu_demo` 改用该位置 | `test_onboarding.py::test_context_menu_demo_does_not_cover_bubble` |

### 命令与结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 进度/引导定向 | `.venv\Scripts\python -m pytest tests/test_progress_store.py tests/test_progress_cockpit.py tests/test_progress_radar.py tests/test_progress_radar_ui.py tests/test_progress_attention.py tests/test_onboarding.py -q` | 全部通过 |
| 新增开关测试 | `.venv\Scripts\python -m pytest tests/test_floatball_integration.py::test_apply_settings_merges_progress_toggle -q` | 1 passed |
| design token 回归 | `.venv\Scripts\python -m pytest tests/test_design_tokens.py -q` | 通过（首轮自测发现 3px/6px 圆角越档，已改 4px/8px） |
| 全量 pytest | `.venv\Scripts\python -m pytest -o addopts="" -q` | **590 passed / 2 failed**；失败仍仅为既有 `test_interaction_flow`、`test_move_mode_enter_place_cancel` |
| pyflakes | `.venv\Scripts\python -m pyflakes src/agentfloat tests` | exit 0，无输出 |
| JS 语法 | 未跑 | 本轮未改任何 `.js`（无 `node --check` 对象） |

### 未验证（不夸大）

- 全部 UI 结论来自 offscreen 断言，未起真实 GUI / 未截图；浅色主题实际像素、125%/150% DPI 未复测。
- Esc 可达性依赖 `_expand()` 的 `activateWindow()`；真实窗口管理器下是否抢焦点未实测。
- 双进程写同一 session 只模拟了 `os.replace` 瞬时 PermissionError；未真起两个进程并发压测。
- 未 build、未装机、未改 VERSION、未 push。

