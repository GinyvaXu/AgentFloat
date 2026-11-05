# BRIEF · AI 模型接入 + 余额监控 + Token 统计

- 日期：2026-11-02
- 模式：Standard（lead + builder + reviewer）
- 目标：AgentFloat 4.0 前完成统一 AI 供应商配置、余额/订阅用量展示、Token 统计，供 AI 快报与 Skills 翻译使用。

## 用户已确认的决策

1. 统一 AI 配置：Base URL / Key / Model / 测试；默认复用余额监控端点，可手填覆盖。
2. 一键切换供应商；只影响 AI 快报与 Skills 翻译，不改 Claude/Codex 配置。
3. 余额监控并入同一界面：
   - 金额型（DeepSeek /user/balance、OpenRouter credits）
   - 订阅型 OpenCode Go：GET https://opencode.ai/zen/go/v1/usage，Bearer {{env:OPENCODE_GO_API_KEY}}，rolling/weekly/monthly.percent（已用百分比，只读，不计入总余额）
4. Token 统计：今日 / 本月 / 分用途（news/translate/test）、最近调用；无 usage 字段按字符估算并标记。
5. 设计参考 docs/previews/LLM接入-ccswitch风格-20261102.html（已确认，卡片 + 右侧编辑 + 顶部汇总）。
6. 设置界面落在 Web 端；不得破坏现有 API 用量页与 Skills 页。

## 非目标

- 本地路由 / 协议转换 / 故障转移
- 修改 Claude/Codex/OpenCode 的配置文件
- 云端同步
- 本次不做 Qt 端 LLM 设置

## 验收

- 供应商 CRUD、active 切换、测试、金额/订阅余额解析
- `services/llm.chat()` 可被 AI 快报 / Skills 翻译调用并记录 usage
- Web 新页面/设置区可操作，密钥不回显、不写日志
- 新增测试通过；不依赖真实网络

## 受影响文件（建议）

- src/agentfloat/services/llm.py（新）
- src/agentfloat/webshell/{handlers,server}.py
- web/js/app.js、web/css/style.css、web/index.html
- tests/test_llm_*.py
