# REVIEW · AI 供应商接入 / 余额 / Token 统计

- 审查时间：2026-11-02
- 审查范围：`services/llm.py`、`/api/llm/*`、`web/js/llm.js`、`style.css`、`news/worker.py`、`skills/ai_service.py`、`core/config.py`
- 结论：**BLOCK**（P0 1 项、P1 5 项）

## 摘要

1. 核心骨架合格：掩码覆盖了所有返回 provider 的路径，日志/异常无 Key，XSS 面已封（esc + toast 用 textContent）。
2. 新测试 39 项与既有 test_config / test_server_api 合跑 55 项，本地复跑全绿；但测试没覆盖「未保存的新供应商」和「删空后重新归一化」两条真实路径。
3. **P0：删掉的供应商会在下一次 GET 立刻复活并重新成为 active**，被迁移的付费 Key 会一直生效。
4. 三个用户主流程是坏的：新供应商「测试」必然 400；「测试」会清掉刚输入的 Key；LLM 通道坏了不会回退 CLI Agent（4.0 回归面）。
5. `balance_url` 未校验协议，`file://` 可把本地文件前 120 字符带进错误信息；配合每次开页面自动查询，属低成本可修的读文件面。
6. 本机鉴权（Host/Origin/token）仍在，SSRF 影响局限于本机；但发布前必须把 `config.json.bak*` 加进 .gitignore。
7. 余额/统计口径正确（金额、OpenRouter credits、订阅 percent 只读、估算标记、跨日跨月），问题集中在币种兜底与文案口径。
8. 浏览器冒烟（mock）无法发现第 4 条：mock 的 `/api/llm/test` 恒返回 ok，且新建供应商硬编码 low_balance_warn。修复后需用真服务 + mock HTTP 重跑。

## P0 阻断（must fix）

### P0-1 删除供应商被「迁移逻辑」就地复活

- Finding：`delete_provider` 生效后，下一次 `normalize_config()`（`GET /api/llm/providers` 每次都会调）在 `providers` 为空时重新从 `api_monitor.endpoints` 派生同一个供应商并自动设为 active。UI 表现为「删除成功 → 卡片立刻回来 → 仍是当前使用」。
- Evidence：
  - `src/agentfloat/services/llm.py:352-360`（`if not providers and derive_from_api_monitor` 无「仅迁移一次」条件）
  - `src/agentfloat/webshell/server.py:342-346`（`_llm_config()` 每次 GET 都 `normalize_config`）
  - `src/agentfloat/core/config.py:236-247`（启动加载也会走同一路径）
  - 实测（TestClient，桩 `_http_json`）：`GET -> [('deepseek', True)] active=deepseek` → `POST delete -> {'ok': True, 'active': ''}` → `GET -> [('deepseek', True)] active=deepseek`
- Why：BRIEF 验收项「供应商 CRUD」不成立；用户以为删掉了付费 Key，AI 快报 / Skills 翻译仍继续用它计费。
- Fix：迁移只在「配置里原本没有 `llm` 键」时做一次，例如 `derive = derive_from_api_monitor and "llm" not in config`，或迁移后写 `llm.migrated_from_api_monitor = true` 并据此跳过；同时补一条「删除最后一个迁移供应商后 GET 不再返回」的测试。

## P1 重要

### P1-1 未保存的新供应商「测试」必然失败

- Finding：页面主流程「+ 添加 → 填 Key → 测试 → 保存」在第一步就返回 400「尚未设置当前 AI 供应商，请先在 AI 接入页添加并设为当前」。
- Evidence：
  - `src/agentfloat/services/llm.py:889`（`tmp_cfg` 的 `active` 取 `candidate.get("id")`，新草稿 id 为空）
  - `src/agentfloat/services/llm.py:395-399`（`_llm_of` 对已是 dict 的 `llm` 直接返回，不做归一化）
  - `src/agentfloat/services/llm.py:805-818`（`chat()` 无 provider_id 时只认 active）
  - 实测：`POST /api/llm/test`（新草稿）→ `400 {'ok': False, 'error': '尚未设置当前 AI 供应商…'}`
- Why：QA 只测了「先保存再测试」，所以没暴露；这是页面上最自然的顺序，用户会以为自己的 Key 坏了。
- Fix：`test_provider()` 里先 `candidate = _normalize_provider(candidate)`，再用 `candidate["id"]` 作 `tmp_cfg.active`；补「无 id 草稿可测试且不落盘」的测试。

### P1-2 点「测试」后草稿被静默重置，刚填的 Key 丢失

