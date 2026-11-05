# REVIEW · D 线进度显示（4.0.0）

审查者：schiz-reviewer（只读，未改代码）。环境：`.venv\Scripts\python` + `QT_QPA_PLATFORM=offscreen`，全部实测用临时 `AGENTFLOAT_PROGRESS_DIR`，未碰真实任务目录。

摘要（10 行）
1. 状态机 7 个 action、坏 JSON、ETA、原子写单写者路径全部实测通过；`tests/test_progress_*.py` 11 项全过，全量 pytest 仍只有 2 个既有 floatball 失败（与 QA.md 一致）。
2. 显示门槛 2min / need_input·failed 即时 / running 10min 过期 / blocked·failed 4h 过期 / done 不显示：8 条用例全部符合。
3. 贴边条-面板-渐隐回条主流程正常；**手动关闭（Esc）1.2s 后被撤销**，且 dismissed 记录会命中 `_tick` 的兜底分支，重启后点条出现**空面板**。
4. 驾驶舱打开/列表/步骤耗时/几何记忆正常；**“重试”会给失败任务追加伪步骤**，**已完成任务的“已用”永远在涨**。
5. 同源成立（CLI/MCP/UI 同一份 json）；但两个进程写同一 session 会 `PermissionError` 崩掉一方并丢步。
6. 复用 session id 再 plan 不重置 createdAt → 2 分钟门槛被绕过（`skill-install` 正是固定 id）。
7. 教程暂停/恢复已接上，但 `resume()` 无视 `progress.enabled`，教程结束后会强行拉起雷达。
8. 排序、ETA 文案、注意力路由、回放高亮、面板高度等为 P2，见下。
9. 未验证：真实多屏/多 DPI/窗口枚举、真实 GUI 视觉（全部 offscreen 断言）；`_dismiss` 的 Esc 可触达性依赖窗口被点击激活。
10. 结论：P0=0，P1=5（建议正式版前修 1–3）。

## P0 阻断
无。

## P1 重要

### P1-1 手动关闭不生效，且 dismissed 记录会导致展开空白面板
- Finding：`_dismiss()` 后再来一次 tick，贴边条立刻重新 show；若 `dismissed` 已持久化（重启后从 QSettings 恢复），点条展开时 `_tick` 命中 `_dismiss_sig == sig` 分支 `hide(); return`，**不执行 `_rebuild`**，随后 `_expand` 又 `show()` → 260px 空白框。
- Evidence：`src/agentfloat/ui/progress_radar.py:243-254`（`_dismiss` 只 hide，不参与到折叠态判断）、`:332-335`（折叠态无条件 `_tab.show()`）、`:339-357`（`_dismiss_sig == sig → hide + return`，跳过 `_rebuild`）、`:285-293`（`_expand` 之后照常 show）。
- 实测：dismiss 后 1.3s `_tab.isVisible()==True`；新实例恢复 dismiss sig 后 `_expand()` → `isVisible()==True`、`_body.count()==0`。
- Why：关闭语义自相矛盾——不持久（1.2s 内撤销）却持久化到 QSettings，并以“隐藏 + 跳过渲染”的形式泄漏到展开路径；用户看到的是“关不掉”和“偶尔点开是空框”。
- Fix：折叠态也按内容签名判断 `_dismiss_sig`（sig 变了才重新出现）；`_expand()` 进入时若 `sig == _dismiss_sig` 先 `_dismiss_sig=""` + `QSettings.remove`，保证必然 `_rebuild`；或干脆去掉 dismissed 持久化（无 X，关闭只有 Esc，价值低）。
- 复现：临时 DIR 写一条 running 且 createdAt=3 分钟前的 json → 起 radar → 按 Esc → 等 1.3s 条自己回来；退出重开 → 点条 → 空面板。

