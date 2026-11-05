# BRIEF · 4.0.0 收尾与审验

- 日期：2026-11-04
- 级别：max（版本收尾、跨模块、需两次独立审查、上下文已长）
- 目标：完成 4.0.0 剩余开发与验收；不 push、不 tag、不发 Release。

## 范围
1. LLM 页面浏览器复测：切换 / 保存 / 测试 / Token / 空态 / 窄屏
2. 全量回归：pytest、pyflakes、node --check、安装包内容
3. 两次独立审查：LLM UI/UX、发布/回归/安全
4. P0/P1 修复后重新构建安装

## 非目标
- 真实端点联调（无 Key）
- 修改 Claude/Codex 配置、本地路由
- push / tag / Release

## 验收
- 浏览器冒烟无 console error
- pytest 通过（2 个既有 floatball 失败标注）
- 两次审查 P0=0，P1 有处置
- 安装包重建并安装
- HANDOFF 可继续
