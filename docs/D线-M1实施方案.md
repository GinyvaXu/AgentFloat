# D 线 · Agent 进度中枢（M1 实施方案）

- 日期：2026-10-29
- 目标：把「Agent 在干什么」变成环境的一部分：抬眼可见、可算时间、可一键介入
- 本轮范围：协议 + 状态总线 + CLI（Qt L0/L1 下一步接入）

## 1. 三层形态

| 层 | 出现方式 | 内容 | 交互 |
|---|---|---|---|
| L0 雷达条 | 有任务 >2min 或 ≥3 步自动浮现，贴浮球侧边；全部结束 10s 收起 | 每项目一行：`● 项目 · 3/7 · 当前步 · ~18m` | 点一行展开 L1 |
| L1 快面板 | 从 L0 就地展开 | 步骤列表 + ETA + 失败/需要输入 + 中断/继续/聚焦 | 不抢焦点，Esc 收起 |
| L2 驾驶舱 | L1「打开驾驶舱」或手动 pin | 项目列表 / 每步预估 vs 实际 / 会话 / 回放 | 独立窗口，记忆位置 |

## 2. 统一任务总线（本轮已落地）

数据目录：`%APPDATA%/AgentFloat/progress/<sessionID>.json`（`AGENTFLOAT_PROGRESS_DIR` 可覆盖）。
写入方式：临时文件 + `os.replace` 原子替换；Qt 用 `QFileSystemWatcher` 监听目录。

状态示例：

```json
{
  "sessionId": "default",
  "project": "AgentFloat",
  "title": "D 线 M1",
  "status": "running",
  "currentStepId": "s2",
  "needsInput": false,
  "steps": [
    {"id": "s1", "title": "设计", "status": "done", "startedAt": "...", "finishedAt": "..."},
    {"id": "s2", "title": "实现", "status": "running", "startedAt": "...", "finishedAt": ""}
  ],
  "eta": {"etaSeconds": 1080, "etaText": "~18–30m", "confidence": "medium"},
  "updatedAt": "..."
}
```

协议事件：`plan / step / next / done / fail / need_input / cancel`。
- `plan`：项目、标题、步骤列表
- `step`：开始或切换当前步骤
- `next`：完成当前步骤并进入下一步
- `done / fail / need_input`：任务级状态
- `cancel`：取消

ETA：用已完成步骤的实际耗时均值 × 剩余步骤；1 步 → low，2 步 → medium，≥3 步 → high；没有数据 → `待估`。不使用 tokens/s。

## 3. CLI（本轮已落地）

```bash
python -m agentfloat.services.progress plan --project AgentFloat --title "D 线 M1" --steps "设计,实现,验证"
python -m agentfloat.services.progress step --title "实现"
python -m agentfloat.services.progress next
python -m agentfloat.services.progress need-input --question "是否继续？"
python -m agentfloat.services.progress done
python -m agentfloat.services.progress list
python -m agentfloat.services.progress show
```

`--session` 或环境变量 `AGENTFLOAT_PROGRESS_SESSION` 指定会话；输出 JSON，便于 MCP / Skill 解析。

## 4. 下一步（Qt L0/L1）

1. `progress_watcher`：QFileSystemWatcher 监听目录，2s 轮询兜底；合并 300ms 内变更。
2. L0 雷达条：无边框置顶窗，贴浮球侧边；按 `status` 排序（need_input > failed > running）；显示 `项目 · done/total · 当前步 · ETA`；全部结束 10s 后淡出。
3. L1 快面板：点 L0 就地展开；步骤行、ETA、失败原因、need_input 问题；按钮「中断（写 cancel）/ 继续（写 step）/ 聚焦（激活对应窗口）」。
4. 接入现有任务：Skill 安装 jobs、快报生成、A 线安装逐步写入同一总线；不伪造步骤，拿不到计划只显示「活跃/停滞」。
5. L2：独立驾驶舱（项目列表 + 步骤预估 vs 实际 + 回放时间线），后续迭代。

## 5. 验收（G2）

- 3 个项目并行，L0 同时显示 3 行，状态/ETA 实时
- 任一任务 need_input → 置顶 + 托盘提醒一次 + 一键跳回
- 一周试点 ETA 命中率（±30%）≥ 70%

## 6. 本轮状态

- ✅ 进度总线 store（原子写、列表、ETA、need_input）
- ✅ CLI `python -m agentfloat.services.progress`
- ✅ 3 项测试通过
- ⏳ Qt L0 雷达条 / L1 快面板
- ⏳ MCP 工具、Skill 协议、现有任务接入
- ⚠️ 尚未与 UI 联调；状态文件协议已稳定，可先接 CLI 试跑
