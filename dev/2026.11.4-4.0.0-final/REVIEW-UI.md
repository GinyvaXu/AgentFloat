# REVIEW-UI · 4.0.0 LLM「AI 接入」页（只读审查）

- 审查时间：2026-11-04
- 审查范围：`web/js/llm.js`、`web/js/app.js`（导航/路由）、`web/css/style.css`（`.llm-*`）、`web/index.html`、
  `src/agentfloat/services/llm.py`、`src/agentfloat/webshell/{server,handlers}.py`、`dev/2026.11.2-llm-integration/{QA,HANDOFF,REVIEW}.md`
- 结论：**BLOCK**（P0 1 项、P1 2 项、P2 8 项）
- 方式：静态审查 + TestClient 复现（未起 GUI、未连真实端点）

## 摘要（10 行）

1. **BLOCK**：设置页 / API 用量页的「保存」会把整份旧 `config` 写回，静默覆盖 LLM 页改动 —— 新增供应商连同 Key 消失、删掉的供应商连同 Key 复活并重新成为 active；P0-1 的服务端修复在这条真实操作序列下被抵消（已复现）。
2. 导航链路完整：`index.html` 导航项 → `goPage("llm")` → `renderLlmPage()`，页面确实可达，不是只存在于文件里。
3. 但 hash 白名单未加 `llm`，`#/llm` 刷新/重开回到「设置」页（路由只写了一半）。
4. 草稿测试不丢 Key：`state.dirty` 保护 + 测试请求携带新 Key，代码路径正确；不过「点另一张卡片 / + 添加 / 设为当前」仍会静默丢弃未保存草稿，P1-2 只修了后台刷新这一半。
5. 保存合并规则、Key 只回尾 4 位、`balance_url` 仅 http(s)、删除不复活（服务层）：静态核对均闭合，pytest 有对应断言。
6. Token 汇总口径与前端「累计」标注一致；但币种兜底仍会被 `_money_value` 的字段名启发式抢先猜成 CNY，`OTHER` 分支基本不可达。
7. 错误态偏弱：查询失败一律显示「余额 —」，「刷新余额」无论全败都 toast「余额已刷新」，401 / 地址写错时用户拿不到线索。
8. 与「API 用量」页存在实质重复：同一把 Key 分别存在 `api_monitor.endpoints[].headers` 和 `llm.providers[].api_key`，两套低余额阈值，指南页完全没提「AI 接入」。
9. 测试证据：`pytest` 69 + 12 全绿、`node --check` 0；但 QA 自己注明浏览器冒烟未复跑，清单却把该项勾成 [x]。
10. 未验证：安装包内是否含 `web/js/llm.js`、真实 DeepSeek/OpenRouter/OpenCode Go 联调、窄屏实拍（本轮无截图）。

## P0 阻断（must fix）

### P0-1 全量 `PUT /api/config` 覆盖 `llm`：新增供应商被抹掉、删除的供应商复活

- Finding：`web/js/app.js` 的 `cfg` 只在 `init()` 里 GET 一次，LLM 页所有写操作走的是 `/api/llm/*`，从不回写 `cfg`。
  之后用户在「设置」或「API 用量」页点保存（`App.save()` 不做 diff 过滤，即使 0 处改动也照发整份 config），
  `put_config` 直接把这份**旧快照**落盘并 `apply_settings(full config)`，`llm.providers/active` 整体回滚。
- Evidence：
  - `web/js/app.js:111-117`（`save()` 无条件 PUT 整份 `cfg`，成功后才回读）
  - `web/js/app.js:2999-3001`（`cfg` 仅 init 时加载，全文只有 3 处赋值：115 / 3000 / 3309）
  - `web/js/app.js:1948`（「API 用量」页顶部就有「保存设置」按钮，紧邻新页面）
  - `src/agentfloat/webshell/server.py:220-228`（`put_config` 不合并、直接 `save_config(cfg)`）
  - `src/agentfloat/app.py:574-576`（`apply_settings(整份 config)`，旧 `llm` 同样进内存）
  - 实测（TestClient + 假 handlers，桩 `_http_json`）：
    - `POST /api/llm/providers` → 磁盘 `['deepseek']` → `PUT /api/config {config: 旧快照}` → 磁盘 `[]`，页面下次 GET 也 `[]`
    - `POST /api/llm/providers/deepseek/delete` → 磁盘 `[]` → `PUT /api/config {config: 旧快照}` → 磁盘 `[('deepseek','sk-secret-1234')]`，`active=deepseek`
- Why：这是静默数据损失（用户刚粘的 Key 被丢弃，toast 却显示「已保存：无变化」），并且**把 P0-1 的成果原地推翻**——
  「删除不复活」只在直接调 `/api/llm/*` 时成立，真实用户只要在隔壁页保存一次，付费 Key 就回来了且重新计费。
  4.0 验收项「删除不复活 / Key 不丢」在这条路径上不成立。
