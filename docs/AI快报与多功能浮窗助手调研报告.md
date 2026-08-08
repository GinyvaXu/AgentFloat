# AgentFloat 多功能浮窗助手 — AI 快报功能调研与扩展规划报告

> 版本：v1.1 规划草案 · 日期：2026-08-08
> 范围：AI 快报功能方案调研、浮窗助手生态参考、后续扩展功能建议、开发路线图

---

## 一、执行摘要

AgentFloat 当前是「通用多 Agent 启动浮窗 + 环绕菜单 + Skills 辅助窗 + API 余额监控」的 Windows 桌面工具。本次调研围绕两个目标：

1. **新增 AI 快报功能**：每天自动聚合 AI 行业资讯（Hacker News、GitHub Trending、arXiv、官方博客、中文社区），用本地 AI 生成中英双语速览，从浮窗一键查看。
2. **把 AgentFloat 打造为多功能浮窗助手**：以「可自选扇区的环绕菜单」为核心交互，扩展剪贴板、翻译、OCR、搜索、系统监控等高频能力，并预留插件化空间。

市场调研结论：**AI 快报已有成熟参考架构（RSS 多源聚合 + AI 策展 + 定时生成 + 多渠道推送）**，桌面浮窗领域有 **ZTools/uTools、Floatyball、Raycast** 等成熟交互范式。AgentFloat 的差异化定位是：**「本地优先 + 通用 Agent 中枢 + 可自选径向菜单」**，不需要做成大而全的平台，而是把「调用本机任意 AI Agent」这一能力作为核心卖点，快报只是其中一个模块。

---

## 二、GitHub 远程仓库状态（回答用户问题）

- 当前项目**没有配置任何远程仓库**：`git remote -v` 为空，仅本地 `main` 分支。
- `dist/`（构建产物）、`versions/`（版本归档）、`config.json`（个人配置）均在 `.gitignore` 中，**从未也不会被推送到远程**。
- 建议：创建 GitHub 私有仓库 `AgentFloat`，把源码 + README + 文档推上去（`versions/` 与 `dist/` 保持本地）。如需我代为创建仓库（需要 `gh` 已登录或你提供仓库地址），告诉我即可。

---

## 三、市场参考调研

### 3.1 AI 快报 / 新闻聚合类方案

