<p align="center">
  <img src="assets/agent_float_icon.png" alt="AgentFloat" width="132">
</p>

<h1 align="center">🌀 AgentFloat</h1>

<p align="center"><b>通用多能 · AI Agent 桌面悬浮助手</b></p>

<p align="center">
一个浮窗，唤醒你的整个 AI 工作流 —— 一键启动任意 Agent、环形菜单随心定制、Skills 辅助窗、
API 余额实时监控，全部收纳在一个毛玻璃小球里。
</p>

<p align="center">
  <a href="VERSION"><img src="https://img.shields.io/badge/version-v3.9.0-5B8DEF?style=for-the-badge&logo=semver" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"></a>
  <a href="#"><img src="https://img.shields.io/badge/platform-Windows%2010%2F11-8E44AD?style=for-the-badge&logo=windows&logoColor=white" alt="Windows"></a>
  <a href="#"><img src="https://img.shields.io/badge/UI-PyQt5-41b883?style=for-the-badge&logo=qt&logoColor=white" alt="PyQt5"></a>
</p>

---

## ✨ 功能亮点

| | |
|---|---|
| 🪟 **深色玻璃浮球** | 品牌渐变描边（`#0a84ff→#af52de`）+ 内部光晕 + 白色旋涡（P2 方案 C）；弹簧驱动悬停/按压/退出动效；拖拽不误弹、贴边唤出顺滑（交互状态机） |
| 🌀 **轮盘式环绕菜单** | **按住立即外滑**唤出（游戏式轮盘：滑到扇区松手即执行，选中后确认脉冲 + 丝滑收合再执行动作）；**按住不动约 2s → 环形进度条 → 启动主 Agent**；悬停仅视觉反馈；菜单内含「移动浮窗」模式；品牌渐变描边 + 外发光 + 扇区预渲染（60fps） |
| 🎛️ **扇区功能模块化** | 轮盘 4 / 6 / 8 扇区任选，每个扇区可自由分配：启动某 Agent、Skills 辅助窗、API 余额、设置、AI 快报、剪贴板历史、命令面板、退出 |
| 🧩 **通用多 Agent 启动** | 点击浮窗即启动 Claude Code / Codex CLI / Pi Coding Agent / 自定义命令，右键或托盘可快速切换主 Agent，实时状态指示灯 |
| 🧠 **Skills 辅助窗** | 无边框窗口扫描本机已安装 skills，分类树浏览 + 中英对照切换 + 触发指令一键复制（右侧完整展示，溢出自动滚动） |
| 📊 **API 用量监控** | 通用 JSONPath 框架轮询任意 API 用量，浮窗角标实时显示余额，<5¥ 低余额变色警告，环绕菜单一键跳转对应平台用量页 |
| 📰 **AI 快报** | 多源聚合（Hacker News / GitHub Trending / 少数派 / 量子位 / arXiv）+ 本地 Agent 一键生成今日 AI 速览，支持关注主题定向偏好（预设 + 权重 + 彩色标注），无边框精简面板浏览、链接可点击，启动自动生成后自动弹出 + 托盘通知，历史记录默认收起 |
| 🤖 **本地 AI 自检服务** | 校验 API 余额端点、查找并翻译缺失的 skills；自动部署翻译 skill，检测到新 skill 自动触发补译（可在设置中关闭） |
| 📋 **剪贴板历史** | 自动记录复制内容（上限 60 条、相邻去重），面板点击即复制回剪贴板，支持单条删除与一键清空 |
| ⌘ **自定义命令面板** | 自由管理常用命令（名称/命令/参数/工作目录/启动方式），一键运行或新建独立窗口 / Windows Terminal / 后台静默，内置常用示例 |
| 💧 **喝水助手** | 喝水 / 久坐 / 护眼 三个独立循环计时器，全屏遮罩 / 居中弹窗 / 托盘三种提醒形态，多屏自选 + 游戏进程豁免，每日目标杯数轻量统计 |
| 🔔 **系统托盘 / 开机自启** | 最小化至托盘、双击显示浮窗、可注册 Windows 自启动，全局热键 `Ctrl+Alt+C` 随时唤起 |
| 🎬 **动态退出动画** | 退出时播放全新收拢动画，配合窗口淡出，告别生硬关闭 |
| 📝 **Debug 日志体系** | 调试版每次运行生成 `版本+时间戳+崩溃类型` 命名的日志与崩溃报告 txt，关闭程序时统一导出，便于回溯问题 |

