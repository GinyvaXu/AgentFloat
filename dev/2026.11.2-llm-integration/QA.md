# QA · AI 供应商接入 + 余额/订阅用量 + Token 统计

- 日期：2026-11-02
- 范围：`services/llm.py`、`/api/llm/*`、Web「AI 接入」页、测试
- 环境：Windows 10 / Python 3.14（项目 `.venv`）/ Node 24 / Chromium（Playwright）

## 一、验收清单（可逐项勾选）

### 服务层
- [x] 配置归一化：缺 `llm` 自动补、字段补齐、`active` 悬空回退
- [x] 旧配置迁移：`api_monitor.endpoints` 中首个「有 Key + 有 model」的端点复用为供应商（**只迁移一次**，删除后不复活）
- [x] 供应商 CRUD：新增 / 更新（Key 留空保留旧 Key）/ 删除 / 列表
- [x] 一键激活：只改 `config.llm.active`；停用或不存在时报可读中文错误
- [x] `test_provider()`：用草稿临时测试（**含未保存、无 id 的新供应商**），不切换 active、不落盘；计一条 `purpose=test`
- [x] `chat()`：OpenAI 兼容 `/chat/completions`，返回 content/usage/latency
- [x] 无 `usage` 字段时按字符 /4 估算并标 `estimated`
- [x] Key 脱敏：`mask_provider()` 只给 `api_key_set` + **尾 4 位**提示；订阅型与 `fetch_balance` 同样走 env 回退
- [x] `has_active_provider()` 要求 Key 可解析；LLM 失败时 AI 快报 / Skills 翻译回退 CLI Agent
- [x] `balance_url` 只允许 http/https（`validate_provider` + `_http_json` 双层），`file://` 拒绝且不回显内容
- [x] 金额余额：DeepSeek `balance_infos[0].total_balance`、OpenRouter `total_credits - total_usage`
- [x] 订阅用量：OpenCode Go `usage.rolling/weekly/monthly.percent`，只读、不计入总余额
- [x] 余额查询永不抛异常（网络/解析失败返回 `ok:false` + 原因）
- [x] 余额 60s 缓存 + 强制刷新 + 并行查询
- [x] Token 统计：今日 / 本月 / 分用途（news / translate / test）/ 各供应商今日 / 最近 8 条
- [x] 坏 JSONL 行跳过，不炸统计

### API
- [x] `GET /api/llm/providers`（含余额、今日 tokens、汇总、预设）
- [x] `POST /api/llm/providers`（保存，响应不含 Key）
- [x] `POST /api/llm/providers/{id}/activate`
- [x] `POST /api/llm/providers/{id}/delete`（另兼容 `DELETE`）
- [x] `POST /api/llm/test`、`POST /api/llm/refresh`、`GET /api/llm/usage`
- [x] 保存后同步 Qt 内存配置（无 Qt 场景只落盘，不报错）

### Web 页面
- [x] 导航新增「AI 接入」，标题 / 页面切换 / 保存按钮显示逻辑接入
- [x] 顶部汇总：总余额（按币种）、今日/本月 Token、订阅数、低余额
- [x] 供应商卡片：名称、模型、域名、今日 tokens、余额或订阅百分比、刷新时间、当前使用标记
- [x] 点击卡片切换编辑对象；卡片「切换」按钮一键设为当前（已实测）
- [x] 右侧编辑：预设 / 名称 / Base URL / 模型 / Key / 类型 / 余额接口 / 余额字段 / 低余额 / 备注 / 启用
- [x] 预设联动填充；订阅型锁定余额接口为 OpenCode Go usage、字段只读
- [x] 保存（实测 toast「已保存」）、测试（实测 toast「测试通过」）、删除二次确认
- [x] Key 用 password 输入框，只显示「已保存 …1234（留空不改）」
- [x] 测试 / 后台刷新不再清空未保存输入（`state.dirty` 保护，Key 不会丢）
- [x] 深色 / 浅色主题均已目检

### 约束
- [x] 未构建、未装机、未 push、未改 `VERSION`
- [x] 未改 Claude / Codex / OpenCode 配置
- [x] 未触碰 `skills/`、`skills_workshop/` 业务逻辑
- [x] 测试只写临时目录（`AGENTFLOAT_LLM_USAGE`），不读写用户 `config.json`

## 二、自动化测试

