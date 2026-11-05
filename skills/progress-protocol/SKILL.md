---
name: progress-protocol
description: 把长任务进度写入 AgentFloat 进度总线（D 线雷达条）。当任务预计超过 2 分钟或 ≥3 步时使用：先 plan，再 step/next，结束 done/fail，需要用户确认时 need_input。
---

# Progress Protocol

目标：让用户在 AgentFloat 浮球旁的雷达条看到任务进度，而不是只能翻聊天记录。

## 何时使用

- 任务预计 > 2 分钟，或步骤 ≥ 3
- 需要用户确认、失败重试、跨会话交接

## 优先 MCP，回退 CLI

MCP 工具：`progress`（与 CLI 写同一份状态）

```json
{"session": "my-task", "action": "plan", "project": "项目名", "title": "任务名", "steps": ["设计", "实现", "验证"]}
{"session": "my-task", "action": "step", "title": "实现"}
{"session": "my-task", "action": "next"}
{"session": "my-task", "action": "need_input", "question": "是否继续？"}
{"session": "my-task", "action": "done"}
```

CLI 回退：

```bash
python -m agentfloat.services.progress --session my-task plan --project 项目名 --title 任务名 --steps "设计,实现,验证"
python -m agentfloat.services.progress --session my-task step --title 实现
python -m agentfloat.services.progress --session my-task next
python -m agentfloat.services.progress --session my-task done
```

## 规则

- 不要伪造步骤；拿不到计划时只在 L0 显示活跃/停滞。
- 步骤标题短（≤ 20 字），一次只推进一个 step。
- 阻塞时用 `need_input` 并写清问题；不要静默等待。
- 任务取消写 `cancel`，失败写 `fail --error "原因"`。