- Fix（二选一，推荐 a + b 都做）：
  - a) `put_config` 服务端合并：`cur = handlers.get_config(); if "llm" not in (changed_keys or []): cfg["llm"] = cur.get("llm")`；
  - b) 进入设置页 / API 用量页前重新 GET `/api/config` 刷新 `cfg`（`goPage` 分支里加一次拉取），并在 `save()` 成功后同步刷新 LLM 页 `state.data`；
  - 补测试：`test_put_config_without_llm_key_keeps_providers`（含「删除后再 PUT 旧配置仍为空」）。

## P1 重要

### P1-1 「切换/新增/设为当前」静默丢弃未保存草稿（P1-2 的剩余半边）

- Finding：`selectProvider()`、`newProvider()`、`activate()` 都直接 `state.draft = draftFrom(...)` / `= null` + `dirty = false`，
  不检查 `state.dirty`、不弹确认。用户输完 Key 点错卡片、或点「切换」再回来，输入内容与 Key 一起消失且无提示。
- Evidence：`web/js/llm.js:400-409`、`web/js/llm.js:411-416`、`web/js/llm.js:465-483`（476-477 清空 draft 与 dirty）
- Why：与 REVIEW P1-2「静默改配置是最难排查的一类问题」同源；后台刷新已保护，用户主动动作反而没保护，用户会以为 Key 保存过。
- Fix：三个入口统一前置 `if (state.dirty && !confirm(...)) return;`（可复用 `window.App.confirmDialog`），
  或在切换前把草稿暂存到 `state.draftsBySelected`；至少「设为当前」不要清空草稿。

### P1-2 「刷新余额」恒报成功，失败原因在页面上永远看不到

- Finding：`/api/llm/refresh` 只清缓存并返回 `{ok:true}`；前端不看每个 provider 的 `balance.ok`，直接 toast「余额已刷新」。
  卡片在 `balance.ok=false` 时统一显示「余额 —」，`balance.error`（401 / 字段未命中 / 未配置 Key）完全没渲染。
- Evidence：`web/js/llm.js:544-557`、`src/agentfloat/webshell/server.py:468-472`、`web/js/llm.js:211-217`
- Why：这是余额监控页的核心失败路径；Key 写错或 `balance_field` 写错时用户只能看到「—」，且被成功提示误导。
- Fix：`refreshBalances()` 读 `load(true)` 的返回值，统计 `providers.filter(p=>p.balance && !p.balance.ok && !p.balance.skipped).length`，
  有失败就 toast「N 个供应商查询失败」；卡片失败时把 `balance.error` 放进 `title` 或第二行小字（REVIEW P2-5 仍未修）。

## P2 建议

### P2-1 hash 路由白名单缺 `llm`

- Finding：`goPage()` 会把地址写成 `#/llm`，但启动恢复的白名单里没有 `llm`，刷新/重开 web 壳会回落到设置页。
- Evidence：`web/js/app.js:3008-3010`（`["api","news","settings","install","skills","guide"]`）
- Fix：白名单补 `"llm"`（1 行）；顺手把 `"guide"` 也纳入（当前 guide 会落到 `loadNewsPage()`）。

### P2-2 空态文案自相矛盾，首次进入是死路提示

- Finding：左侧空态说「先在右侧选一个预设（DeepSeek / OpenRouter / OpenCode Go…），填 Key 后保存」，
  但右侧此时只有「点击左侧卡片编辑，或点「+ 添加供应商」新建」，根本没有预设下拉；新用户不知道该点哪里。
- Evidence：`web/js/llm.js:239-241`、`web/js/llm.js:285-288`
- Fix：空态改为「点下方「+ 添加供应商」→ 选预设 → 填 Key」，或空态直接内联一个预设下拉 + 新建按钮。

### P2-3 币种 `OTHER` 兜底基本不可达（P2-1 只修了一半）

- Finding：`summarize_balances` 已不默认 CNY，但上游 `_money_value` 在 `currency` 为空时仍按字段名猜：
  `"balance" in field` → `CNY`、`total_credits` → `USD`。于是「未知币种」几乎总被填成具体币种，仍可能把美元计进人民币合计。
- Evidence：`src/agentfloat/services/llm.py:993-1000`（猜币种）、`llm.py:1163-1168`（OTHER 分支）
- Fix：`_money_value` 不再按字段名猜，只认 `provider.currency` 与响应里的 currency 字段；都没有就返回 `""`，交给 `OTHER`。

### P2-4 删除当前供应商后，回落到「没有 Key 的供应商」

- Finding：`delete_provider` 选下一个 active 时只看 `enabled`，不看 Key；与 P1-3「无 Key 不自动激活」的规则不一致。
- Evidence：`src/agentfloat/services/llm.py:548-549`（对比 `llm.py:390-396` / `llm.py:529-531` 都查了 Key）
- Fix：回退条件改成 `enabled and resolve_provider_key(p)`。

### P2-5 无障碍：label 未关联、嵌套交互元素

- Finding：`field()` 只输出并列的 `<label>` + 控件，没有 `for`/`id`（仅预设下拉有 id），读屏无法把「Base URL」「模型」念出来；
  供应商卡片是 `role="button"` 的 div，内部又嵌了 `<button>`（切换），嵌套交互元素在 AT 里行为不可靠；页面内没有 h2 级标题。