```
.venv\Scripts\python -m pytest tests/test_llm_service.py tests/test_llm_api.py -q
# 53 passed（service 43 + api 10；含审查修复新增 14 项）

.venv\Scripts\python -m pytest tests/test_news_worker.py tests/test_ai_service_pure.py -q
# 12 passed（新增 5 项：AI 通道回退 / Skills 翻译回退）
```

回归抽查（含既有模块）：

```
.venv\Scripts\python -m pytest tests/test_llm_service.py tests/test_llm_api.py \
  tests/test_config.py tests/test_server_api.py tests/test_news_worker.py \
  tests/test_ai_service_pure.py tests/test_news.py tests/test_news_v2.py \
  tests/test_news_v3.py tests/test_skills.py -q
# 146 passed
```

静态检查：

```
node --check web/js/llm.js      # 0
.venv\Scripts\python -m pyflakes src/agentfloat/services/llm.py \
  src/agentfloat/services/news/worker.py src/agentfloat/services/skills/ai_service.py \
  tests/test_llm_service.py tests/test_llm_api.py tests/test_news_worker.py \
  tests/test_ai_service_pure.py   # 0
```

覆盖要点：迁移（只一次 / 不复活 / deleted_ids 兜底）、CRUD、激活回退、草稿测试（无 id）、
Key 脱敏（尾 4 位 / env 回退）、估算 tokens、金额/订阅余额解析、`file://` 拒绝、
缓存、并行汇总、币种未知归 OTHER、跨日/跨月统计、recent 全量、坏行容错、API 全链路、
LLM 失败回退 CLI Agent（worker + ai_service）。

## 三、浏览器冒烟（mock API，未连真实网络）

临时目录 `%TEMP%\opencode\llm-smoke`（不在仓库内）起了 mock 服务，静态托管真实 `web/`，
用 Playwright 走完：

1. 打开页面 → 汇总 `¥12.40 / $3.20`、`51.2K`、`1.24M`、订阅 `1 个` 正确渲染，控制台 0 error
2. 点 OpenRouter 卡片「切换」→ 卡片变「当前使用」，DeepSeek 回到「切换」，toast「已切换到：OpenRouter」
3. 点「+ 添加供应商」→ 选预设 OpenCode Go → Base URL / 模型 / 类型 / 余额接口自动填充，
   余额接口置灰，提示「只读 rolling / weekly / monthly 百分比」
4. 保存 → toast「已保存」，列表出现新卡片
5. 测试 → toast「测试通过：OK（9 tokens）」
6. 深色主题截图确认层级、对比度正常

截图（临时产物，仓库外）：
`%TEMP%\opencode\llm-smoke\llm-dark.png`、`llm-final.png`、`llm-after-switch.png`

## 四、未做 / 风险（如实列出）

- 未与真实 DeepSeek / OpenRouter / OpenCode Go 端点联调；余额字段按既有 `api_monitor`
  模板与官方返回结构实现，真实环境仍建议手动点一次「刷新余额」。
- 未做 Qt 端 LLM 设置（BRIEF 明确非目标）。
- 订阅型只读 `usage.rolling/weekly/monthly.percent`；若 OpenCode Go 改字段，需同步
  `_parse_sub_percent`。
- 同名新建供应商会得到 `-2` 后缀 id（沿用 `_new_id` 规则），页面允许同名多份。
- 保存不校验 Base URL 是否真的 OpenAI 兼容，只有「测试」会暴露；这是刻意的低门槛设计。
- 本机存在用户级 `OPENCODE_GO_API_KEY`（注册表兜底），订阅余额测试已用 monkeypatch 隔离，
  不会误连真实接口。
- **本轮未复跑浏览器冒烟**：`state.dirty` 改动只做了 `node --check` 与代码走查，P1-2 建议用
  真服务 + mock `_http_json` 在 Chromium 里复测（「填 Key → 测试 → 输入框仍保留 → 保存时带新 Key」）。
- `has_active_provider` 改严后，「只有 Key 没填 / env 未设置」的供应商不再自动成为 active，
  页面「当前使用」可能为空，这属于刻意行为（此时走 CLI Agent）。

## 五、REVIEW（BLOCK）修复记录 · 2026-11-02 第二轮