### P1-2 驾驶舱“重试”制造伪步骤，与雷达行为不同源
- Finding：失败后没有任何 `status=="running"` 的步骤，`_resume` 取到 `title=""`，`store.update(action="step")` 于是**新增一条“步骤 N”**；原失败步骤永远停在 failed，pending 步骤也未动。
- Evidence：`src/agentfloat/ui/progress_cockpit.py:321-325`（只找 running 步骤）、`:293`（failed 也启用该按钮）；`src/agentfloat/services/progress/store.py:148-160`（`step` 找不到就 append 新步骤）；对照 `src/agentfloat/ui/progress_radar.py:78-83, 612-620` 用的是 `current_step()`（带 currentStepId 回退），所以雷达“重试”是对的。
- 实测：plan[a,b,c] → step a → fail → 驾驶舱 `_resume()` → steps = `a(failed), b(pending), c(pending), 步骤 4(running)`，currentStepId=s4。
- Why：用户点“重试”结果是多出一条无名步骤、失败步骤仍是红叉，进度分母也被改大。
- Fix：`_resume` 复用 `current_step()`（先按 currentStepId，再按首个 failed/running）；更稳妥是后端加 `retry` action：把 failed 步骤复位 running、清 `error`、清 `needsInput`。
- 复现：`af progress plan/step/fail` → 打开驾驶舱 → 点“重试” → 看步骤列表。

### P1-3 已完成/已取消任务的“已用时间”永不停止（session 级 finishedAt 从不写入）
- Finding：`session_elapsed` 读 `data["finishedAt"]`，但 `store` 任何 action 都不写 session 级 `finishedAt`（`done` 只写步骤级），于是已完成任务的“已用”按当前时间持续增长。
- Evidence：`src/agentfloat/services/progress/store.py:172-192`；`src/agentfloat/ui/progress_cockpit.py:60-68`；`tests/test_progress_cockpit.py:26`（测试手工造了 `finishedAt`，覆盖的是生产永不产生的字段 → 假通过）。
- 实测：createdAt 10:00、10:05 done 的任务，15:21 打开驾驶舱显示“已用 5h21m”。
- Fix：`done/fail/cancel` 分支写 `data["finishedAt"]=now_iso()`（`plan` 时清空）；`session_elapsed` 在无 finishedAt 时回退 `updatedAt`；补一条只走 `store.update` 的测试。
- 复现：`plan → step → done`，15 分钟后再打开驾驶舱看“已用”。

### P1-4 复用 session id 再 plan 不重置 createdAt：2 分钟门槛失效 + 时间跨历史
- Finding：`plan` 不重置 `createdAt`（也不清 `finishedAt/error`），`qualifies()` 的门槛又只看 `createdAt`，因此同一 id 的第二次任务一开始就满足“已运行 ≥2 分钟”，立刻整块浮现在屏幕上；驾驶舱的“已用”也带着上次甚至几天前的时长。
- Evidence：`src/agentfloat/services/progress/store.py:126-147`（`data.update` 无 createdAt）、`src/agentfloat/ui/progress_radar.py:54-59`、`src/agentfloat/services/skills/jobs.py:41`（固定 id `skill-install`）。
- 实测：把 `skill-install.json` 的 createdAt 改成 3 天前 → 再 plan+step → `qualifies()` 立即 True。
- Fix：`plan` 里重置 `createdAt=now_iso()`、`finishedAt=""`、`error=""`、`question=""`；或门槛改用“本轮首次 step 的 startedAt”；jobs 侧改用带时间戳的 session id。
- 复现：连续两次 `af progress --session demo plan ...`，间隔 1 秒，看第一次的 createdAt 仍在。

### P1-5 两个进程写同一 session → PermissionError（WinError 5），CLI 直接 traceback 且丢步
- Finding：`_atomic_write` 的 `os.replace` 在目标正被另一写者占用时抛 `PermissionError`，无重试；`cli.main` 只捕获 `ValueError`，于是 CLI 以 traceback 退出 1，文件停留在中间态（丢步）。MCP 侧被 `except Exception` 吞成 error 回复，agent 看到的是“工具报错”。
- Evidence：`src/agentfloat/services/progress/store.py:37-51`、`src/agentfloat/services/progress/cli.py:77-79`、`src/agentfloat/mcp_server.py:57-61`。
- 实测：两进程各 40 次 `step`（同一 session）→ 一方 `PermissionError [WinError 5]`，最终文件 42 步（应为 82）。单写者 + 1.2s 读轮询 6s/80 次写 无失败（读路径不阻塞写，`_atomic_write` 本身设计是对的）。
- Fix：`os.replace` 加 3 次 20–50ms 重试（失败再 `shutil.move`）；CLI 捕获 `OSError` 走 `{"ok": false}` 分支；文档/技能里强调 session id 必须唯一（或默认 session 由 cwd/项目名派生，避免所有 agent 挤在 `default`）。
- 复现：两个终端同时跑上面的 step 循环。