- Evidence：`web/js/llm.js:345-347`、`web/js/llm.js:303-311`、`web/js/llm.js:228-236`
- Fix：`field()` 生成 `id` + `label[for]`（或 `aria-label`）；卡片的「切换」按钮改为 `aria-hidden` 之外的独立焦点项（把卡片做成 description，不在 role=button 里嵌 button）。

### P2-6 与「API 用量」页重复入口、双份 Key、指南未更新

- Finding：同一把 API Key 会同时存在于 `api_monitor.endpoints[].headers.Authorization` 和 `llm.providers[].api_key`；
  两页各有一套低余额阈值与「余额」展示（迁移只拷贝一次，之后互不同步）。「使用指南」第 ⑤ 节只讲 API 余额监控，
  全新用户从指南里找不到「AI 接入」，而「API 用量」与「AI 接入」两个导航名也容易混淆。
- Evidence：`src/agentfloat/services/llm.py:284-328`（一次性迁移）、`web/js/app.js:1916-1950`（API 页）、
  `web/js/app.js:2651,2702-2705`（指南章节表无 llm）、`web/index.html:25-26`
- Fix：两页各加一行互链与「Key 改动不会同步到另一处」说明；4.x 再考虑让 api_monitor 端点引用 `llm.providers[].id` 复用 Key；
  指南加「⑥ AI 接入（可选）」小节。

### P2-7 数字/文案小瑕

- `fmtTokens(999950)` → `n/1000=999.95` → `toFixed(1)="1000.0"` → 输出「1000K」而不是「1M」（`web/js/llm.js:32-37`）。
- `moneyText(amount, "")` 会多一个尾空格（`web/js/llm.js:39-44`）。
- Fix：先按 1e6 阈值判断；空币种直接返回数字。

### P2-8 测试证据与清单不一致

- Finding：`QA.md` 第一节把「测试 / 后台刷新不再清空未保存输入（state.dirty）」勾成 `[x]`，但同文件第四节明确写「本轮未复跑浏览器冒烟」，
  该项只有代码走查。其余 `[x]`（切换 / 保存 / 测试 / 深色）也没有本轮修复后的运行证据。
- Evidence：`dev/2026.11.2-llm-integration/QA.md:44` vs `QA.md:115-118`；`HANDOFF.md:22-23`
- Fix：把该项改成「代码走查（未运行验证）」，并按 HANDOFF 第 1 步用真服务 + mock `_http_json` 复跑，
  重点验「填 Key → 测试 → 输入框仍在 → 保存带新 Key」与「删除后卡片不回来」。

## 已核对（静态 + 可复现）

- 导航可达：`web/index.html:26` → `web/js/app.js:2974,1363` → `web/js/llm.js:112-122`；`#llmContent` 存在（`index.html:76-78`）。
- 草稿测试：`test_provider()` 归一化后走临时 config，不落盘、不改 active（`llm.py:933-967`），`tests/test_llm_api.py` 覆盖。
- Key 脱敏：`/llm/providers`、保存、激活三处都走 `mask_provider`（`llm.py:582-593`），响应只给尾 4 位；`/llm/test` 不回 Key。
- `balance_url` 协议：`validate_provider` + `_http_json` 双层 `_require_http_url`（`llm.py:596-605, 626, 1057`），`file://` 在发请求前抛错。
- 删除不复活（服务层）：`migrated_from_api_monitor` + `deleted_ids`（`llm.py:360-380, 550-555`）；但见 P0-1。
- 窄屏：`.llm-layout` 900px 单列、560px 字段竖排、`.llm-top` 换行（`style.css:812-815, 897-905`），静态无溢出风险。
- XSS：所有插值走 `esc`，toast 用 `textContent`（`util.js:8,14-21`），`data-llm-*` 属性同样转义。

## 运行证据（本轮实际执行）

```
.venv\Scripts\python -m pytest tests/test_llm_service.py tests/test_llm_api.py tests/test_config.py tests/test_server_api.py
# 69 passed in 4.55s
.venv\Scripts\python -m pytest tests/test_news_worker.py tests/test_ai_service_pure.py
# 12 passed in 0.37s
node --check web/js/llm.js      # exit 0
```
另用 TestClient 写了两个一次性脚本（`%TEMP%`，不入库）复现 P0-1 的两条路径。

## 未验证（不猜）

- 安装包内是否包含 `web/js/llm.js`（`build_exe.py:32-36` 以整个 `web` 目录作为 datas，静态看应该包含，但未拆包核对）。
- 真实 DeepSeek / OpenRouter / OpenCode Go 端点与订阅 `percent` 量纲（0-100 还是 0-1）。
- 深色主题、420/600/760 窄屏实拍（本轮无截图，只按 CSS 复核）。
- 未复跑浏览器冒烟；`state.dirty` 修复的运行期表现只有代码走查。
- 两个标签页并发保存的丢失更新：只做了代码推断（P0-1 是其中一种表现）。