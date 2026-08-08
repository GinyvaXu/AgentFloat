# AgentFloat — AI Agent 桌面悬浮助手

[![Version](https://img.shields.io/badge/version-1.0.5-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)]()

一个精致的 Windows 桌面悬浮按钮，一键启动你本机的任意 AI Agent（Claude Code / Codex CLI / 自定义命令）。iOS 风格毛玻璃外观，支持亮色/暗色双主题，内置 Skills 辅助窗与 API 用量余额监控。

<p align="center">
  <img src="assets/agent_float_icon.png" alt="AgentFloat Icon" width="128">
</p>

## ✨ 功能特性

- 🎨 **iOS 风格毛玻璃** — 7 层渐变绘制，亮色/暗色双主题
- 🖱️ **自由拖拽** — 任意位置拖放，带按压缩放和涟漪动画
- 📌 **边缘吸附** — 拖到屏幕边缘自动贴边，支持自动隐藏
- 🌓 **即时换肤** — 设置对话框中一键切换，无需重启
- ⚡ **通用多 Agent 启动** — 点击浮窗启动主 Agent；右键/托盘可切换其他 Agent
- 🎯 **悬停/长按环绕菜单** — 悬停或长按浮窗唤出扇形菜单（双通道，可在设置中调整），一键切换 Agent、打开 Skills 辅助窗、查看 API 用量、设置与退出
- 🧩 **Skills 辅助窗** — 一键查看本机已安装 skills、功能描述与手动触发指令（无边框窗口，支持中英对照与一键复制）
- 🤖 **本地 AI 自检服务** — 首次启动自动调用主 Agent 校验 API 余额端点、查找并翻译缺失的 skills；可在设置中随时再次运行
- 🔔 **系统托盘** — 最小化到托盘，右键菜单快速操作
- 🟢 **状态指示** — 绿色指示灯显示主 Agent 运行状态
- 🚀 **开机自启** — 可选注册到 Windows 启动文件夹
- 💰 **API 余额监控** — 通用 JSONPath 框架，轮询任意 API 用量，浮窗角标实时显示
- 💾 **配置持久化** — 配置保存于 `%APPDATA%/AgentFloat/`，首次运行自动生成

## 📸 使用方式

> 启动后桌面出现 52×52px 毛玻璃圆角浮窗。**点击**启动主 Agent；**悬停 400ms** 或**长按 500ms**（默认）唤出环绕菜单；右键浮窗或系统托盘图标打开设置。

## 📦 安装方式

### 方式一：安装包（推荐）

下载最新 Release 中的 `AgentFloat_Setup.exe`，双击运行安装向导。

### 方式二：便携版

下载 `AgentFloat.exe`，放到任意目录直接运行。首次运行自动生成默认配置，配置文件保存在 `%APPDATA%/AgentFloat/config.json`。

### 方式三：从源码运行

```bash
pip install PyQt5 pywin32
python agent_float.py
```

### 前置依赖

- **至少一个 AI Agent CLI**（如 `claude` / `codex`），可在「设置 → Agent 管理」中配置自定义命令
- **Windows Terminal**（推荐）— 提供最佳终端体验，非必需

## ⌨️ 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Alt+C` | 显示/隐藏浮窗 |
| 双击托盘图标 | 显示浮窗 |
| 悬停 / 长按浮窗 | 唤出环绕菜单 |
| 右键浮窗 | 打开设置菜单 |

## 🔧 构建

```bash
# 构建调试版（带控制台，默认迭代目标）
python build_debug.py

# 构建正式版（确认稳定后）
python build_exe.py

# 构建安装包
python build_setup_exe.py
```

每次构建前会自动把旧版 exe 归档到 `versions/v<旧版本>/dist/`，版本归档目录本地保留不上传。

## 🗂 目录结构

```
AgentFloat/
├── agent_float.py              # 主程序（浮窗 + 设置 + 托盘）
├── agent_registry.py           # 多 Agent 注册表与启动模型
├── radial_menu.py              # 悬停/长按环绕菜单（QPainter 自绘）
├── skills_scanner.py           # Skills 扫描器（SKILL.md 解析）
├── skills_panel.py             # Skills 辅助窗（双栏 + AI 优化）
├── agent_manager.py            # Agent 管理 / Skills 设置对话框
├── af_theme.py                 # 共享主题配色
├── api_*.py                    # API 用量监控模块
├── updater.py                  # GitHub Releases 自动更新
└── assets/                     # 图标资源
```

## 📄 许可

MIT License
