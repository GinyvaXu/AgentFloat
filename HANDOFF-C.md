# HANDOFF · C 线（Skill 车间 2.0）

> 2026-10-27 · 上游：`docs/2026.10.21-AgentFloat-vNext-大版本规划-风暴稿.md` §3.C
> 状态：**服务层初稿已存在但未验证、未接线**；UI 未做；子代理两次被中断，改为本文件交接。

## 现状

- 已提交：`src/agentfloat/services/skills/{models,metadata,discovery,installer,scoring,workshop}.py`（约 2975 行，`1970ad4`）
- 这些模块**没有任何测试、没有被 import**（`git grep workshop` 仅内部引用）
- Qt `panels/skills.py` 仍旧（39 个 skill，只读浏览）；Web 无技能页
- B 线（AI 日报 2.0）已实现并通过 489 项测试；A 线目录/安装/启动/更新/偏好已完成

## 下一步（按顺序）

1. **验收服务层**：为 `models/metadata/discovery/scoring/installer/workshop` 写最小真实用例（纯函数，临时目录），跑通后才知道哪些能留
2. **接数据**：让 `workshop` 产出与现有 `scan_skills` 对齐的列表（同一 SkillInfo 结构），保证 Qt 面板不回归
3. **UI（Qt 优先）**：在 `panels/skills.py` 增加「发现 / 已安装 / 可更新」三个视图与安装/卸载动作；空/加载/错误态
4. **Web**：仿快报页做一个只读列表 + 安装入口（可选，视时间）
5. **安全**：安装前展示来源与 commit；禁止静默覆盖用户已有 skill；失败回滚
6. **测试**：状态机与数据变换单测；全量 pytest 保持 ≥489

## 已知坑

- 子代理代码无测试，可能存在接口不一致；**先跑通再谈 UI**
- 安装会写 `%LOCALAPPDATA%/AgentFloat/skills_workshop`，测试务必用临时目录
- 不要把 `workshop` 的输出直接替换 `scan_skills`（先做适配层）

## 验收（建议）

- [ ] 列出 ≥39 个已装 skill，与现有面板一致
- [ ] 搜索/分类/详情可用
- [ ] 安装/卸载有确认与回滚
- [ ] 断网时只显示已装、不报错
- [ ] 全量测试全绿
