# Agent 支持矩阵（调研中 v0.1）

> 目标：为「Agent 检测 / 一键启动 / 安装」提供唯一事实来源。
> 规则：**只写核实过的事实**；未核实的行标「待核实」，不写猜测的命令。
> 核实方式：① 本机探测（`where` / `--version` / 官方文档页）；② 官方文档（记录 URL 与核对日期）。

## 字段定义

| 字段 | 含义 |
|---|---|
| 启动命令 | 可执行名（PATH 可发现）或常见安装路径 |
| launcher | `cli`（可 headless）/ `app`（GUI）/ `web`（网页）——决定能否给快报 AI 摘要复用 |
| 常用参数 | 默认启动参数、`--version`、工作目录、模型/profile 参数 |
| 危险参数 | 会关闭用户会话 / 强制退出 / 清空数据的参数（启动器需过滤） |
| 安装方式 | 包管理器 / 官方脚本 / 安装包（含静默参数） |
| 版本检测 | 能打印版本号的命令 |
| 卸载 | 卸载命令或安装包卸载入口 |
| 核实日期 | 最后核对日期 + 来源 |

## 已核实（2026-10-26 · npm registry 实测 + 本机探测）

| Agent | 启动命令 | npm 包 | 最新版本 | 安装命令 | 核实方式 |
|---|---|---|---|---|---|
| OpenCode CLI | `opencode` | `@opencode/cli` | **2.0.18**（本机已装） | `npm i -g @opencode/cli` | 本机 `--version` + `npm ls -g` |
| Claude Code | `claude` | `@anthropic-ai/claude-code` | **2.1.310** | `npm i -g @anthropic-ai/claude-code` | `npm view` bin/version |
| OpenAI Codex CLI | `codex` | `@openai/codex` | **0.164.0** | `npm i -g @openai/codex` | `npm view` bin/version |
| Gemini CLI | `gemini` | `@google/gemini-cli` | **0.65.0** | `npm i -g @google/gemini-cli` | `npm view` bin/version（`@google/gemini` 为 404，确认包名） |
| Qwen Code | `qwen` | `@qwen-code/qwen-code` | **0.26.1** | `npm i -g @qwen-code/qwen-code` | `npm view` bin/version |

> 以上 5 个都走 npm 全局安装、二进制名即启动命令；四家官方文档的 **headless 参数**（供快报 AI 摘要复用）仍待核实，验证方法：安装后跑 `<cmd> --help`，或 `npx -y <pkg> --help`。
> 本机未安装（正好用于验证「未装 → 检测 → 安装」链路）：claude / codex / gemini / aider / qwen。

### 下一批待核实

| Agent | 包管理器 | 待补 |
|---|---|---|
| Aider | pip / pipx（`aider-chat`） | 版本、启动名、`--message` 非交互参数 |
| Kimi CLI | 待定 | 包名与安装方式 |
| Goose | 待定 | 包名与安装方式 |
| Cursor Agent | 待定 | 是否有独立 CLI |
| Cline / Roo Code | VS Code 扩展 | 是否能 CLI 化（可能只能检测 GUI） |

## 候选清单（待核实，按优先级）

| # | Agent | 类型 | 要核实的三件事 | 官方文档（待核） |
|---|---|---|---|---|
| 1 | Claude Code | cli | 启动/`-p` 非交互参数/安装脚本 | Anthropic 文档（待补 URL） |
| 2 | OpenAI Codex CLI | cli | 启动/`exec` 非交互参数/npm 安装 | GitHub openai/codex（待补） |
| 3 | Gemini CLI | cli | 启动/`-p` 参数/npm 安装 | GitHub google-gemini/gemini-cli（待补） |
| 4 | Qwen Code | cli | 启动/非交互/安装 | GitHub QwenLM/qwen-code（待补） |
| 5 | Kimi CLI | cli | 启动/安装 | Moonshot 文档（待补） |
| 6 | Aider | cli | 启动/`--message` 非交互/pipx 安装 | aider.chat（待补） |
| 7 | Goose | cli | 启动/安装 | block/goose（待补） |
| 8 | Cline / Roo Code | app（VS Code 扩展） | 是否能 CLI 化 | 扩展市场页（待补） |
| 9 | Cursor Agent | cli | 启动/安装 | Cursor 文档（待补） |

## 调研判定标准（落库前必过）

1. **启动**：能在干净 PATH 下用一行命令起来，且失败信息可判读
2. **headless**：能非交互执行一次问答并退出（供快报摘要 / 自动任务）
3. **安装**：静默安装可复现（winget 或官方脚本），失败有明确退出码
4. **危险参数**：确认不会 `kill` 用户正在使用的 GUI 进程（v3.11.0 的教训）
5. **可卸载**：能找到官方卸载方式，避免残留

## 下一步

1. 逐批抓官方文档，补齐上表（每批 3-5 个，附 URL + 日期）
2. 把核实结果落成 `services/catalog/` 可用的数据（内置 + 远程 Registry）
3. 用 2-3 个真实 Agent 跑通「检测 → 一键启动 → 安装」闭环


## 全链路隔离测试结果（2026-10-26）

方式：`npm install --prefix %TEMP%\af-e2e\<agent>`（独立缓存）→ 该前缀下 `--version` → headless 一条 → `npm uninstall` + 删目录；aider 用临时 venv。
全程静默（CREATE_NO_WINDOW），测完删除，未污染全局。

| Agent | 安装 | 检查（版本） | headless | 卸载/清理 | 耗时 |
|---|---|---|---|---|---|
| OpenCode | ✅ | 2.1.4（registry 最新；本机装的是 2.0.18） | 未测（无已核实参数） | ✅ | 30s |
| Claude Code | ✅ | 2.1.310 | 启动成功，提示需登录/密钥 | ✅ | 21s |
| Codex CLI | ✅ | 0.164.0 | 启动成功并读到 prompt，API 返回 **401 需登录**；非 git 目录需 `--skip-git-repo-check` | ✅ | 24s |
| Gemini CLI | ✅ | 0.65.0 | 需登录/密钥 | ✅ | 100s |
| Qwen Code | ✅ | 0.26.1 | 未测（无已核实参数） | ✅ | 17s |
| Aider | ❌ | — | — | ✅ | 94s |

### 结论与待办

1. **安装/检测/卸载/清理 4 段链路可用**（5/6 全绿）：npm 前缀隔离方案成立，可直接作为安装适配器的实现基线。
2. **headless 需鉴权**：claude / codex / gemini 都能启动并读到提示词，缺的是登录态；UI 要能把「未登录」与「启动失败」区分开。
3. **aider 安装失败**：全新 venv 缺 `setuptools`，`aider-chat` 需要源码构建（`BackendUnavailable: Cannot import 'setuptools.build_meta'`）→ 安装适配器走 pip 时必须先 `pip install setuptools wheel`，或改用 pipx。
4. **版本漂移**：opencode registry 最新 2.1.4，本机 2.0.18 → 目录不锁版本，UI 可提示「有更新」。
5. **codex 细节**：非 git 目录要加 `--skip-git-repo-check`，应写进安装/启动参数模板。
