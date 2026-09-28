# 版本管理规范 — AgentFloat

## 版本号制度
采用 **语义化版本号 (Semantic Versioning)**：
```
v<MAJOR>.<MINOR>.<PATCH>

MAJOR — 重大架构变更或不兼容的 API 改动
MINOR — 新功能、优化（向后兼容）
PATCH — Bug 修复、安全补丁
```

### 版本历史

| 版本 | 说明 |
|------|------|
| v3.1.0 | **配置安全 + OpenCode 接入**：配置原子写入/读重试/不覆盖原文件（根治「设置无法保存」事故）；OpenCode CLI（默认 --continue）/ Desktop（新 app 启动器，主 Agent 可自主切换）/ Web（opencode serve）；Web Agent 通用「启动/状态/终止」（进程树 + 端口兜底），浮球右键菜单入口；新增 10 项测试（全量 169 项） |
| v3.0.2 | **崩溃修复**：修复更新检查 QThread 在结束时被释放导致的 qFatal 崩溃（Qt5Core.dll / 0xC0000409，表现为打开设置后闪退、设置无法保存）；全部 worker 改为线程结束后释放引用 + wait 兜底；Qt 致命消息自动转储 Python 线程栈；新增并存实例（旧版/调试版）警告；新增 3 项线程释放时序单测（全量 159 项） |
| v3.0.1 | **稳定性修复**：浮窗位置自愈（越界坐标收敛 / 离屏自动收回 / 托盘「重置浮窗位置」）；单实例守卫（双开不再产生双浮窗与热键冲突）；退出链路修复（会话报告与错误汇总恢复落盘、规避退出期 QThread 析构 qFatal 崩溃）；`faulthandler` 原生崩溃记录；非 ASCII 路径 Qt 插件与构建兜底；新增 11 项位置收敛单测（全量 156 项） |
| v3.0.0 | **P3 测试/瘦身/打磨**：pytest 测试体系 146 项（覆盖率 43%，纯逻辑模块 75-100%）+ smoke_test.py 构建冒烟脚本；默认 onedir 打包（启动 4.3s→1.8s）+ 安全裁剪 24.6MB（141.9MB）；Web 前端 ES 模块化（util/install 拆分，浏览器实测 0 报错）；安装页并行探测 + TTL 缓存（8.4s→12ms）；结构分层（src/agentfloat）与死代码清理（-3.3k 行）收敛 |
| v2.4.0 | **P2 交互与视觉重写**：交互状态机（拖拽不误弹/贴边唤出抑制/点按即时反馈/退出弹性收拢）；弹簧动效引擎；环菜单三件套（弹簧展开/磁吸选中/按压微光）；浮球重绘（深色玻璃+渐变描边）+ 固定窗口三态位图（解决掉帧）；Web 壳静默预热（设置/快报秒开）；token 对齐 ProjectDock |
| v2.3.0 | **P1 结构重构**：死代码清除 -3329 行（SettingsDialog 等）；全库迁入 src/agentfloat 包分层（根入口 5028→24 行）；主题 token 唯一化；路径解析收敛；构建链适配 |
| v2.2.x | Web 套壳（设置/API 用量/AI 快报）+ Agent 安装模块 + DeepSeek Harness 兼容 + 启动动画与加载指示器 |
| v2.1.0 | 设置 / API 用量 / AI 快报 迁移为 Web 套壳（FastAPI + pywebview + 原生前端，参考 ProjectDock）；新增 DeepSeek Harness（dsh）Web UI 启动兼容（统一 Agent 框架含 claude/codex/pi/dsh，launcher 字段区分终端/Web 启动）；dsh 自动迁移进内置预设；构建脚本纳入 web 资源与 fastapi/uvicorn/pywebview 依赖 |
| v1.6.0 | 新增 Pi Coding Agent 启动兼容（pi.dev 多模型终端编码智能体）；内置 Agent 迁移机制：升级后自动追加新内置预设，不覆盖用户自定义 |
| v1.4.0 | 环绕菜单吸附对齐修复（展开时浮窗居中于圆环，关闭后恢复原位）；AI 快报面板尺寸/字号可配置（设置新增窗口宽高与正文字号），启动与每日定时自动生成后自动弹出快报窗口（可关闭）；设置页 API 用量与 AI 快报统一风格（去外边框、关注主题全平铺显示并修复黑框黑底）；「应用」改为生效并关闭；「保存」仅在有改动时可点，保存后弹出修改摘要 toast |
| v1.3.0 | 安装/卸载/自动更新链路重构（参考诺丁汉警长桌游项目）：Inno Setup 按用户级安装、支持静默自动更新；多源检查更新（update.json 清单 + jsDelivr CDN + 国内 GitHub 代理 + Releases API）友好错误码；静默重装并重启 + boot 验证；mirror.json 自建镜像。设置「关于」页新增检查更新/下载更新/更新并重启。修复深色模式 API 用量与 AI 快报页白框、浅色模式输入框边框不可见；关于页重建（使用教程/下载链接/个人网站）；修复 AI 快报生成超时崩溃（返回部分结果） |
| v1.2.2 | 效率工具：剪贴板历史（轮询采集/面板复制/单条删除/清空）+ 自定义命令面板（新建/编辑/删除/运行/示例，窗口/终端/后台三种启动方式）；修复吸附隐藏与环绕菜单冲突（打开菜单与按压前自动弹出）；边缘检测条加宽 + 滑动提速，改善点击快捷打开 Agent；快报启动自动生成后自动弹窗（可设置关闭）、面板精简并默认隐藏历史；扇形菜单图标/字体/圆点随扇区数自适应防重叠；移除未读角标；自动更新链路复核（已是最新时不再提示） |
| v1.2.1 | AI 快报体验优化：关注主题定向偏好（预设/权重/彩色标注）、面板毛玻璃标题栏与分类彩色卡片排版、生成加载条；设置「应用/保存/取消」逻辑重构；未读角标美化（渐变红点） |
| v1.2.0 | AI 快报上线：多源聚合（HN/GitHub Trending/少数派/量子位/arXiv）+ 本地 Agent 摘要 + 无边框面板 + 定时/启动补生成 + 未读红点角标 + 托盘通知 |
| v1.1.0 | 环绕菜单扇区模块化（4/6/8 扇区自选功能，Agent/Skills/API/设置/AI 快报预留/退出）；修复灰色覆盖层乱飞根因（arcTo 角度约定错误）；设置页新增扇区数量与槽位动作下拉；AI 快报调研报告 + 精美 README |
| v1.0.9 | 扇形菜单命中/DPI 修复（展开可点击启动、关闭缩放同步）；Skills 手动触发说明完整展示；API 余额一键跳转平台网页；退出全新收拢动画 |
| v1.0.8 | 悬停灰显 + 按压缩放感；拖拽与环绕菜单冲突修复（拖拽冷却 500ms）；设置改为顶部标签页布局；默认启动方式支持自定义程序路径；菜单关闭向中心收拢动画 |
| v1.0.7 | 修复悬停菜单消失/动画抽搐；点击菜单外立即关闭 + spring 入场；翻译 skill 自动部署 + 新装 skill 自动触发翻译；辅助窗标题栏毛玻璃/关闭按钮 B/分类树美化与动画 |
| v1.0.6 | 环绕菜单整环重绘（统一配色/修复扇区重叠/2秒宽限关闭）；Skills 分类树 + 可见关闭按钮；余额角标常显；移除 AI 自动首启 |
| v1.0.5 | 本地 AI 服务（API 余额配置 + Skills 翻译）+ 悬停菜单/辅助窗/触发指令修复 |
| v1.0.4 | 修复环绕菜单弹不出；Skills 中英对照 + 去除 AI 优化 |
| v1.0.3 | 修复环绕菜单绘制崩溃（QPointF 解包） |
| v1.0.2 | 错误日志改为关闭程序时统一导出汇总报告 |
| v1.0.1 | 修复悬停动画失效；新增报错日志导出 |
| v1.0.0 | AgentFloat 首个版本：通用多 Agent 启动 + 环绕菜单 + Skills 辅助窗 |

