# AgentFloat × ProjectDock 深度联动方案（精简版）

> v0.2 · 2026-09-29 · 两轮交互问卷（12 项决策）已完成，结论见 §7
> 涉及版本：AgentFloat v3.3.1（主要实施方）· ProjectDock v1.7.0（服务方）
> 状态：决策已确认 ✅ · ⏸ 暂停中 —— 等待 AgentFloat 新版功能更新后重新制定

---

## 1. 一句话方案

把 ProjectDock 变成浮球的「项目大脑」：轮盘新增**「项目坞」**（双页签：项目 / 动态）——一键在**项目目录**启动 Agent、一键交办 AI 任务、任务完成/失败实时提醒；全部复用两边现成的本地 HTTP API，P1 不引入新组件、不改 ProjectDock 代码。

### 目标场景（问卷确认）

| # | 场景 | 说明 | 阶段 |
|---|------|------|------|
| S1 | 项目遥控器 | 浮球 → 项目坞 → 选项目 → 终端启动 Agent（cwd=项目目录）/ 交办任务 | P1 |
| S2 | 任务监视器 | 运行中角标、完成/失败托盘气泡（带结果摘要）；「动态」页签看活动流 | P1 |
| S3 | 快捷指令台 | P1 轻量交办（输入 + 完成通知）→ P2 完整流式 + `pdchoice` 回传 | P1/P2 |
| S4 | 状态感知彩蛋 | 异常角标 / 快报「项目进展」/ 托盘直达总控台 | P3 |

> 痛点校准（问卷）：**任务完成无感知 / 两个软件来回切 / 项目状态不直观** → 监视与状态信息前置到 P1（项目行的版本/合规/运行中/最近活动 + 动态页签）。

---

## 2. 现状底盘（已核实）

两边同栈（Python + FastAPI + 本地 HTTP），且 AgentFloat 已在视觉与流程上对齐 ProjectDock（AGENTS.md 契约、`logs/ai` 日志、主题 token）——联动属于既有关系的自然延伸。

**通道结论：浮球 → ProjectDock 全通（HTTP `127.0.0.1:8765`）；反向暂时不通**（浮球端口动态 3087–3098 且无端口文件；ProjectDock 无出站、无通知、无托盘）。

ProjectDock 既有接口（本方案全部直接复用，P1 不改其后端）：

| 用途 | 接口 |
|------|------|
| 探活/版本 | `GET /api/health` → `{ok, app, version, root}` |
| 项目列表 | `GET /api/projects` → `id`(文件夹名)/`title`/`type`/`path`/`version`/`has_git`/`compliant`/`pinned` |
| 任务列表 | `GET /api/jobs?limit=` → `{id,label,status(running/done/error),error,exit_code,started_at}` |
| 跨项目聚合 | `GET /api/console` → `activity[]`（含 project/project_title/ts/result/action）+ `running_jobs[]` + `failed_count` + `projects[]` |
| 发起 AI 任务 | `POST /api/agent/run` `{project_id,prompt,agent?,history?}` → `{job_id,...}` |
| 任务输出流 | `GET /api/jobs/{id}/stream`（SSE：status/line/chunk/end）|
| 写 AI 日志 | `POST /api/projects/{pid}/ai-logs` `{agent,action,result,summary,details,source}` |
| 读 AI 日志 | `GET /api/projects/{pid}/ai-logs?limit=`（结果摘要来源）|
| 打开目录 | `POST /api/projects/{pid}/open` |
| 默认后端 | `GET /api/settings` → `agent`（默认 pi）|

必须绕开的既有约束（设计已针对处理）：

1. **无通知/无出站** → 提醒由浮球轮询驱动（P3 才按需评估反向）。
2. **SSE 单消费者、不可回放** → P1 轻量交办**不消费 SSE**（ProjectDock 窗口可正常观看）；P2 完整流式面板改为浮球消费（届时约定）。
3. **浮球 launch API 只认 Agent id** → 终端启动走浮球内部 `launch_agent(agent, config, cwd_override=项目路径)`；交办走 `/api/agent/run`。
4. **浮球配置 PUT 有键白名单** → 新增 `projectdock` 配置段必须同步进 `apply_settings()` 白名单，否则改了不生效。
5. **两边 API 无鉴权**（仅绑 127.0.0.1）→ 问卷确认：现状即可，P3 评估 token 硬化。

