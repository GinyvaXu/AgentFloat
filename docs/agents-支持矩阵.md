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

## 已核实（本机 2026-10-26）

| Agent | 启动命令 | launcher | 版本检测 | 安装方式 | 核实 |
|---|---|---|---|---|---|
| OpenCode（CLI） | `opencode` | cli | 待补（`opencode --version` 未跑） | 已在本机 npm 全局目录（`%APPDATA%\npm\opencode.ps1`） | 本机 PATH 探测 |

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
