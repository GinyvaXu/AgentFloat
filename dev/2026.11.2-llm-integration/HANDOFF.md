# HANDOFF · LLM 接入

- 状态：**REVIEW(BLOCK) 已修完，待复跑浏览器冒烟 + 用户验收**（2026-11-02 第二轮）
- 已完成：
  - 设计预览 `docs/previews/LLM接入-ccswitch风格-20261102.html`（已确认）
  - 服务层 `src/agentfloat/services/llm.py`：供应商 CRUD/激活/chat/测试；金额型 + 订阅型余额；Token 统计
  - API `src/agentfloat/webshell/server.py`：`/api/llm/providers|test|refresh|usage`
  - Web：`web/js/llm.js`（新）、`web/js/app.js`（导航接入）、`web/css/style.css`（`.llm-*`）
  - 测试：`tests/test_llm_service.py`（43）、`tests/test_llm_api.py`（10）、
    `tests/test_news_worker.py`（7，含回退 4 项）、`tests/test_ai_service_pure.py`（5，含回退 1 项）
  - 审查修复（详见 `QA.md` 第五节 / `REVIEW.md`）：
    - P0：迁移只执行一次（`llm.migrated_from_api_monitor`）+ `deleted_ids` 兜底，删除后不再复活/重新 active
    - P1-1：`test_provider()` 先归一化草稿，未保存（无 id）的新供应商可直接测试且不落盘
    - P1-2：`web/js/llm.js` 加 `state.dirty`，测试/后台刷新不再清空草稿与刚输入的 Key
    - P1-3：`has_active_provider` 要求 Key 可解析；`upsert`/`normalize` 不自动激活无 Key 供应商；
      AI 快报与 Skills 翻译在 LLM 失败时回退 CLI Agent（worker 抽 `generate_ai_with_fallback`）
    - P1-4：`balance_url` 只允许 http/https（`validate_provider` + `_http_json` 双层），错误不回显内容
    - P1-5：`.gitignore` 加 `config.json*` / `launcher_config.json*`
    - P2：Key 提示只留尾 4 位 + env 回退（不再显示「未配置 Key」）、币种未知归 `OTHER`、
      分用途统计标「累计」且 recent 不再只看今天
- 下一步（按顺序）：
  1. 复跑浏览器冒烟（**必须用真服务 + mock `_http_json`**，不要用恒返回 ok 的 mock 路由），
     重点验「填 Key → 测试 → 输入框仍在 → 保存带新 Key」「删除后卡片不回来」
  2. 用户验收：`QA.md` 第一节清单勾选
  3. 验收通过后由 lead 决定构建 / 装机 / CHANGELOG / VERSION（本轮未动 VERSION、未 build、未装机）
- 关键路径：
  - 服务：`src/agentfloat/services/llm.py`
  - 回退：`src/agentfloat/services/news/worker.py`（`generate_ai_with_fallback`）、
    `src/agentfloat/services/skills/ai_service.py`（`run_services` skills 分支）
  - 路由：`src/agentfloat/webshell/server.py`（搜 `v3.28`）
  - 页面：`web/js/llm.js` + `#page-llm`（`web/index.html`）
  - 用量文件：`config_dir()/llm_usage.jsonl`（可用 `AGENTFLOAT_LLM_USAGE` 覆盖）
- 注意：
  - 切换 active 只影响 AI 快报（`news/worker.py`）与 Skills 翻译（`skills/ai_service.py`）
  - 供应商没有可用 Key 时 active 可能为空（刻意），此时走 CLI Agent
  - 订阅型固定 `GET https://opencode.ai/zen/go/v1/usage`，只读 percent，不进总余额
  - Key 只在 `config.json`；接口只回 `api_key_set` / 尾 4 位；测试用临时目录
  - 本机注册表可能有 `OPENCODE_GO_API_KEY`，写测试要 monkeypatch 隔离
  - 仍未修（范围外）：P2-3 用量文件轮转 / 首屏等余额、P2-4 `/api/config` 明文 Key、P2-5 余额错误展示

## 2026-11-02 交付
- 4.0.0 已构建并本地安装；af-mcp.exe 与内置 skills 已进安装包
- 审查 P0/P1 已修（删除不复活、草稿测试、失败回退 CLI、余额 URL 协议、.gitignore）
- 未做：真实端点联调、LLM 页面浏览器复测（修复后）、P2 残留
- 未 tag / 未 Release / 未 push