## 🚀 快速上手

启动后桌面出现一颗 **52×52px 毛玻璃圆角小球**：

| 操作 | 效果 |
|---|---|
| **单击** | 启动主 Agent（默认 Claude Code） |
| **悬停** | 浮球放大 + 辉光（仅视觉反馈，不再唤出菜单） |
| **按住不动约 2s** | 环形进度条实时提醒 → 启动主 Agent（松手取消） |
| **按住并立即外滑** | 唤出**轮盘**，滑到扇区松手即执行（松在中心/空白取消）|
| **轮盘选「移动浮窗」** | 进入移动模式：浮窗跟随光标（左键放置 · 右键或 Esc 取消） |
| **右键** | 打开设置 / Agent 切换 |
| **托盘图标双击** | 重新显示浮窗 |

## 📦 安装方式

**方式一：安装包（推荐）**
下载最新 Release 中的 `AgentFloat_Setup.exe`，双击运行安装向导。

**方式二：便携版**
下载 `AgentFloat.exe` 放到任意目录直接运行。首次运行自动生成默认配置，配置保存在 `%APPDATA%/AgentFloat/config.json`。

**方式三：源码运行**
```bash
pip install PyQt5 pywin32
python agent_float.py
```

> **前置依赖**：至少一个 AI Agent CLI（如 `claude` / `codex` / `pi`），可在「设置 → Agent 管理」中添加自定义命令；Windows Terminal 提供最佳终端体验（非必需）。

## ⌨️ 快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+Alt+C` | 显示 / 隐藏浮窗 |
| 双击托盘图标 | 显示浮窗 |
| 悬停 / 长按浮窗 | 唤出环绕菜单 |
| 右键浮窗 | 打开设置菜单 |

## 🎛️ 环绕菜单模块化

在「设置 → 交互」中可自由定制你的环形菜单：

- **扇区数量**：4 / 6 / 8 三种布局
- **每个扇区的动作**：
  - `启动 <Agent>` — 点击直接启动对应 Agent
  - `Skills 辅助窗` — 浏览 / 翻译 / 复制触发指令
  - `API 余额` — 查看用量，点击跳转对应平台网页
  - `设置` — 打开设置
  - `AI 快报` — 打开每日 AI 行业速览（多源聚合 + 本地 Agent 摘要）
  - `剪贴板历史` — 查看 / 复制最近复制的文本
  - `命令面板` — 快速运行自定义命令
  - `退出` — 播放收拢动画后退出

> 模块化扇区动作位让未来扩展（快捷短语、定时提醒等）无需改动交互框架即可接入。

## 🛠️ 从源码构建

```bash
# 测试（146 项单测 + 覆盖率）
python -m pytest
python -m pytest --cov --cov-report=term

# 调试版（默认 onedir，启动更快；自动归档旧产物到 versions/）
python build_debug.py            # → dist/AgentFloat_debug/AgentFloat_debug.exe
python build_debug.py --onefile  # 可选：单文件便携版 → dist/AgentFloat_debug.exe

# 构建后冒烟（隔离 APPDATA：进程存活 + 日志无 ERROR + 启动耗时）
python smoke_test.py

# 正式版（确认稳定后；同样支持 --onefile）
python build_exe.py

# 安装包（Inno Setup）
python build_setup_exe.py
```

构建前会**自动把旧版产物归档**到 `versions/v<旧版本>/dist/`；onedir 产物会做未用 Qt 组件的安全裁剪。版本归档与构建产物仅保留在本地，不随 git 上传。

## 📁 目录结构

```
AgentFloat/
├── agent_float.py              # 启动入口（python agent_float.py，实际源码在 src/）
├── src/agentfloat/
│   ├── app.py                  # 应用引导（托盘 / 热键 / 生命周期 / 更新链路）
│   ├── core/                   # 路径 / 配置 / 主题 token / 日志 / 自启 / 启动器
│   ├── ui/                     # 浮球 / 环绕菜单 / 轻面板 / 加载指示器
│   ├── services/               # API 余额 / AI 快报 / Skills / 喝水 / 更新 / dsh / 安装
│   └── webshell/               # FastAPI 后端 + 事件桥 + pywebview 窗口
├── web/                        # Web 设置 / API 用量 / AI 快报 前端资源
├── tests/                      # pytest 测试（P3 完善）
├── config.example.json         # 配置模板（本地 config.json 不入库）
├── build_debug.py              # 调试版构建（带控制台）
├── build_exe.py                # 正式版构建
├── build_setup_exe.py          # 安装包构建
├── build_utils.py              # 构建辅助（归档 / 版本）
├── AgentFloat.spec             # PyInstaller 参考配置
├── docs/                       # 设计与调研文档
└── assets/                     # 图标等静态资源
```