---

## 目录结构（v3 重构后）

```
AgentFloat/
├── agent_float.py              # 启动入口（源码在 src/，本文件仅 24 行兼容层）
├── src/agentfloat/
│   ├── app.py                  # 应用引导（托盘/热键/生命周期/更新链路）
│   ├── core/                   # 路径/配置/主题 token/日志/自启/启动器/注册表/版本
│   ├── ui/                     # 浮球/交互状态机/环菜单/弹簧动效/面板/启动动画
│   │   └── panels/             # Skills / 剪贴板 / 命令 / 喝水（Qt 轻面板）
│   ├── services/               # API 监控 / AI 快报 / Skills / 喝水 / 更新 / dsh / 安装
│   └── webshell/               # FastAPI 后端 + 事件桥 + pywebview 窗口（含静默预热）
├── web/                        # Web 控制台前端（HTML/CSS + ES Module JS）
├── tests/                      # pytest 测试（146 项）+ 覆盖率配置
├── smoke_test.py               # 构建产物冒烟（隔离 APPDATA：存活/日志/启动耗时）
├── config.example.json         # 配置模板（本地 config.json 不入库）
├── VERSION                     # 版本号唯一来源（core/version.py 读取）
├── build_debug.py              # 调试版构建（默认 onedir；--onefile 可选）
├── build_exe.py                # 正式版构建（默认 onedir；--onefile 可选）
├── build_setup_exe.py          # 安装包构建（Inno Setup，适配 onedir/onefile）
├── build_utils.py              # 构建辅助（版本读取/旧版归档/onedir 安全裁剪）
├── agent_float.py / AgentFloat.spec
├── versions/                   # 历史版本归档（本地保留，不入库）
├── dist/                       # 构建产物（当前工作副本；onedir 目录 + 安装包）
└── assets/                     # 图标等静态资源
```

