# REVIEW RECHECK · D 线进度（4.0.0 修复复验）

- 审验者：schiz-reviewer（只读，未改任何代码；仅新增本文件）
- 日期：2026-11-04；环境：`.venv` + `QT_QPA_PLATFORM=offscreen`；全部用临时 `AGENTFLOAT_PROGRESS_DIR`，未碰真实任务目录
- 复跑：`test_progress_{store,radar,radar_ui,cockpit,attention}.py` → **24 passed**；`test_floatball_integration.py` → **5 passed / 2 failed**（`test_interaction_flow`、`test_move_mode_enter_place_cancel`；后者单独跑通过，全文件顺序下是被前者早退带崩的连带失败）
- 环境噪声：本机对该文件用 `-q` 不加 `-s` 时只打印 `F` 就以 1 退出、拿不到 summary；加 `-s` 正常。原因未查，不影响结论

## 逐条核对（P0/P1）

| 项 | 结论 | 证据 |
|---|---|---|
| 设置页「进度贴边条」开关持久 | 通过 | `floatball.py:2922-2937` 深拷贝 `progress` 子树后再收尾 `save_config`；`config.py:89` 默认 `{enabled: True}`；`web/js/app.js:1473-1474` 设置页开关；`test_apply_settings_merges_progress_toggle` 覆盖 内存 → 落盘 → `load_config()` 回读 |
| 无 ×（无关闭按钮） | 通过 | `progress_radar.py:479-509` 头部只有 标题 / 简略 / —，无 ×；`test_progress_radar_ui.py:73-75` 断言不存在 × 按钮。⚠ QA.md §4 仍写「头部补 ×」，与代码和用户决策不符（文档漂移） |
| Esc / 关闭持久，tick 不撤销 | 通过（同内容） | `_tick:351-365` 折叠态按 sig 判断；`_expand:292-296` 先清 dismissed 再渲染。offscreen 复核：dismiss → tick 仍隐藏；恢复 dismissed 后 `_expand()` body.count()=3 且有内容。残余见 P2-1 |
| 驾驶舱「重试」不新增步骤 | 通过 | `store.py:199-217` retry 按 currentStepId → 首个 failed/running 复位、清 finishedAt/error，不 append；`test_retry_reuses_failed_step_without_adding`、`test_cockpit_retry_does_not_add_step` |
| session finishedAt / 已用停止 | 通过 | `store.py:218-242` done/fail/cancel 写 finishedAt，step/next/retry/plan 清空；`session_elapsed` 对旧终态回退 updatedAt；测试只走 `store.update`，5 小时后仍 600s |
| 同 id 再 plan 重置 createdAt | 通过 | `store.py:162-172` 重置 createdAt/finishedAt/currentStepId；测试用 2020 年时间戳验证 |
| os.replace 重试 + 冲突报错可读 | 通过（模拟） | `store.py:42-72` 3 次 20/40/60ms 退避 + `shutil.move` 兜底；`cli.py:80-84` 捕 OSError → `{ok:false, 进度写入失败}` exit 1；两条测试通过。真实双进程未复测 |
| L1 1 主 + 1 次 + 更多 | 通过 | `_build_l1:620-648`；测试断言 3 按钮且总宽 ≤ WIDTH-20 |
| 面板高度受限 + 滚动 | 通过 | `_detail_steps_h:383-385` 封顶 160 + `QScrollArea:589-607`；`_fit:410-412` clamp 到可用高；测试通过。长 question 仍按 22px 估，会被裁字（不溢出） |
| 浅色主题 overlay | 雷达通过、驾驶舱未修 | `_overlay:448-452` 只用于雷达；`progress_cockpit.py:146,199-204,101` 仍是白色叠白（默认主题 light）→ P2-2 |
| 回放不被 1.5s 刷新打断 | 通过 | `_refresh:229-234` 回放早退；`_stop_replay:286-291` 恢复定时器；`test_cockpit_replay_is_not_interrupted_by_refresh` |
| 引导第 5 步菜单不压气泡 | 通过 | `onboarding.context_menu_pos:113-128` 优先左侧并夹屏；`floatball.py:2622-2633` 改用该位置；`test_context_menu_demo_does_not_cover_bubble` |