| 项目 | 形态 | 核心做法 | 值得借鉴 |
|------|------|----------|----------|
| [TrendRadar](https://github.com/BedrockLian/TrendRadar) | Python 管线 + Codex | 多源 RSS 聚合 → 分类精选翻译 → 日/周/月报 Markdown；日推 3 次（早/午/晚） | 编排器 + 单一时区计划表 + 可审计 JSON/Markdown 产物 |
| [agents-radar](https://github.com/duanyytop/agents-radar) | GitHub Actions | 10 个数据源（HN / GitHub Trending / arXiv / HF / Product Hunt / 官方博客 sitemap），每日 08:00 双语简报 | **数据源清单与分类维度**（模型/工具/论文/产品/行业）可直接复用 |
| [condenseit](https://github.com/wildlifechorus/condenseit) | 自托管 Web | RSS + YouTube + HN + Reddit + 播客；本地 LLM（Ollama）或 OpenAI 兼容端点；星级反馈学习偏好 | **本地 LLM 摘要**（与 AgentFloat 本地优先理念一致）+ 偏好学习 |
| [dailybrief](https://github.com/adanoliveira/dailybrief) | 应用 | 每天两次抓取 → AI 摘要 → 主题聚类 → 个性化日报 | 主题聚类 + 个人化 |
| [horizonnews](https://github.com/xinqiyang/horizonnews) | Python | 中英双语日报 + 邮件/飞书/钉钉/Slack/webhook 推送 | **双语生成 + 多通道推送** |
| [ai-daily-skill](https://www.freemcplab.com/play/ai-daily-skill) | Agent Skill | 抓当日内容 → 按主题归类（模型/工具/论文/产品/行业）→ 去重 → 一句话摘要 → 结构化日报 | 「一句话摘要 + 分类」的轻量快报格式 |
| [Glanceway](https://www.producthunt.com/products/glanceway-everything-at-a-glance) | macOS 菜单栏 | 菜单栏收集 RSS + 插件源，AI 阅读摘要，菜单栏即 AI 收件箱 | **菜单栏/浮窗常驻 + 增量阅读**的交互 |
| Digest (App Store) | iOS/Android | 天气 + 通勤 + 日历 + 新闻 + 健康，AI 汇总为每日简报 | 「个人日程 + 资讯」混合简报 |

**结论**：AI 快报的成熟架构 = **定时抓取（RSS/API/sitemap）→ 过滤去重 → LLM 策展 → 结构化日报 → 本地 UI + 可选推送**。AgentFloat 应做轻量本地版：默认 4~6 个免费数据源，用本地 AI（claude/codex 命令，复用现有 `local_ai_service`）生成，数据与产物存本地。

### 3.2 浮窗 / 启动器类方案

| 项目 | 形态 | 核心交互 | 值得借鉴 |
|------|------|----------|----------|
| [ZTools](https://github.com/ZToolsCenter/ZTools)（uTools 开源实现） | 桌面启动器 + 插件平台 | 悬浮球 + 超级面板（长按唤出）；Alt+Z 全局搜索框；剪贴板/截图/插件市场 | **模块化动作注册 + 悬浮球长按面板**——AgentFloat 的「可自选扇区」正是其轻量版 |
| [Floatyball](https://meta.appinn.net/t/topic/85852/2) | Windows 悬浮球 | 高度自定义动作、文件拖放、悬停自动展开面板、吸附/透明/开机自启 | 悬浮球细节打磨（与 AgentFloat 定位最接近的竞品） |
| [Raycast](https://www.raycast.com/core-features/ai) | macOS 效率中枢 | AI Quick AI 悬浮窗 + AI Extensions + MCP 工具接入；热键即唤 | **AI 悬浮窗 + 扩展/MCP 生态**的现代 AI 交互标准 |
| SAO Utils 2 | 桌面 3D 启动器 | 手势唤出分层 UI、环形/径向菜单 | 径向菜单成熟度参考（已体现在 AgentFloat 环绕菜单） |
| Quicker / uTools / PixStart / umi-float | 效率工具 | 悬浮球 + 动作面板 + 插件 | 悬浮球 = 常驻入口 + 次级菜单 = 动作面板（AgentFloat 已具备） |

**结论**：AgentFloat 的环绕菜单 + 可自选扇区方向正确，与 ZTools「超级面板」、Raycast「AI 悬浮窗」一致；下一步关键是**提供足够的动作种类**（快报、剪贴板、翻译等），让「自选扇区」真正有用。

### 3.3 交互与 UI 模式参考

- **悬停/长按双通道**：ZTools 长按打开超级面板、Floatyball 悬停展开面板 → AgentFloat 已实现双通道并可调，方向正确。
- **常驻收件箱式浮窗**：Glanceway 菜单栏收件箱 → AgentFloat 可用「余额角标同款」的迷你快报角标 + 点击展开快报面板。
- **多级菜单空间**：用户已要求「悬停唤出次级菜单环绕」——快报面板、剪贴板历史、翻译结果都可作为环绕菜单的次级层。

---

## 四、AI 快报功能设计

### 4.1 定位

- **默认免费**：数据源全部为免费公开接口（无 API Key 也能跑）。
- **本地优先**：抓取与 AI 策展在本机完成（复用 `local_ai_service` 对 claude/codex 的调用），产物存 `%APPDATA%/AgentFloat/news/`。
- **轻量**：默认每天 1~2 次（可配），每次全链路 < 90 秒，不打扰。

### 4.2 数据源（默认 + 可配置）

| 源 | 类型 | 接口 | 默认 |
|----|------|------|------|
| Hacker News | 社区 | Algolia API（top AI stories） | ✅ |
| GitHub Trending | 代码 | HTML/API（AI 主题） | ✅ |
| arXiv | 论文 | arXiv API（cs.AI/cs.CL/cs.LG） | ✅ |
| 机器之心/量子位等中文源 | 资讯 | RSS | ⚙️ 可配 |
| Anthropic/OpenAI 官方 | 博客 | sitemap lastmod 增量 | ⚙️ 可配 |
| Product Hunt | 产品 | GraphQL（需 token） | ⚙️ 可配 |

用户可增删源（RSS URL 列表 + 内置源开关），配置存 `config.json` 的 `news` 段。

### 4.3 生成链路

```
QTimer 定时（默认 09:00）或手动触发
  → NewsWorker(QThread)：并行抓取各源（超时 15s/源）
  → 过滤去重（标题/URL 归一化，保留 Top N）
  → 调用本地 AI（claude -p 或 codex exec，模板化 prompt）生成：
      ## 今日 AI 速览（4~6 条，每条约 60 字）
      - 分类标签 + 一句话摘要 + 来源链接
  → 落盘 news/<date>.md + news/latest.json
  → 更新浮窗「快报角标」（未读数/红点）
```

### 4.4 UI / 交互

- **环绕菜单**新增「AI 快报」扇区（已预留 `news` 动作，本轮加入自选列表）。
- 点击后打开**快报面板**（无边框小窗，复用 SkillsPanel 的风格体系）：左侧日期列表，右侧正文（QTextBrowser，可滚动、可点击链接）。
- 可选：托盘气泡通知「今日 AI 快报已生成」；浮窗角标显示红点/条数。
- 设置页新增「AI 快报」Tab：启用开关、生成时间、数据源勾选、AI 工具选择（claude/codex/自定义）、条数。

### 4.5 技术实现（与现有架构契合）

- 新增 `news_fetcher.py`（抓取 + 解析，纯标准库 + urllib，参考 `api_fetcher.py` 风格）。
- 新增 `news_worker.py`（QThread 轮询/一次性任务，参考 `api_monitor_worker.py`）。
- 复用 `local_ai_service.py` 的 AI 调用与模板机制生成摘要。
- 复用 `skills_panel.py` 的无边框窗口 + 主题体系做快报面板。
- 环绕菜单 `news` 动作 → `_open_news_panel()`（已预留 handler，先弹「开发中」，v1.1 替换为真面板）。

### 4.6 分阶段实现

| 阶段 | 内容 | 版本 |
|------|------|------|
| P1 | news 扇区可配置 + 快报面板骨架 + 手动生成（HN + GitHub Trending） | v1.1 |
| P2 | 定时自动生成 + 更多数据源 + 中文源 + 角标红点 | v1.2 |
| P3 | 个性化（偏好源/关键词）、推送通知、双语 | v1.3+ |

---

## 五、其他扩展功能建议

### P0 — 高价值、实现成本低（建议随 v1.1~v1.2 逐个加入）

| 功能 | 说明 | 与环绕菜单的接法 |
|------|------|------------------|
| **剪贴板历史** | 监听剪贴板，保存最近 N 条文本/图片，搜索 + 一键复制 | 新扇区「剪贴板」→ 次级面板 |
| **划词翻译** | 全局选中文本 → 弹窗翻译（可用本地 AI 或免费翻译 API） | 新扇区「翻译」或托盘快捷键 |
| **OCR 截图识别** | 框选屏幕区域 → OCR 文字 → 复制/翻译（Windows 自带 OCR 或免费引擎） | 新扇区「OCR」 |
| **快速搜索** | 选中文本 → 浏览器搜索（Google/百度/GitHub/HN） | 长按浮窗唤出的次级菜单 |
| **自定义命令面板** | 预置常用命令（打开文件夹、运行脚本、锁屏、关机） | 新扇区「命令」 |

### P1 — 中价值（v1.3 之后）

- **系统监控**：CPU/内存/网络/GPU 迷你面板（浮窗角标实时数字）。
- **天气/日程**：桌面小部件（参考 iOS 小组件），今日天气 + 待办。
- **番茄钟/专注**：浮窗倒计时 + 托盘提示。
- **AI 快捷问答**：点击浮窗弹出输入框，直接把问题发给本地 Agent，结果浮窗展示（Raycast Quick AI 的轻量版）。
- **全局热键扩展**：自定义任意动作的热键。

### P2 — 远景（v2.0）

- **插件系统**：仿 ZTools `plugin.json`，第三方动作以插件形式注册到环绕菜单（AgentFloat 的「自选扇区」天然适配）。
- **MCP 网关**：把 AgentFloat 的能力暴露为 MCP server / client，让 Claude/Codex 直接调用（agents-radar 已有先例）。
- **跨设备同步**：配置 + 快报收藏云同步（可选）。

---

## 六、路线图（建议）

```
v1.1  —— AI 快报 P1（news 扇区、快报面板、手动生成）
      + 剪贴板历史
v1.2  —— AI 快报 P2（定时 + 多源 + 红点角标）
      + 划词翻译 / OCR
v1.3  —— 自定义命令面板 + 快速搜索 + 通知
v2.0  —— 插件系统 + MCP 网关 + 跨设备同步
```

每步保持「debug 版构建 → 归档旧版 → 测试 → 正式版再出安装包」的既有迭代规范。

---

## 七、风险与建议

- **数据源稳定性**：RSS/HTML 抓取易变，需超时 + 失败降级（单个源失败不影响整体）。
- **AI 摘要成本**：默认用本地/免费 AI 或限制条数；可配置「不启用 AI，仅原文列表」模式。
- **隐私**：所有数据本地处理，不上传；推送通知可关。
- **建议下一步**：确认快报 P1 方案后，我按 v1.1 迭代：实现 `news_fetcher/news_worker/快报面板`，加「剪贴板历史」，构建 debug 版归档。

---

*报告完 · 附：调研参考链接见文内标注*