| 编号 | 问题 | 修复 | 测试 |
|---|---|---|---|
| P0-1 | 删除供应商后被迁移逻辑复活并重新 active | `normalize_config` 只迁移一次（`llm.migrated_from_api_monitor`）；删除时写标记 + `deleted_ids` 兜底跳过；`upsert` 也关闭迁移 | `test_normalize_migration_runs_only_once`、`test_normalize_does_not_revive_deleted_id_without_flag`、`test_normalize_legacy_with_providers_does_not_derive_after_delete`、`test_delete_does_not_revive_migrated_provider` |
| P1-1 | 新供应商「测试」必然 400 | `test_provider()` 先 `_normalize_provider(candidate)` 补 id / 预设默认值，再放进临时 config | `test_test_provider_draft_without_id`、`test_test_endpoint_accepts_unsaved_draft` |
| P1-2 | 测试后草稿被重置、Key 丢失 | `web/js/llm.js` 增加 `state.dirty`；`load()` 仅在未改动（或草稿 id 消失）时重建 draft | 代码走查 + `node --check`（未跑浏览器冒烟，见上） |
| P1-3 | `has_active_provider` 不查 Key；LLM 失败不回退 CLI Agent | 增加 Key 可解析判断；`upsert` 不再自动激活无 Key 供应商；`normalize` 只把有 Key 的设为 active；`news/worker.py` 抽 `generate_ai_with_fallback` 回退 Agent；`skills/ai_service.py` 翻译失败回退 `_run_headless` 并记 warning | `test_has_active_provider_requires_usable_key`、`test_upsert_does_not_auto_activate_keyless_provider`、`test_generate_ai_with_fallback_*`（4 项）、`test_run_services_falls_back_to_agent_when_llm_fails`、`test_saved_provider_without_key_is_not_active` |
| P1-4 | `balance_url` 无协议校验，`file://` 可读本地文件 | `validate_provider` 增加 scheme 白名单；`fetch_balance` / `_http_json` 双层 `_require_http_url`，错误信息只说「仅允许 http/https」 | `test_balance_url_scheme_is_validated`、`test_fetch_balance_rejects_file_url_without_leaking` |
| P1-5 | `.gitignore` 未覆盖 `config.json*` | 增加 `config.json*` / `launcher_config.json*` | — |
| P2-1 | 总余额币种兜底硬写 CNY | 币种未知归 `OTHER`，不再默认人民币 | `test_summarize_balances_unknown_currency_is_not_cny` |
| P2-2 | 分用途统计口径与文案不一致 | 后端 `by_purpose` 明确为累计口径、`recent` 不再只看今天；前端标签改「AI 快报·累计 / Skills 翻译·累计」，recent 显示 月-日 时间 | `test_summarize_usage_recent_includes_past_days` |
| P2-6 | env Key 场景显示「未配置 Key」 | `mask_provider` 走与 `fetch_balance` 相同的 env 回退；提示只留尾 4 位 | `test_mask_provider_uses_env_fallback` |

未修（本轮范围外，保留在 REVIEW 里）：P2-3 用量文件轮转 / 首屏等余额、P2-4 `/api/config` 明文 Key、P2-5 余额错误展示。

## 六、改动文件

| 文件 | 说明 |
|---|---|
| `src/agentfloat/services/llm.py` | 新：供应商 CRUD / 激活 / chat / 测试 / 金额+订阅余额 / Token 统计（已清理未用 `uuid` 导入） |
| `src/agentfloat/webshell/server.py` | `/api/llm/*` 路由（本次核对无缺口，未改） |
| `web/js/llm.js` | 新：「AI 接入」页渲染与交互 |
| `web/js/app.js` | 导航/标题/页面分支接入 `llm` |
| `web/css/style.css` | 新增 `.llm-*` 样式（卡片 / 汇总 / 编辑区 / 响应式 / 深色） |
| `tests/test_llm_service.py` | 服务层 43 项（新增迁移只一次 / 草稿测试 / Key / file:// / 币种 / recent） |
| `tests/test_llm_api.py` | API 10 项（新增删除不复活 / 草稿测试 / 无 Key 不激活） |
| `tests/test_news_worker.py` | 新增 4 项：`generate_ai_with_fallback` 通道选择与回退 |
| `tests/test_ai_service_pure.py` | 新增 1 项：Skills 翻译 LLM 失败回退 CLI Agent |
| `.gitignore` | 新增 `config.json*` / `launcher_config.json*`（防止密钥备份入库） |
| `src/agentfloat/services/news/worker.py` | AI 通道选择抽 `generate_ai_with_fallback`，LLM 失败回退 Agent |
| `src/agentfloat/services/skills/ai_service.py` | Skills 翻译 LLM 失败回退 `_run_headless` 并记 warning |