## 新发现

### P1-A 关掉开关后，引导结束会把贴边条重新拉起

- Finding：`resume()` 不看 `progress.enabled`；`_on_onboarding_finished` 无条件 `resume()`；当前 `CHANNEL=beta`，每次启动都重播引导。
- Evidence：`progress_radar.py:270-278`、`floatball.py:2709-2713`、`app.py:383-386`、`version.py:33,36-38`、`app.py:795-801`。
- Why：没有 ×，设置开关是唯一关闭入口。关掉后每次启动（beta）引导一结束条子又回来，而设置页仍显示「关」，用户感受依旧是「关不掉」。
- Fix：`_on_onboarding_finished` 里先判断 `(self.config.get("progress") or {}).get("enabled", True)` 再 `resume()`；或让 `ProgressRadar` 自己记住 enabled，`resume()` 仅在 enabled 时启动。
- 状态：代码路径确认（未起真实 GUI），逻辑确定，无需概率复现。

## 剩余 P2

| # | Finding | Evidence | Fix |
|---|---|---|---|
| P2-1 | dismiss 对活跃任务只是暂时：`content_signature` 含 `updatedAt` / 步数，任何一步更新都会让条子重新出现（offscreen 已复现：只改 updatedAt → tab 回来） | `progress_radar.py:115-128,351-361` | 若「关闭」应更持久：sig 去掉 updatedAt，只在 session 集合 / 状态变化时清除 |
| P2-2 | 驾驶舱浅色主题白叠白：按钮描边 .12、hover .08、步骤条底 .08、列表分隔 .06，白底上不可见（UX P1-4 只修了雷达） | `progress_cockpit.py:146,199-204,101` | 与雷达同法按主题取叠加色 |
| P2-3 | 重启后 dismissed 命中同一 sig → 条子保持隐藏而设置开关显示「开」，无「重新显示」按钮，只能关-开一次 | `progress_radar.py:188,354-359`、`floatball.py:2931-2932` | 设置页加「重新显示进度条」，或启动时清 dismissed |
| P2-4 | `retry` 在无 failed/running 步骤（例如仅 need_input 且无步骤）时把 status 置 running 但不设 currentStepId，出现「进行中 0/0」 | `store.py:199-217` | 无可复位步骤时保持原状态或返回 ok:false |
| P2-5 | `context_menu_pos` 左侧放不下时退回右侧，窄屏（可用宽 <≈700）仍会压气泡 | `onboarding.py:122-124` | 左侧不足时改上 / 下方，或该步气泡切 left |
| P2-6 | 文档 / 文案漂移：QA.md §4 仍写「头部补 ×」；设置页开关说明「保存并重启浮窗生效」与实际即时生效不符 | `QA.md:50`、`web/js/app.js:1473` | 改文案；QA 表按「无 ×」更正 |
| P2-7 | 测试耦合实现：断言精确 rgba 字符串、160px 魔数、按钮文案全等，改配色 / 结构即红 | `test_progress_radar_ui.py:134-138,156,168-177` | 断言行为（可点、有滚动、对比度阈值）而非具体色值 |

## 未验证（不夸大）

- 真实 GUI 下 Esc 是否收得到（`WA_ShowWithoutActivating` + `activateWindow` 的实际焦点行为），目前只有 offscreen 代码路径。
- 真实双进程并发写同一 session（只模拟了瞬时 `PermissionError`；读-改-写竞态导致的丢步仍在，重试只是降概率）。
- 125% / 150% DPI 的 16×44 热区、浅色主题实际像素；本机 offscreen `grab()` 不出文字，视觉判断以颜色叠加计算为准。

## 结论

**PASS WITH NOTES** —— P0=0（开关持久、无 ×、dismiss 不再被同内容 tick 撤销均已闭合；测试数字与 QA 一致）。新增 **P1-A 1 条**，建议正式版前修（一行判断），其余 P2 可排后。