## 🗺️ 路线图

- [x] v1.0.x — 通用 Agent 启动 / 环绕菜单 / Skills 辅助窗 / API 余额监控
- [x] v1.1.0 — 环绕菜单扇区模块化自选 + 灰块覆盖层根因修复
- [x] v1.2.0 — **AI 快报**：多源聚合 + 本地 Agent 摘要 + 无边框面板 + 定时/启动补生成（详见调研报告）
- [x] v1.2.1 — 快报体验优化：关注主题定向偏好、生成加载条、设置应用/保存重构、未读角标美化
- [x] v1.2.2 — **效率工具**：剪贴板历史 + 自定义命令面板；吸附隐藏与环绕菜单冲突修复、按压即弹出、快报自动弹窗与面板精简、扇区图标/字体/圆点自适应防重叠、移除未读角标、自动更新链路复核
- [x] v2.x — Web 套壳（设置 / API 用量 / AI 快报）+ Agent 安装 + DeepSeek Harness 支持
- [x] v2.3 — **P1 结构重构**：src 包化 + 死代码清除（-3.3k 行）+ 主题 token 收敛
- [x] v2.4 — **P2 交互与视觉重写**：浮球状态机 / 环菜单手感 / ProjectDock 设计语言
- [x] v3.0 — **P3 测试与瘦身**：pytest 146 项 / onedir 打包（启动 4.3s→1.8s）/ 依赖裁剪（详见 [docs/v3重构方案.md](docs/v3重构方案.md)）
- [x] v3.0.1 — **稳定性修复**：浮窗位置自愈（越界收敛 / 离屏收回 / 托盘重置）+ 单实例守卫 + 退出链路修复 + 中文路径 Qt 兜底
- [x] v3.0.2 — **崩溃修复**：修复 QThread 运行中析构导致的 qFatal 崩溃（打开设置后闪退 / 设置无法保存）+ 并存实例提醒 + 线程栈诊断
- [x] v3.1.0 — **配置安全 + OpenCode 接入**：配置原子写入（根治设置被清空）+ OpenCode CLI/Desktop/Web 预设 + Web Agent 启动/终止（浮球右键菜单）
- [x] v3.1.1 — **设置保存修复**：开关置脏（无法保存）+ renderPage 报错 + 异步 apply 回读竞态（开关被打回）+ 垃圾键
- [x] v3.2.0 — **环形菜单全新交互**：按住选环（松手执行）+ 灵敏档 180/300ms + 扇区预渲染 + 品牌渐变发光视觉
- [x] v3.2.1 — **跟手性与设置修复**：悬停检测 100ms→16ms / 高亮 60ms→20ms / DPI 命中偏差 / 背景预渲染（3.3 倍）/ 扇区数量与映射无法设置
- [x] v3.3.0 — **全流程动效 + 游戏式手势**：按住不动 2s 启动（环形进度条）/ 按住外滑唤出轮盘 / 轮盘「移动浮窗」模式（左键放置·右键/Esc 取消）/ 全窗口渐入渐出 / 面板新风格
- [x] v3.3.1 — **交互精简 + 关闭动效**：取消悬停唤出；选中后确认脉冲 + 丝滑收合再执行；面板深度打磨（渐变标题栏 / Esc 关闭 / 统一主按钮）
- [x] v3.4.0 — **OpenCode Go 余额 + 贴边轮盘 + 跨屏 DPI**：预设一键接入与角标显示模式（剩余%/已用%/金额）；贴边让位回弹后开环；跨屏重建位图；吸附阈值 36px
- [x] v3.5.0 — **Agent 进程面板**：悬停弹出（靠边自动选侧）/ 运行时长与最近活动 / 分级中断（软中断 Esc · 结束进程树）/ 继续任务（聚焦注入 continue）
- [x] v3.5.1 — **面板与余额显示重做**：面板半透明且只显示运行中（无则提示）；中断后保留「已中断」+ 继续任务（注入 continue / 按 resume_args 续接会话）；余额显示框半透明多行模块化（自定义行/拖动位置/自适应不裁切）；退出不再结束 Agent 进程
- [x] v3.5.2 — **手动拉取 + 多平台预设**：API 页「立即拉取」不等轮询即刻刷新；端点预设新增 DeepSeek / Kimi / SiliconFlow / OpenRouter；余额显示行预设一键添加（OpenCode Go 5h/周/月剩余%、余额行、余额+已用%）
- [x] v3.5.3 — **API 用量页彻底重构**：状态总览条 + 端点卡片（状态/字段/错误建议/复制）+ 显示框实时预览 + 独立设置与折叠帮助；移除示例占位端点、端点自动去重、结果按名对齐
- [x] v3.5.4 — **显示框自由调整**：滚轮/右下角拖拽/设置滑杆调整大小与不透明度；进程面板不透明度
- [x] v3.6.0 — **本地账户 + API Key 保险箱 + 配置导出导入**：多账户（PBKDF2/AES-256-GCM/DPAPI 快速登录）、启动 Agent 自动注入密钥环境变量、`.afpack` 口令保护单文件导出导入（可选含 Key）
- [x] v3.6.2 — **启动动画 + 代码审查清理 + Windows 安装包**：屏幕中心光晕/圆环/放大浮球 → 飞向落点（版本号+随机问候语、合成提示音、不可跳过、多屏适配）；去死代码/消重复（含球体渲染共用）；`build_installer.py` 产出免管理员安装包
- [x] v3.9.0 — **新用户引导 + 图文教程 + 快报重写 + 更新链路打通**：首次运行浮球聚光灯引导（6 步）；Web 控制台「使用指南」页（3 段新录演示动图 + 5 张截图 + FAQ/快捷键）；AI 快报交互层完全重写（分类分组/未读收藏/搜索过滤/键盘导航 + 阶段进度可取消单源重试 + 点击通知直达 + Markdown 导出）；自动更新接入自有 R2 镜像为第一优先并强制 SHA256 校验
- [x] v3.8.0 — **安全加固 + 体验优化**：本地接口加访问令牌 / Host 白名单 / 同源校验（修复任意网页可读走保险箱密钥）、更新包 SHA256 校验、依赖锁版本；设计令牌与空态文案统一；显示器热插拔自动收敛；进程检测提速约 15 倍
- [x] v3.7.0 — **全新品牌图标（AF-2 旋涡徽记）+ 浮球旋涡换新**：应用/安装器/托盘/窗口/任务栏/README/Web 全套替换（ICO 七档）；浮球保留深色玻璃质感与品牌渐变描边，仅换新旋涡 glyph；修复安装包自身图标为 Inno 默认图标的历史问题；Web 新增 favicon
- [ ] 下一步候选 — 云账户同步（AuthProvider 抽象）/ 密钥一键测端点 / 导出文件拖到浮球导入
- [ ] v3.3.x（进行中）— 各子页面逐页深度重构（Skills/快报/剪贴板/命令/喝水）+ 剩余动效打磨
- [ ] v3.3.x（候选）— OpenCode Go 余额预设（角标滚动剩余%）/ Web 多标签 / 更多效率工具