---

## 3. 总体蓝图（分层递进）

```
L0 探测与降级   浮球探测 ProjectDock 存活；离线 → 面板离线态 + 一键启动；全程静默降级
L1 项目坞      轮盘扇区「项目坞」→ 双页签面板：「项目」列表 + 「动态」监视
L2 启动双通道   终端启动（cwd=项目目录）｜ 交办任务（/api/agent/run，轻量输入+完成通知）
L3 提醒        轮询 jobs + console：运行中角标、完成/失败气泡（带结果摘要）
L4 进阶        P2 指令台（流式 + pdchoice）；P3 彩蛋（快报日报 / 异常角标 / 托盘直达）
```

---

## 4. P1 · MVP 详细设计（闭环 + 监视面板）

### 4.1 数据流

1. **探测**：浮球启动后 `ProjectDockWatcher` 每 10s `GET /api/health`；未运行时面板显示离线态，提供「启动 ProjectDock」按钮（探测 `%LOCALAPPDATA%\Programs\ProjectDock\ProjectDock_v*.exe` 取最新，或配置 `exe_path`）。
2. **项目坞 ·「项目」页签**：`GET /api/projects` 拉列表（缓存 + 手动刷新）。每行：logo + 标题 + 类型章 + 版本 + 合规点 + 运行中小点 + 最近活动时间；置顶分区、搜索。行操作：
   - 终端启动主 Agent（默认浮球主 Agent，子菜单可换）
   - 交办任务（轻量输入框）
   - 打开项目目录（`POST /api/projects/{pid}/open`）
   - 打开 ProjectDock（浏览器打开 `base_url`）
3. **项目坞 ·「动态」页签**：`GET /api/console`（10s）显示最近活动流（项目名/结果/摘要/时间）、运行中任务、失败计数。
4. **终端启动**：`launch_agent(agent, config, cwd_override=项目路径)`（wt 优先，cmd 回退——沿用现有链路）。
5. **交办任务（轻量）**：输入框 → `POST /api/agent/run {project_id, prompt}`（agent 默认跟随 ProjectDock 设置 `GET /api/settings.agent`，可切换）→ 立即 toast「已交办」→ 不消费 SSE，想看过程点「打开 ProjectDock」。
6. **监视与提醒**：`GET /api/jobs?limit=30` 每 5s 按 id 差分，追踪 running→done/error（首次拉取只建基线不提醒）；`GET /api/console` 每 30s 补充 CLI/外部任务（不在内存 job 里，靠 activity 新条目发现）。完成 → 信息级气泡；失败 → 警告级；**通知带结果摘要**（任务结束后读该项目最新 `ai-logs.summary`，取不到则降级为「(摘要不可用)」）。浮球右下角角标常显运行中任务数（复用 ApiBalanceBadge 结构）。
7. **可选落痕**：终端启动时可写 `POST /api/projects/{pid}/ai-logs`（`log_launches`，**默认关**，保持日志干净）。

### 4.2 AgentFloat 侧改动清单

| 文件 | 改动 |
|------|------|
| `src/agentfloat/services/projectdock/__init__.py` | 新子包 |
| `.../client.py` | HTTP 客户端（urllib，零新依赖；超时 3s；连接失败抛 `ProjectDockOffline` 静默降级）：health / projects / jobs / console / run_agent / latest_log / write_log / open_project |
| `.../watcher.py` | `ProjectDockWatcher(QThread)`：轮询 + 信号（connection_changed / projects_updated / jobs_updated / task_finished / task_failed / activity_updated）；差分与去重在新线程内完成 |
| `.../badge.py` | `TaskCountBadge`（复用 `api_monitor/badge.py` 结构，右下角）|
| `ui/panels/project_dock.py` | `ProjectDockPanel`（SkillsPanel 同构：FadePanelMixin + panel_style）：QTabWidget 双页签（项目 / 动态）；项目行自定义 ItemWidget；交办输入行；搜索框；离线态 |
| `core/launcher.py` | `launch_agent(agent, config, cwd_override=None)`（一个参数） |
| `ui/floatball.py` | `_radial_item_for` 增加 `"projectdock"`；`_on_radial_action` 增加分发；`_open_projectdock_panel()` + 面板引用清理 |
| `app.py` | 启动 watcher、接线托盘气泡/角标、`_shutdown` 停止线程；托盘菜单加「项目坞」 |
| `core/config.py` + `web/` 设置页 | 默认配置段 + `apply_settings()` 白名单 + 设置页「ProjectDock 联动」分组 |
| `tests/` | client（mock HTTP）、任务差分/去重、面板冒烟、配置白名单 |