---

## 发布流程

### 1. 开发阶段
- 每次构建 debug 版：`python build_debug.py` → `dist/AgentFloat_debug/AgentFloat_debug.exe`（onedir，默认）
  - 单文件便携版可选：`python build_debug.py --onefile` → `dist/AgentFloat_debug.exe`
- 构建后冒烟：`python smoke_test.py`（隔离 APPDATA 运行 12 秒：进程存活 + 日志无 ERROR + 启动耗时）
- 构建前 `build_utils` 自动把被覆盖的旧版产物归档到 `versions/v<旧版本>/dist/`（支持目录）
- 版本号唯一来源：根目录 `VERSION`（`core/version.py` 读取；禁止在源码/安装器手写第二份）

### 2. 版本升级（新功能 / 修复）
```
1. 更新 VERSION 文件 + CHANGELOG.md
2. 运行 build_debug.py 构建调试版（自动归档旧版）+ smoke_test.py 冒烟
3. 用户实测确认稳定后：python build_exe.py（正式版）+ python build_setup_exe.py（安装包）
4. 将正式产物归档到 versions/v<version>/dist/
5. 更新 VERSIONING.md 版本历史与当前版本
```

### 3. 发布后
- 打 Git tag: `git tag v<version>`
- 确认 `versions/v<version>/dist/` 包含 `AgentFloat.exe` 与 `AgentFloat_Setup.exe`

---

## CHANGELOG 格式

```markdown
# v1.0.1 — YYYY-MM-DD

## 安全修复 / Bug 修复 / 新功能 / UX 改进
- 具体变更描述
- **根因**：问题根因分析
- **修复**：解决方案说明

## 文件变更
| 文件 | 变更 |
|------|------|
| `agent_float.py` | 具体改动 |
| `VERSION` | x.y.z-1 → x.y.z |

## 构建产物
- `AgentFloat.exe` — 正式版
- `AgentFloat_debug.exe` — 调试版（含会话/崩溃报告）
- `AgentFloat_Setup.exe` — 安装包
```

---

## 归档规则

| 规则 | 说明 |
|------|------|
| 每次发布时必须归档 | 包含源文件、安装包、更新日志 |
| 归档内容 | `src/`（所有 `.py` `.json` `.iss` `.spec`）、`installer/`、`dist/`、`CHANGELOG.md` |
| 归档不包括 | `build/`、`__pycache__/`、`*.pyc` |
| 构建产物 | **必须**归档到 `versions/v<version>/dist/` |
| 命名规范 | 目录名严格使用 `v<MAJOR>.<MINOR>.<PATCH>` 格式 |

---

## 当前版本

**v3.1.0** — 2026-09-28（配置安全 + OpenCode 接入）

- 配置原子写入（临时文件 + `os.replace`）+ 读取重试 + 解析失败不覆盖原文件：根治「设置无法保存」（保存与读取并发被误判损坏后清空）
- OpenCode 全系接入：CLI（默认 `--continue`）/ Desktop（`app` 启动器，主 Agent 可自主切换）/ Web（`opencode serve`）
- Web Agent 通用化：任意网页模式 Agent 支持启动/状态/终止（结束进程树 + 端口校验），入口在浮球右键菜单「Web Agent」

详见 `CHANGELOG.md`；v3.0.0 的 P1–P3 重构详情见 `docs/v3重构方案.md`。历史版本说明见 `versions/v<版本>/`。

- 修复悬停菜单消失（悬停离开不再强行关闭）与动画抽搐（防重入）；点击菜单外立即关闭 + OutBack 轻微过冲入场 + 淡出收尾
- 翻译 skill 自动部署；新装 skill 自动触发翻译（首次跑基线，可在设置中关闭）
- 辅助窗：毛玻璃标题栏 + 精致关闭按钮 B + 分类树美化与展开动画

见 `versions/v1.0.7/CHANGELOG.md`。
