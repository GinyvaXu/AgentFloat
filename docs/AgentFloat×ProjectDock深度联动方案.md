# AgentFloat × ProjectDock 深度联动方案（精简版）

> v0.1 草案 · 2026-09-29 · 编写：opencode
> 涉及版本：AgentFloat v3.3.1（主要实施方）· ProjectDock v1.7.0（服务方）
> 状态：待确认「决策拍板表」（§7）后进入实现拆解

---

## 1. 一句话方案

把 ProjectDock 变成浮球的「项目大脑」：轮盘新增**「项目坞」**——直接列出全部项目，一键在**项目目录**启动 Agent、一键发 AI 指令、任务完成/失败实时提醒；全部复用两边现成的本地 HTTP API，不引入新组件、不改变两边架构。

### 目标场景（按优先级）

| # | 场景 | 说明 |
|---|------|------|
| S1 | 项目遥控器 | 浮球 → 项目坞 → 选项目 → 在该项目目录启动 Agent（终端）|
| S2 | 任务监视器 | ProjectDock 的 AI 任务/构建：运行中、完成、失败，浮球角标 + 托盘气泡提醒 |
| S3 | 快捷指令台（P2）| 从浮球给项目发 AI 指令，面板看流式输出；`pdchoice` 选择卡片可点选回传 |
| S4 | 数据互认（P2/P3）| 浮球发起的操作写进 ProjectDock AI 日志/总控台；快报可含「项目进展」 |

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
| 打开目录 | `POST /api/projects/{pid}/open` |
| 默认后端 | `GET /api/settings` → `agent`（默认 pi）|

必须绕开的既有约束（设计已针对处理）：

1. **无通知/无出站** → S2 提醒由浮球轮询驱动（P3 才评估反向）。
2. **SSE 单消费者、不可回放** → 浮球发起的任务输出由浮球消费；ProjectDock 侧看总控台时间线即可。
3. **浮球 launch API 只认 Agent id** → 项目启动走浮球内部 `launch_agent(agent, config, cwd_override=项目路径)`，无需 HTTP 自调。
4. **浮球配置 PUT 有键白名单** → 新增 `projectdock` 配置段必须同步进 `apply_settings()` 白名单，否则改了不生效。
5. **两边 API 无鉴权**（仅绑 127.0.0.1）→ 本阶段接受，P3 评估 token 硬化。

---

## 3. 总体蓝图（分层递进）

```
L0 探测与降级   浮球探测 ProjectDock 存活；离线 → 面板离线态 + 一键启动；全程静默降级
L1 项目坞      轮盘扇区「项目坞」→ Qt 面板：项目列表（图标/类型/版本/置顶/搜索）
L2 任务监视    轮询 jobs + console：运行中角标、完成/失败托盘气泡
L3 指令台      项目发指令 + 流式输出 + pdchoice 回传（P2）；日志互通、快报进展、异常角标（P3）
```

---

## 4. P1 · MVP 详细设计（最小闭环）

### 4.1 数据流

1. **探测**：浮球启动后 `ProjectDockWatcher` 每 10s `GET /api/health`；未运行时面板显示离线态，提供「启动 ProjectDock」按钮（探测 `%LOCALAPPDATA%\Programs\ProjectDock\ProjectDock_v*.exe` 取最新，或配置 `exe_path`）。
2. **项目坞**：打开面板 → `GET /api/projects` 拉列表（缓存 + 手动刷新）；置顶项目置顶分区；支持搜索；（P2 起可按「最近活动」排序）。
3. **启动**：选项目 → 动作 = 启动主 Agent（默认浮球主 Agent）/ 启动其他 Agent / 打开项目目录 / 浏览器打开 ProjectDock。终端启动 `cwd = 项目路径`（wt 优先，cmd 回退——沿用现有链路）。
4. **监视**：`GET /api/jobs?limit=30` 每 5s：按 id 差集找新任务、追踪 running→done/error 转变（首次拉取只建基线不提醒，避免历史任务轰炸）；`GET /api/console` 每 30s 补充 CLI/外部任务（它们不在内存 job 里，靠 activity 新条目发现）。
5. **提醒**：完成 → 托盘气泡（信息级）；失败 → 警告级；浮球右下角角标常显运行中任务数（复用 ApiBalanceBadge 结构）。
6. **落痕**：从浮球启动 Agent 时 `POST /api/projects/{pid}/ai-logs`（agent="AgentFloat"，action="浮球启动 <Agent>"，source="external"）→ 总控台时间线可见（可配置关闭）。