配置段（默认值）：

```json
"projectdock": {
  "enabled": true,
  "base_url": "http://127.0.0.1:8765",
  "default_agent": "",
  "exe_path": "",
  "poll_jobs_seconds": 5,
  "poll_console_seconds": 30,
  "notify_done": true,
  "notify_fail": true,
  "notify_summary": true,
  "log_launches": false
}
```

### 4.3 ProjectDock 侧改动

**无。** P1 全部复用既有 API —— 这是本方案「精简」的核心：种子功能只改一侧。

### 4.4 边界与降级

- ProjectDock 未装/未启动：面板离线态 + 一键启动；浮球其余功能不受影响。
- ProjectDock 重启：job 内存清零 → 提醒以 console/activity（磁盘日志）为准继续；无法补摘要时降级提示。
- 去重：job 按 id、活动按 `project+ts`，重启浮球不重复提醒（基线重建）。
- 版本门槛：`health.version < 1.7.0` 或端点缺失时面板提示（本方案所需端点 1.7.0 全部具备）。
- 成本：回环轮询两三个小 JSON/5s，可忽略。

### 4.5 验收清单（P1）

- [ ] 项目坞双页签正常：「项目」与 ProjectDock 一致（含版本/合规/最近活动）；「动态」显示活动流与运行中任务
- [ ] 断线显示离线态，一键启动 ProjectDock 后自动恢复
- [ ] 终端启动的 Agent 工作目录 = 项目根（`pwd` 验证）；交互体验与现状一致
- [ ] 交办任务后：ProjectDock 窗口可看流式输出，浮球角标计数正确
- [ ] 任务完成：≤10s 气泡提醒且带结果摘要；失败为警告级；重复提醒为 0
- [ ] 浮球 pytest 全绿（含新增用例）；ProjectDock 无回归（无改动）
- [ ] PyInstaller 打包冒烟通过（新子包正常收包）

---

## 5. P2 · 指令台（完整形态）

- 项目行动作「发指令」升级：预设指令 chips（按类型，可配置）+ 自由输入 + 会话延续。
- `POST /api/agent/run`（`history` 由浮球自持，会话存 `%APPDATA%\AgentFloat\projectdock_sessions.json`）。
- 浮球面板消费 `GET /api/jobs/{id}/stream`：显示流式输出 + `end` 后结果摘要。
- `pdchoice` 选择卡片：从流式输出识别 ```pdchoice``` JSON → 渲染可点按钮 → 点击以「我选择：X」续轮。
- 约定：浮球发起的任务输出只由浮球面板消费（SSE 单消费者）；ProjectDock 总控台仍能看到任务时间线。
- 改动仍集中在 AgentFloat（ProjectDock 零改动）。

## 6. P3 · 彩蛋与增强（问卷已选 ✅ 为选定项）

| 项 | 做法 | 状态 |
|----|------|------|
| 快报「项目进展」 | news 模块新增数据源：读各项目 `logs/ai` 近 24h，生成「昨天各项目干了什么」板块 | ✅ 已选 |
| 异常角标 | console 数据里 `compliant=false` / `failed_count>0` → 浮球角标轻度提醒 | ✅ 已选 |
| 托盘直达 | 托盘菜单「打开 ProjectDock 总控台」→ `webbrowser.open(base_url)` | ✅ 已选 |
| 秒级双向通知 | 浮球写端口文件 + `POST /api/notify`；ProjectDock 任务结束回调浮球（按需再做）| 候选 |
| 安全硬化 | 共享 token 文件 + 两边校验（按需）| 候选 |
| 任务进度贴片 | 浮球旁环形进度 | ✖ 已排除 |

