# HANDOFF — AgentFloat 前端精修（v3.16.3 代码已提交，构建待做）

> 2026-10-19 深夜补充：
> - 已装版本：**v3.16.2**（用户已验 B2/C3 通过；B5 跨屏按用户要求延后）
> - 工作树已提交 v3.16.3：C1 剪贴板复制反馈（选中该行 + 1.2s 提示）；**尚未构建/装机**
> - **红灯**：`tests/test_floatball_integration.py::test_interaction_flow` 失败（点击后仍触发 launch）。已确认与 C1 无关（stash 验证），v3.16.2 起就存在；疑似点击回调路径/状态机在测试环境下提前走 `launch_requested`，需下轮隔离（建议：在该测试里记录 `_interaction` 状态与 `acts`，用 print + `-s` 看实际分支）
> - 流程：**构建前必须跑全量 pytest**（v3.16.2 只跑 pyflakes 就打包，漏了红灯）
> - 回退：`versions/v3.16.2/dist/AgentFloat-Setup-3.16.2.exe`；动效开关 `motion.legacy`
> - 待办：`docs/待办-Backlog.md`（P0 Agent 收录/调研、P1 前端遗留）

## 状态

- 已装版本：**v3.14.1（测试版）**，本机运行中；源码已推 GitHub（`96cba00`）
- 当前批次：前端精修 **B1 完成、B2 完成**；**B3 未开始**；**重做方向已选定 C 分栏**
- 动效方案：v3.13.0 全量实施完成；回退开关 `motion.legacy`（配置即时生效）

## 已完成（可验收）

| 项 | 产物 |
|---|---|
| 前端审计（Qt + Web，56 条） | `docs/前端精修方案.md` |
| B1：Qt 字号层级修复（全局 QSS 不再压平 setFont）、剪贴板清空二次确认 + 单条 3 秒撤销、禁用态、Web 对比度（hint 2.9:1→4.6:1）、主导航键盘可达 | v3.14.0（装机验证） |
| B2：`DESIGN.md`、`theme.CARD` 单源、`ui/menu_style.py` 菜单单源（修 QMenu 泄漏）、flash 统一、Web CSS 去重 | v3.14.1（装机验证） |
| 重做方向拼版（A 紧凑 / B 卡片 / **C 分栏**） | `docs/direction/boards.html`（预览服务 http://127.0.0.1:8765/boards.html） |
| 用户决定 | 范围=试点 Web 一屏（快报页）；方向=精密工具感；品牌渐变保留、毛玻璃收缩；参照=我出拼版→已选 **C** |

## 下一步（按顺序）

1. **Web 快报页按 C 分栏落地**（本轮未做，代码未动）
   - 渲染入口：`web/js/app.js:973 renderNews()`；列表行：`app.js:956 newsItemHtml()`；筛选：`app.js:944 newsFilteredItems()`
   - 现有选择态：`newsUI.focus`（行上已有 `.focus` class）；点击/星标/已读切换都用 data-* 委托事件
   - 目标结构：`.news-split`（左 52% 列表 + 右详情），详情含：分类 kicker、标题、meta（时间/未读/收藏）、摘要、按钮「打开原文 / 收藏 / 标记未读」
   - 样式：`web/css/style.css:316` 起 `.news-*` 区；新样式用 `--r-* / --sp-* / --dur-* / --ease-*` 令牌；行高 34px，细线分隔，单强调色（拼版 C 即规范）
   - 验收：①宽窗（≥1000px）分栏正常；②窄窗（<760px）自动堆叠为单列；③点行切换详情不丢筛选/搜索；④未读/收藏状态与浮球红点同步
   - 已知坑：整页 `innerHTML` 重渲染（`app.js:1076` 附近）会丢焦点/滚动位置 → 详情切换只重绘详情容器；搜索输入需保留 `setSelectionRange` 补救
2. **B3 收尾**（约 45 分钟）：Web `confirmDialog()` 组件替换原生 `confirm()`（`app.js:1516/1525/1555/1736/1826`、`install.js:90`）；加载骨架 + 超时；错误卡片 + 重试；空态行
3. 重做铺开：其余 Web 页（设置/指南/语录）→ 再评估 Qt 侧（浮球/环菜单保持现状，面板按拼版令牌微调）

## 关键路径与命令

- 构建/装机（ASCII 联接路径，避免中文路径坑）：
  ```
  cd C:\AIAgentBase\AgentFloat_build
  .venv\Scripts\python.exe build_exe.py
  .venv\Scripts\python.exe build_installer.py   # 产物 → versions/v<ver>/dist/
  ```
  装机流程：`taskkill /IM AgentFloat.exe` → 旧版 `unins000.exe /VERYSILENT` → 新版 Setup `/VERYSILENT` → 启动 → 看 `%APPDATA%\AgentFloat\logs\AgentFloat.log`
- 推送：`GIT_CONFIG_GLOBAL=C:\Users\zhenl\AppData\Local\Temp\opencode\gitconfig-push` 后 `git push https://github.com/GinyvaXu/AgentFloat.git main:main`（绕过 gh-proxy 改写；网络不稳时重试脚本 `push_persist.py`）
- Web 预览：`python -m http.server 8765 --directory docs\direction --bind 127.0.0.1`（拼版仍在跑）
- 回退：git tag `pre-motion`（动效）、`pre-polish` 未打（B1 起点为 `95d5f8d`）；二进制回退 `versions/v3.13.2/dist`

## 约束

- 默认测试版：构建 + 每版本地安装 + 推源码；不打 tag/Release/官网
- 版本号唯一来源 `VERSION`；每批更新 `CHANGELOG.md`；产物归档 `versions/v<ver>/dist/`
- 不删文件、不覆盖旧产物、push 需明确指令（本项目内已授权按需 push）
- 本机 shell 偶尔无法创建窗口（服务器重启可恢复）；视觉验证优先用 `grab()` 抓图 + 浏览器预览
