# REVIEW-RECHECK · 4.0.0 收尾修复复审（只读）

- 时间：2026-11-04
- 审查者：独立只读（未改代码、未 build、未 push）
- 范围：`server.py::put_config`、`web/js/{app,llm}.js`、`progress_radar.py`、`floatball.py`、`tests/test_llm_api.py`、QA/HANDOFF/REVIEW-UI/REVIEW-RELEASE、全量 pytest / pyflakes / node --check、dist 与装机目录
- 结论：**PASS WITH NOTES**（无剩余 P0；剩余 P1 属发布流程，由 lead 接手）

## 摘要（8 行）

1. **P0 真修好**：`put_config` 在 `changed_keys` 不含 `llm` 时用 `handlers.get_config()` 的 `llm` 深拷贝回填（server.py:225-232）；我用「生产语义」替身（`get_config` 返回 deepcopy，同 `WebAppHandlers`）独立复现：无 `changed_keys` / 空数组 / `["theme","opacity"]` 三种旧快照 PUT 后供应商与 Key 均在，删除后再 PUT 仍为空，显式 `["theme","llm"]` 仍可改（不被误拦）。
2. 生产链路自洽：`/api/llm/*` → `_llm_persist` → `apply_config(["llm"])` → `apply_settings` 写 `self.config["llm"]`（floatball.py:2888-2891），故合并读到的是最新 llm 而非旧值；`/api/preview` 走 `preview_only=True`，不碰 llm，无第二条覆盖路径。
3. 新增回归测试 `test_put_config_without_llm_key_keeps_providers` 有效（含「删除后再 PUT 旧快照仍为空」），删掉 merge 即失败；`test_llm_api.py` 11 项全过。
4. P1 草稿：`confirmDiscardDraft()` 覆盖 `selectProvider` / `newProvider` / `activate`，激活当前供应商保留草稿；P1 余额：卡片失败显示 error 小字 + `title`，`refreshBalances` 按 `balance.ok === false && !skipped` 统计并 toast 具体原因（401/字段未命中/网络）；两处均只有代码走查，**未跑浏览器**（QA 已如实标注）。
5. beta 教程重播已恢复 `not is_beta() and not replay and onboarding_done`（floatball.py:2762），语义符合 `docs/发布与版本策略.md`；但 `test_release_channel` 仍只做源码字符串断言（`inspect.getsource` + `in`），不是行为测试。
6. design token：`progress_radar.py` 6px→8px、9px→10px 均落在 `ALLOWED_RADII/ALLOWED_FONTS` 档位；独立复核全量 **577 收集 / 575 passed / 2 failed**（仅 `test_floatball_integration` 两项）、`pyflakes src/agentfloat tests` 0 条、`node --check` app/llm exit 0 —— 与 QA/HANDOFF 数字一致。
7. 修复未引入新 P0/P1；新增问题 6 条均 P2（见下）。
8. **安装包确未重建**：`dist/AgentFloat.exe`（11-2 17:26）、`versions/v4.0.0/dist/AgentFloat-Setup-4.0.0.exe`（11-2 17:27）、装机目录（11-2 17:26-17:28）均早于源码（11-4 14:22-14:25）；`_internal/web/js/app.js`、`llm.js` 与仓库哈希不同 → 当前包不含本次修复，待 lead 重建。

## P0 阻断

无。

## 剩余 P1（不在本轮修复范围，需 lead 决定）

### P1-R1 4.0 代码仍未入库，干净 clone 无法复现构建

- Finding：`git status --porcelain` 仍 82 项；`mcp_entry.py`、`skills/progress-protocol/SKILL.md`（`build_exe.py` 构建输入）、`src/agentfloat/services/llm.py`、`src/agentfloat/services/progress/`、`ui/progress_radar.py`、`web/js/llm.js` 全部 untracked。
- Evidence：`git status --porcelain`；`Test-Path mcp_entry.py / skills\progress-protocol\SKILL.md` 均 True（存在的只是文件，不在索引）。
- Why：仍是 REVIEW-RELEASE P1-3 原状，换机器/干净 clone 直接 build 失败，本次安装包不可复现。
- Fix：lead 按用户确认后提交（复核不被 `debug_logs/`、`skills_workshop/`、`.workbuddy/` 混入；`.gitignore:88-90` 已验证命中），再用干净 clone 跑一次 build。

### P1-R2 发布包尚未重建（当前包不含 P0 修复）

- Finding：dist/装机目录全部是 11-2 构建；源码改动在 11-4。
- Evidence：`dist/AgentFloat.exe` 9863959B@11-2 17:26:38、`%LOCALAPPDATA%\Programs\AgentFloat\AgentFloat.exe` 同尺寸同时刻；`_internal/web/js/llm.js` SHA256 47FDDF4B… vs 仓库 9D0E0019…（app.js 同样不同）。
- Why：现在拿去发布就是「P0 未修」的二进制，且与源码脱节。
- Fix：lead 重建 → 每版本地安装 → 拆包核对 `_internal/web/js/{app,llm}.js` 哈希与仓库一致 + `_internal/VERSION=4.0.0`。

### P1-R3 前端三处修复仍无运行证据（发布前必做）