---

## 7. 决策拍板表（交互问卷 · 已确认 ✅）

| # | 问题 | 最终决策 |
|---|------|----------|
| 1 | 主场景 | 项目遥控器 + 任务监视器 + 快捷指令台（三选全中）|
| 2 | 痛点校准 | 任务无感知 / 来回切 / 状态不直观 → 监视与状态前置到 P1 |
| 3 | 架构方向 | 浮球单向调用 ProjectDock（双向留 P3 候选）|
| 4 | 启动方式 | **双通道**：终端窗口 + 走 ProjectDock 链路（交办）|
| 5 | 交办形态（P1） | 轻量输入 + 完成通知（带摘要）；完整流式放 P2 |
| 6 | 通知 | 完成/失败气泡 + 运行中角标（含结果摘要）|
| 7 | 入口 | 轮盘「项目坞」扇区，双页签面板 |
| 8 | 监视布局 | 页签组合（项目 / 动态）|
| 9 | MVP 范围 | 闭环 + 监视面板（含轻量交办）|
| 10 | 依赖关系 | 各自独立、互相探测、优雅降级（浮球可一键拉起 PD）|
| 11 | 安全 | 现状（仅 127.0.0.1），P3 评估 token |
| 12 | 彩蛋 | 快报项目日报 + 异常角标 + 托盘直达（排除任务进度贴片）|

**明确不做（避免过度设计）**：不做文件监听/命名管道；不把浮球做成完整聊天客户端（与 ProjectDock 前端重复）；不做远程/局域网访问；任务进度贴片已排除；P1 不动 ProjectDock 代码。

---

## 8. 风险与规避

| 风险 | 规避 |
|------|------|
| 轮询延迟（5s / 30s）| 本地回环成本可忽略；P3 双向方案可升级秒级 |
| PD 重启丢 job 内存 | 提醒以磁盘 `logs/ai`（console）为准，id/ts 去重；摘要降级提示 |
| 无鉴权 API | 保持 127.0.0.1；P3 硬化选项；方案内已标注 |
| SSE 抢事件 | P1 交办不消费 SSE；P2 完整流式由浮球消费（约定） |
| 浮球配置白名单坑 | `projectdock` 键显式加入 `apply_settings()` + 单测 |
| 两侧版本漂移 | `health.version` 门槛 + 面板提示；所需 API 均为既有稳定端点 |

---

## 9. 里程碑（估算）

| 阶段 | 内容 | 预估 | 目标版本 |
|------|------|------|----------|
| P1 | 项目坞双页签 + 终端启动 + 轻量交办 + 任务提醒 | 2–2.5 天（浮球侧）| AgentFloat v3.4.0 |
| P2 | 指令台（流式 + pdchoice + 会话）| 1–1.5 天 | AgentFloat v3.5.0 |
| P3 | 快报日报 / 异常角标 / 托盘直达（+按需：双向通知 / 硬化）| ~1 天 | AgentFloat v3.6.x |

流程遵循两边 AGENTS.md：**先备份 → 实现 → 测试 → CHANGELOG/VERSION → 归档 → 写 AI 日志**。

---

## 附：本轮核实来源

- AgentFloat：`webshell/server.py`（20 端点）、`core/launcher.py`、`ui/floatball.py`（轮盘分发 L1223–1288）、`config.example.json`、`AGENTS.md`
- ProjectDock：`api.py`（60 路由，L750–862）、`runner.py`（Job 结构 L14–22、list L145–152）、`console.py`、`models.py`（AgentRun / AILogCreate）

*本文档为已确认决策的方案稿；实现前再拆解为任务清单（update_plan）。*

*⏸ 2026-09-29 15:33 起暂停：等待 AgentFloat 新版功能上线后，核对差异并重新制定（v0.3）。*