- Finding：测试成功后 `load(false)` 无条件用服务端数据重建 `state.draft`，未保存的输入（尤其是新的 API Key）被清空；随后点「保存」，请求里没有 `api_key`，服务端按「留空保留旧 Key」处理 → 用户以为换了 Key，实际还是旧的，toast 仍显示「已保存」。
- Evidence：
  - `web/js/llm.js:131-135`（只要 `state.selected` 就 `state.draft = draftFrom(...)`，无 dirty 判断）
  - `web/js/llm.js:487`（`test()` 收尾 `load(false)`）
  - 浏览器实测（真 `web/` + mock API）：在 DeepSeek 卡片输入 `sk-BRAND-NEW-KEY-9999` → 点「测试」→ 输入框变空，placeholder 回到「已保存 sk-…1234（留空不改）」
- Why：静默改配置是最难排查的一类问题；也影响「切页再回来」的未保存编辑。
- Fix：加 `state.dirty`（任何 `input`/`select` 变更置位），`load()` 只在 `!dirty` 或 `选中 id 变化` 时重建 draft；测试完成后不要整页重载，最多刷新余额与统计。

### P1-3 `has_active_provider` 只认 base_url+model，且失败不回退 CLI Agent（4.0 回归面）

- Finding：供应商没有可用 Key（新加但没填、或 `{{env:XXX}}` 未设置）时仍被判为「可用」，AI 快报与 Skills 翻译改走 LLM 并直接失败；两条路都没有回退到原来能用的 CLI Agent。
- Evidence：
  - `src/agentfloat/services/llm.py:433-435`（只校验 base_url / model，不 `resolve_api_key`）
  - `src/agentfloat/services/llm.py:496-497`（`upsert_provider` 会顺手把第一个供应商设为 active）
  - `src/agentfloat/services/news/worker.py:419-440`（`if llm_ready: ... elif agent:`，LLM 失败不会进 agent 分支）
  - `src/agentfloat/services/skills/ai_service.py:512-513, 556-569`（`use_llm` 命中即只用 LLM，`out is None` 直接返回错误）
- Why：老用户升级后只是「保存了一个供应商」或「迁移出一个端点」，就可能出现 AI 快报降级为标题列表、自动翻译整体报错，且不再是原来的 Agent 生成，属发布阻断级回归。
- Fix：`has_active_provider` 增加 `resolve_api_key(provider)` 非空；`worker` / `run_services` 在 LLM 抛 `LLMError` 时回退到 agent 通道（记录一条 warning）；`upsert_provider` 不自动把无 Key 供应商设为 active。

### P1-4 `balance_url` 没有协议校验，`file://` 可读本地文件

- Finding：`balance_url` 完全由用户/接口写入，`fetch_balance` 直接 `urllib` 打开；`file://` 会被默认 opener 处理，JSON 解析失败时错误信息回显响应前 120 字符，并在页面上游可见。
- Evidence：
  - `src/agentfloat/services/llm.py:987-995`（不做 scheme 校验直接 `_http_json("GET", url)`）
  - `src/agentfloat/services/llm.py:588-591`（`响应不是 JSON（前 120 字符）：%s`）
  - `src/agentfloat/services/llm.py:438-452`（`validate_provider` 只校验 base_url 的 `^https?://`，不管 balance_url）
  - `src/agentfloat/webshell/server.py:372`（每次 GET 列表自动对所有启用供应商发起查询）
- Why：本地 token 鉴权 + Host/Origin 校验把可利用面压到本机，但「任意 URL/任意协议由后端发起」是与既有安全加固不符的缺口，修复成本极低。
- Fix：`validate_provider` 增加 balance_url scheme 白名单（http/https，空值允许）；`fetch_balance` 里再兜一层，拒绝非 http(s)。不要封 127.0.0.1（本地网关是合法用法）。

### P1-5 `config.json.bak*` 未被 .gitignore 覆盖（发布前必改）

- Finding：Key 现在以明文存在 `config.json` 的 `llm.providers[].api_key`，而仓库根目录已有两份 `config.json.bak-*` 处于未跟踪状态；`.gitignore` 只写了 `config.json`，`git add -A` 会把备份连 Key 一起入库。
- Evidence：
  - `.gitignore`（`config.json` / `launcher_config.json` 两行，无通配）
  - `git status --porcelain` → `?? config.json.bak-002035`、`?? config.json.bak-radar`（当前两份暂未含密钥，我用 `api_key/Bearer/sk-` 检索为 0 命中）
- Why：4.0 push 前的最后一脚，属于「一旦发生就无法回收」的泄露。
- Fix：`.gitignore` 改为 `config.json*`（保留现有逐项），并把已有 bak 移出仓库目录。

## P2 建议

### P2-1 总余额币种兜底成 CNY，可能把美元算进人民币