### 4.2 AgentFloat 侧改动清单

| 文件 | 改动 |
|------|------|
| `src/agentfloat/services/projectdock/__init__.py` | 新子包 |
| `.../client.py` | HTTP 客户端（urllib，零新依赖；超时 3s；连接失败抛 `ProjectDockOffline` 静默降级）：health / projects / jobs / console / run_agent / write_log / open_project |
| `.../watcher.py` | `ProjectDockWatcher(QThread)`：轮询 + 信号（connection_changed / jobs_updated / task_finished / task_failed / activity_updated）；任务状态差分在新线程内完成 |
| `.../badge.py` | `TaskCountBadge`（复用 `api_monitor/badge.py` 结构，右下角）|
| `ui/panels/project_dock.py` | `ProjectDockPanel`（SkillsPanel 同构：FadePanelMixin + panel_style；行 = logo+标题+类型章+版本+运行中小点；搜索框；离线态） |
| `core/launcher.py` | `launch_agent(agent, config, cwd_override=None)`（一个参数） |
| `ui/floatball.py` | `_radial_item_for` 增加 `"projectdock"`；`_on_radial_action` 增加分发；`_open_projectdock_panel()` + 面板引用清理 |
| `app.py` | 启动 watcher、接线托盘气泡/角标、`_shutdown` 停止线程；托盘菜单加「项目坞」 |
| `core/config.py` + `web/` 设置页 | 默认配置段 + `apply_settings()` 白名单 + 设置页「ProjectDock 联动」分组 |
| `tests/` | client（mock HTTP）、任务差分逻辑、面板冒烟、配置白名单 |

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
  "log_launches": true
}
```

### 4.3 ProjectDock 侧改动

**无。** P1 全部复用既有 API —— 这是本方案「精简」的核心：种子功能只改一侧。

### 4.4 边界与降级

- ProjectDock 未装/未启动：面板离线态 + 一键启动；浮球其余功能不受影响。
- ProjectDock 重启：job 内存清零 → 提醒以 console/activity（磁盘日志）为准继续；按 id/ts 去重、不重复提醒。
- 版本门槛：`health.version < 1.7.0` 或端点缺失时面板提示（本方案所需端点 1.7.0 全部具备）。
- 成本：回环轮询两三个小 JSON/5s，可忽略。

### 4.5 验收清单（P1）

- [ ] 项目坞列表与 ProjectDock 一致；断线显示离线态，一键启动后自动恢复
- [ ] 从浮球启动的 Agent 工作目录 = 项目根（`pwd` 验证）；终端体验与现状一致
- [ ] ProjectDock UI 发起任务：完成后 ≤10s 浮球气泡提醒 + 角标数字变化；失败为警告级
- [ ] 启动动作在项目 `logs/ai/` 生成 external 日志（可关闭）
- [ ] 浮球 pytest 全绿（含新增用例）；ProjectDock 无回归（无改动）
- [ ] PyInstaller 打包冒烟通过（新子包正常收包）

---

## 5. P2 · 指令台（浮球轻量对话）

- 项目行动作新增「发指令」：预设指令 chips（按类型，可配置）+ 自由输入。
- `POST /api/agent/run`（`history` 由浮球自持，会话存 `%APPDATA%\AgentFloat\projectdock_sessions.json`）。
- 浮球面板消费 `GET /api/jobs/{id}/stream`：显示最近输出行 + `end` 后结果摘要。
- `pdchoice` 选择卡片：从流式输出识别 ```pdchoice``` JSON → 渲染可点按钮 → 点击以「我选择：X」续轮。
- 约定：浮球发起的任务输出只由浮球面板消费（SSE 单消费者限制）；ProjectDock 总控台仍能看到任务时间线。
- 改动仍集中在 AgentFloat（ProjectDock 零改动）。

## 6. P3 · 双向与彩蛋（可选，逐项评估）

| 项 | 做法 | 改动 |
|----|------|------|
| 秒级通知 | 浮球写端口文件 `%APPDATA%\AgentFloat\webshell_port.json`；浮球新增 `POST /api/notify`；ProjectDock 任务结束/日志写入时回调浮球 | 两侧 |
| 快报「项目进展」 | news 模块新增数据源：读各项目 `logs/ai` 近 24h，生成「昨天各项目干了什么」板块 | AgentFloat |
| 异常角标 | console 数据里 `compliant=false` / `failed_count>0` → 浮球角标轻度提醒 | AgentFloat |
| 托盘直达 | 托盘菜单「打开 ProjectDock 总控台」→ `webbrowser.open(base_url)` | AgentFloat |
| 安全硬化 | 共享 token 文件 + 两边 API 校验；或维持现状（风险已记录）| 两侧 |

---

## 7. 决策拍板表（grill 结论 · 默认档 · 可逐条否决）

> 交互问卷被中断，以下为本轮按实情拍板的默认值；你确认或否决后，本表即为最终决策。

| # | 问题 | 默认决策 | 理由 |
|---|------|----------|------|
| 1 | 主场景优先级 | S1+S2 进 MVP；S3 放 P2；S4 彩蛋 | 遥控器 + 监视器闭环最刚需，其余增量 |
| 2 | 架构方向 | 浮球单向调用 ProjectDock | PD 端口固定、改动集中一侧、零新组件；双向留 P3 |
| 3 | 启动方式 | 终端窗口（cwd = 项目目录）| 复用现有链路，交互体验不变 |
| 4 | 通知 | 完成/失败气泡 + 运行中角标 | 有感知但不打扰 |
| 5 | 入口 | 轮盘「项目坞」面板 | 与 Skills 面板同构，成本最低、可扩展 |
| 6 | MVP | 项目列表 + 项目目录启动 + 任务提醒 | 最小闭环，快速验证 |
| 7 | 安全 | 现状（仅回环），P3 评估 token | 先跑通体验，风险已记录 |
| 8 | 依赖关系 | 各自独立、互相探测、优雅降级（浮球可一键拉起 PD）| 不互相绑架 |

**明确不做（避免过度设计）**：不做文件监听/命名管道；不把浮球做成完整聊天客户端（与 ProjectDock 前端重复）；不做远程/局域网访问；P1 不动 ProjectDock 代码。

---

## 8. 风险与规避

| 风险 | 规避 |
|------|------|
| 轮询延迟（5s / 30s）| 本地回环成本可忽略；P3 双向方案可升级秒级 |
| PD 重启丢 job 内存 | 提醒以磁盘 `logs/ai`（console）为准，id/ts 去重 |
| 无鉴权 API | 保持 127.0.0.1；P3 硬化选项；方案内已标注 |
| SSE 抢事件 | 约定：浮球发起的任务只由浮球消费 |
| 浮球配置白名单坑 | `projectdock` 键显式加入 `apply_settings()` + 单测 |
| 两侧版本漂移 | `health.version` 门槛 + 面板提示；所需 API 均为既有稳定端点 |

---

## 9. 里程碑（估算）

| 阶段 | 内容 | 预估 | 目标版本 |
|------|------|------|----------|
| P1 | 项目坞 + 项目目录启动 + 任务提醒 | 1.5–2 天（浮球侧）| AgentFloat v3.4.0 |
| P2 | 指令台（流式 + pdchoice）| 1–1.5 天 | AgentFloat v3.5.0 |
| P3 | 双向通知 / 快报 / 角标 / 硬化（逐项）| ~1.5 天（含 PD 小改）| AgentFloat v3.6.x · ProjectDock 1.8.x |

流程遵循两边 AGENTS.md：**先备份 → 实现 → 测试 → CHANGELOG/VERSION → 归档 → 写 AI 日志**。

---

## 附：本轮核实来源

- AgentFloat：`webshell/server.py`（20 端点）、`core/launcher.py`、`ui/floatball.py`（轮盘分发 L1223–1288）、`config.example.json`、`AGENTS.md`
- ProjectDock：`api.py`（60 路由，L750–862）、`runner.py`（Job 结构 L14–22、list L145–152）、`console.py`、`models.py`（AgentRun / AILogCreate）

*本文档为方案草案：决策表任一项可改，确认后进入 update_plan 拆解与实现。*