- Finding：草稿确认、余额失败文案、进页重拉配置，均未在浏览器点过。
- Evidence：QA.md 第 3 节自述「未跑浏览器冒烟」；本轮我只能 `node --check` + 代码走查。
- Why：4.0 验收项（Key 不丢 / 删除不复活 / 余额可诊断）只有服务端测试支撑，前端接线（`confirmDialog` 返回值、`state.error` 分支）无证据。
- Fix：真服务 + mock `_http_json` 走一遍：填 Key → 测试 → 输入框仍在 → 保存；删供应商 → 进设置页保存 → 卡片不回来；余额 401 → toast 与卡片文案。

## 新增 P2（修复引入或暴露）

1. **进页重拉最长阻塞 15s**：`goPage` 对 `settings/api/llm` 先 `await refreshConfig()`，`API.api` 默认 `DEFAULT_TIMEOUT=15000`（api.js:47）。本地服务卡住时切页会停在旧页面最长 15 秒，无骨架/提示。Fix：该次 GET 传 `timeout: 3000`，失败静默降级。
2. **`confirmDialog` 不 resolve 的关闭方式**：Esc / 点遮罩只 `closeModal()` 不 resolve（app.js:2907-2920 vs 3015-3016），`await confirmDiscardDraft()` 会永久 pending → 用户点卡片「没反应」，还会阻塞后续点击（无 toast）。Fix：`closeModal` 时 resolve(false)，或给 confirmDialog 挂兜底 reject。
3. **无 Key 供应商被算作「刷新失败」**：`fetch_balance` 的「未配置 API Key」分支没有 `skipped: True`（llm.py:1059-1061），于是 `refreshBalances` 每次 toast「N 个供应商查询失败：… 未配置 API Key」，卡片同时出现「未配置 Key」与「未配置 API Key」两个 chip。Fix：该分支加 `skipped` 或前端按 `api_key_set===false` 排除。
4. **CHANGELOG 数字未更新**：4.0 条目仍写「LLM/日报/翻译/回归 146+ 项通过；pyflakes/node 检查通过」。现在这句话不再虚假，但发布说明缺真实数字（577/575 passed，2 known failures）。Fix：按 HANDOFF 第 4 步改。
5. **token 修的是数值不是 token，且测试有逃逸口**：`progress_radar.py` 写死 `8px`/`10px`（值合规，未引用 `RADIUS.sm`/`FONT.micro`）；`font-size:10.5px`（progress_radar.py:440）与 `padding-left:4px` 类写法能被 `test_design_tokens` 的 `(\d+)px` 正则漏过。Fix：后续统一走 token 常量，正则加 `[\d.]+`。
6. **合并依赖「内存 llm 最新」**：`put_config` 只在 `isinstance(current.get("llm"), dict)` 时合并；若 `/api/llm/*` 的 `apply_config` 超时/无 Qt（`_llm_persist` 的 except 分支只落盘），内存里可能没有 llm → 不合并 → 旧快照仍覆盖磁盘。Fix：`current.get("llm") or load_config().get("llm")` 兜底。

## 已核对（本轮实际执行）

```
.venv\Scripts\python -m pytest -q --junitxml=%TEMP%\af_recheck.xml
# tests=577 failures=2 errors=0 skipped=0（仅 test_floatball_integration 两项）
.venv\Scripts\python -m pyflakes src/agentfloat tests   # exit 0，无输出
node --check web/js/llm.js / web/js/app.js               # exit 0 / exit 0
git check-ignore -v debug_logs\... skills_workshop\... .workbuddy\...   # 命中 .gitignore:88-90
```

- 独立 P0 探针（`%TEMP%\af_recheck_p0.py`，不入库）：生产语义 handler + TestClient，覆盖 4 种 `changed_keys` 组合，结果见摘要第 1 条。
- `_llm_persist` → `apply_settings` 的 llm 回写已逐行核对（floatball.py:2888-2891）。
- 安装包/装机目录：文件时间与 web 资源哈希比对（见 P1-R2）。

## 未验证（不猜）

- 两个 `test_floatball_integration` 失败是否早于本次修复：只读约束下未回退代码复跑；但 floatball.py 的 diff 未触及 `_enter_move_mode/_exit_move_mode` 与鼠标交互区（改动集中在 2383-2440 菜单与 2555-2718 引导演示），失败表现为窗口几何，与本轮改动无交集。建议 lead 在干净 HEAD 上单独确认一次。
- 浏览器实际行为（同 P1-R3）；真实 DeepSeek / OpenRouter / OpenCode Go 余额 401 与 `percent` 量纲。
- 打包环境里的启动动画淡出、进度雷达圆角改动的观感、引导重播（未启动 GUI）。

## 结论

**PASS WITH NOTES**。P0（PUT /api/config 覆盖 llm）已实质修复并可用「去掉 merge 即失败」的回归测试守住；P1 清单（草稿、余额原因、beta 重播、design token、575/2、pyflakes 0）均已兑现，未见修复引入的新 P0/P1。发布仍被三件事挡住：4.0 代码未入库（P1-R1）、安装包未重建（P1-R2）、前端修复无运行证据（P1-R3）——都由 lead 收口，不是本轮代码问题。