## P2 建议

| # | Finding | Evidence | Fix |
|---|---|---|---|
| P2-1 | `resume()` 无条件重启定时器，无视 `progress.enabled=false`：教程结束会把用户关掉的雷达拉起来 | `progress_radar.py:263-266`、`app.py:385-386`、`floatball.py:2697-2699` | `start()` 记录 enabled，`resume()` 只在 enabled 时启动；或 `pause()` 记原因、`resume()` 复原原状态 |
| P2-2 | `cancel` 不结当前步骤（留着 running），`fail` 不清 `needsInput/question`；驾驶舱因此对已取消任务仍显示“进行中”的步骤条 | `store.py:180-192` | 两分支都收尾当前步骤；`fail` 置 `needsInput=False` |
| P2-3 | ETA 文案下限与数值矛盾：剩 20s 显示“~1–2m” | `store.py:69-70` | `low/high` 下限改为 10s/20s，或 <60s 直接显示秒 |
| P2-4 | 同状态内按 `updatedAt` **升序**排（最久没动的在前），与“最近活跃优先”直觉相反 | `progress_radar.py:64-65` | 同状态改 `reverse=True` 或按 (status, -updatedAt) |
| P2-5 | 回放高亮活不过 1.5s：`_refresh` 每次重建全部 StepRow，高亮被抹掉（也带来持续重建开销） | `progress_cockpit.py:219-233, 353-364` | 回放期间暂停 `_timer`；或只更新时长文本、不重建控件 |
| P2-6 | 注意力路由：(a) 不看过期规则，重启后仍为 3 天前的 need_input 弹通知；(b) 去重键含 updatedAt 秒级时间，1 秒内二次失败会被吞 | `attention.py:12-16`、`app.py:681` | 复用 `qualifies/is_stale`；去重键改用 `sessionId:status:eventId` 或对同 status 只提醒一次直到状态改变 |
| P2-7 | 展开面板固定高度、无滚动；步骤多（40 步 ≈922px）或标题换行时内容/底部按钮被裁 | `progress_radar.py:363-376`（offscreen 600px 屏实测被裁） | 面板高度 `min(h, area.height()-80)` + QScrollArea |
| P2-8 | 多屏/贴边：球隐藏时 `RadarTab.place()` 直接落到“球所在屏”的右缘；球中心若在屏外，`screenAt()` 回退主屏，贴边条可能跳到另一块屏 | `progress_radar.py:157-172`、`:378-398` | 球隐藏时保留最后已知屏幕与边侧；`screenAt` 为 None 时取上次的 screen |
| P2-9 | `_tick()` 在 Qt 槽内直接 `list_sessions()`，无 try；progress 目录不可写/被删时异常会冒到事件循环（PyQt5 默认中止进程）。session 名超 200 字符也会 `FileNotFoundError`（`mkstemp` 路径过长） | `progress_radar.py:320-321`、`store.py:39` | `_tick` 包 try/except 并降级为“本次不动”；session 名截断/校验长度 |
| P2-10 | 工艺：`qualifies` docstring 仍写“≥3 步”（实现已删该条件）；`af progress show` 对不存在的 session 返回 `ok: true, data: {}`；jobs 首次 plan 写失败即 `progress_store=None`，终态不写，留 10 分钟 running 假任务 | `progress_radar.py:44-45`、`cli.py:76-81`、`jobs.py:37-49,60-68` | 修 docstring；`show` 找不到时 `ok:false`；jobs 用 `finally` 兜底写终态 |

## 复验建议（修完后跑）
- `.venv\Scripts\python -m pytest tests/test_progress_store.py tests/test_progress_radar.py tests/test_progress_cockpit.py tests/test_progress_attention.py -q`（当前 11 passed）
- 新增应覆盖：`plan` 重置 createdAt/finishedAt、`cancel/fail` 收尾、`store→cockpit` 端到端“已用”、`_dismiss→tick→_expand` 序列、驾驶舱 failed 重试的步骤集合、双进程同 session 写。
- 真实 GUI/多屏/DPI 仍需人工过一遍（本次全为 offscreen 断言，未截图）。

结论：**PASS WITH NOTES**（P0=0；P1-1/2/3 建议正式版前修掉，P1-4/5 给出缓解即可）。