> 📚 功能扩展的完整调研与方案对比见 [AI快报与多功能浮窗助手调研报告](docs/AI快报与多功能浮窗助手调研报告.md)。

## 🙏 致谢

AI 快报与扩展功能的设计参考了以下开源项目与产品（详见 [调研报告](docs/AI快报与多功能浮窗助手调研报告.md)）：

- **AI 快报类**：[TrendRadar](https://github.com/BedrockLian/TrendRadar)、[agents-radar](https://github.com/duanyytop/agents-radar)、[condenseit](https://github.com/wildlifechorus/condenseit)、[dailybrief](https://github.com/adanoliveira/dailybrief)、[horizonnews](https://github.com/xinqiyang/horizonnews)、[Glanceway](https://www.producthunt.com/products/glanceway-everything-at-a-glance)、Digest
- **浮窗 / 启动器类**：[ZTools](https://github.com/ZToolsCenter/ZTools)（uTools 开源实现）、[Floatyball](https://meta.appinn.net/t/topic/85852/2)、[Raycast](https://www.raycast.com/)、[SAO Utils](https://sao-sys.com/)
- 数据源：Hacker News、GitHub Trending、少数派、量子位、arXiv 公开接口，感谢各平台免费开放。

## 📄 许可

[MIT License](LICENSE)