- Evidence：`src/agentfloat/services/llm.py:1097`（`balance.get("currency") or provider.get("currency") or "CNY"`）
- Fix：无法判定时归到 `OTHER`/不参与合计，或要求保存时填币种；不要把未知币种默认成 CNY。

### P2-2 Token 统计口径与文案不一致

- Finding：「今日 / 本月」卡片里的「AI 快报」「Skills 翻译」是**全量历史**；「最近调用」只取**今天**的记录。
- Evidence：`src/agentfloat/services/llm.py:741-746`（by_purpose 不分时间）、`llm.py:749-764`（recent 仅在 `ts.startswith(today)` 内收集）、`web/js/llm.js:256-257`
- Fix：分用途按今日或本月统计（或标题写「累计」），recent 不按今日过滤（全量取最后 8 条）。

### P2-3 用量文件无轮转，且首屏同步等余额

- Evidence：`src/agentfloat/services/llm.py:692-712`（每次全量读 JSONL）、`llm.py:1056-1078`（页面加载即并行查余额，单个 8s 超时）、`web/js/llm.js:127`（首屏 30s 超时）
- Fix：按月分文件或写入时顺带维护 `llm_usage_summary.json` 增量；GET 列表先返回缓存，余额由前端异步补（或把首屏超时压到 10s）。

### P2-4 `/api/config` 仍返回 `llm.api_key` 明文

- Evidence：`src/agentfloat/webshell/server.py:216-218`（返回完整 config）；`web/js/llm.js:9-10` 的「不回显」只对 `/api/llm/*` 成立
- Why：沿用 api_monitor 的旧模式，不算新漏洞，但与本次「密钥不回显」的验收表述冲突，且设置页保存会把整份含 Key 的 config 再 POST 回来。
- Fix：至少在文档/验收里写明范围；有空时给 `/api/config` 做一层 provider 掩码 + PUT 时「空 Key 保留」。

### P2-5 余额状态在卡片上反馈不足

- Finding：`balance.error` 前端完全没用，任何失败都显示「余额 —」；active 卡片的「余额偏低」徽标被 `!isActive` 抑制，但顶部低余额数包含它，用户看到计数却找不到是哪张卡。
- Evidence：`web/js/llm.js:192-204`、`web/js/llm.js:214`
- Fix：失败时给 title/详情显示 `balance.error`；低余额徽标对所有卡片显示（active 可换一种颜色）。

### P2-6 Key 提示泄露前 3 位；env Key 场景显示「未配置 Key」

- Evidence：`src/agentfloat/services/llm.py:536-542`（`resolved[:3] + "…" + resolved[-4:]`）、`llm.py:966-971`（订阅型会回退 `{{env:OPENCODE_GO_API_KEY}}`）
- Why：截图里 OpenCode Go 卡片显示「未配置 Key」，但余额查询其实能用环境变量成功 —— 状态自相矛盾。
- Fix：提示只留尾 4 位；`mask_provider` 用与 `fetch_balance` 相同的 env 回退来判断 `api_key_set`。

## 验证与未验证

已复现/已核对：
- `pytest tests/test_llm_service.py tests/test_llm_api.py tests/test_config.py tests/test_server_api.py -q` → 55 passed
- 服务层与 API 两条 P0/P1 路径用 TestClient/直接调用复现（桩 `_http_json`，未连真实网络）
- P1-2 用真 `web/` + mock API 在 Chromium 里复现
- 掩码：`/llm/providers`、`/llm/providers`(POST)、`/activate` 三处全部走 `mask_provider`；`/llm/test`、`/llm/usage`、`/refresh` 不含 Key；日志仅打印供应商名
- 窄屏：420 / 600 / 760 三档无横向溢出，「测试」按钮 40×24 未被挤压（QA 截图里的竖排按钮在当前样式下未复现，按当前代码不计入问题）
- XSS：`esc` 转义引号，toast 用 `textContent`，余额/错误文本均经 `esc`

未验证（不猜）：
- 真实 DeepSeek / OpenRouter / OpenCode Go 联调（QA 已如实标注）；订阅型 `percent` 是 0-100 还是 0-1 未证实，若是小数需要 ×100 并加断言
- 深色主题与 QA 截图之外的分辨率：只按现有截图与 CSS 复核，未重新实拍
- 并发保存（两个标签页同时改配置）的丢失更新：只做了代码推断，未实测

## 结论

**BLOCK**：P0-1 必须先修（否则删除功能形同虚设、付费 Key 无法停用）；P1-1/P1-2 是主流程坏点，P1-3 是 4.0 回归面，建议同一轮修完再重跑 QA 与冒烟（冒烟需改用真服务 + mock `_http_json`，不要用恒返回 ok 的 mock 路由）。
