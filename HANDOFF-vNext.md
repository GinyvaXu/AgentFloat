# HANDOFF · vNext（A 线定稿，待开工）

> 2026-10-23 ｜ 上游文档：`docs/2026.10.21-AgentFloat-vNext-大版本规划-风暴稿.md`（v1.0）
> 本文件是**新批次**的交接说明；前端精修批次的交接仍在 `HANDOFF.md`，两者互不覆盖。
> 读者：下一个接手本项目的会话 / 协作者。看完这页就能直接开工。

---

## 0. 30 秒结论

- **方案侧已就绪**：vNext 四条线（A Agent Hub / B 日报 2.0 / C Skill 车间 2.0 / D 进度面板）方案全部收口；A 线名单与分发已定稿，决策门 **G0 已通过**。
- **仓库侧还没就绪**：有一盏红灯（已定位，非业务 bug）、一个已提交未构建的版本（v3.16.3）、一个未收尾的前端批次（B3）。
- **建议开工顺序**：清障（约 1 小时）→ P1 第一刀（Content Catalog 骨架）→ Registry 数据 → 安装适配器 → Hub 页面。
- **开发时间线（archify）**：每次提交后重跑更新 `.archify/timeline-dev-*/agentfloat-dev-timeline.html`（已完成 / 开发中 / 待开发）；当前版本见 `.archify/timeline-dev-20261026-130332/`。

---

## 1. 当前仓库状态

| 项 | 值 |
|---|---|
| `VERSION` | **3.16.4**（已构建、已装机；P1 Catalog 地基尚未接 UI，未占版本号） |
| 已装机版本 | v3.16.4（2026-10-23 15:03 启动，日志 `当前 v3.16.4`） |
| 工作树 | 两份风暴稿未提交：`docs/2026.10.19-...进度面板...md`（M）、`docs/2026.10.21-...vNext...md`（??）；`.workbuddy/` 为本机记忆目录，不入库 |
| 分支 | 单 `main`，无 develop/feature 分支 |
| 构建机 | `C:\AIAgentBase\AgentFloat_build`（独立 venv，中文路径会坑，见 §6） |

---

## 2. 开工前必须先清的三件事（2026-10-23 已全部清完）

### 2.1 红灯：`test_interaction_flow`（已修，提交 `6b3ce2b`）

`tests/test_floatball_integration.py::test_interaction_flow` 断言「单击应弹语录」，实际触发了 `launch_requested`。

**根因不是业务 bug**，是测试读了仓库根的真实 `config.json`：

```json
"quotes": { "enabled": true, "on_click": false }
```

`on_click=false` 时 `show_quote_window()` 返回 `False`，`floatball.py:2310` 按设计回退到启动 Agent。测试却按默认值断言，于是红灯。

**已采用的修法**：`ball` fixture 构造 `FloatingWidget` 后强制 `w.config["quotes"]["on_click"] = True`（仅内存，`save_config` 已 mock）。业务逻辑未改。
修完全量 409 项全绿（含新增 catalog 测试）。

### 2.2 v3.16.3 / v3.16.4 已构建装机

- v3.16.3：源码 + 构建产物在 `versions/v3.16.3/dist/`；**装机已被 v3.16.4 覆盖**。
- v3.16.4（B3 前端收尾）：已装机并启动验证，日志 `当前 v3.16.4`；产物 `versions/v3.16.4/dist/AgentFloat-Setup-3.16.4.exe`。
- 构建注意：`prune_onedir` 裁 Qt 翻译时会撞批量删除保护（92 个 .qm 只删掉 17 个），脚本以退出码 1 结束但**产物完整**；需手工补 `dist/.build_version`。详见 §6.8。

### 2.3 B3 收尾（已完成）

- ✅ Web `confirmDialog()` 替换原生 `confirm()`（`install.js`）
- ✅ 加载骨架 + 15s 超时、错误卡片 + 重试（此前「重试/查看详情」按钮没有事件）、空态行
- ⏸（可选，较费时）Web 快报页 C 分栏，详见 `HANDOFF.md` 第 1 条

> P1 Catalog 第一刀（schema / merge / store + 41 项单测）已完成，见 §7 打钩清单。

---

## 3. P1 施工图（A 线）

### 3.1 模块骨架

```
src/agentfloat/services/catalog/
    __init__.py
    schema.py        # AgentSpec / CatalogManifest 的 dataclass + 校验（不引第三方 validator）
    store.py         # 本地缓存：%LOCALAPPDATA%/AgentFloat/catalog/，原子写 + last-known-good
    client.py        # manifest 拉取：ETag / TTL 24h / 3s 超时 / mirrors 依次回退
    merge.py         # bundled < remote < user 三层合并，按 id
    verify.py        # 签名校验（Ed25519）+ schema 白名单
    api.py           # 对外只读接口：list_agents() / get_agent(id) / refresh(force=False)

catalog/agents/                  # 随包发布的内置目录（18+1 条）
    claude.json  codex.json  antigravity.json  opencode.json  aider.json
    goose.json   crush.json  cursor-cli.json    copilot.json   pi.json
    qwen.json    kimi.json   dsh.json  codebuddy.json  qoder.json
    cursor-desktop.json  windsurf.json  trae.json  amp.json

tools/catalog_cli.py             # af catalog verify / publish / promote（见 §3.3）
tests/test_catalog_*.py          # schema / merge / client 回退 / 签名
```

### 3.2 数据结构（冻结版）

一条 Agent 记录（字段只增不删，带 `schemaVersion`）：

```jsonc
{
  "schemaVersion": 1,
  "id": "opencode",
  "name": "OpenCode",
  "vendor": "Anomaly",
  "group": "intl-cli",              // intl-cli | cn-cli | desktop | wsl
  "platforms": { "windows": "native", "macos": "native", "linux": "native" }, // native|wsl|none
  "install": [
    { "type": "npm",    "packageOrUrl": "@opencode/cli", "verify": "opencode --version" },
    { "type": "script", "url": "https://opencode.ai/v2/install", "reversible": false }
  ],
  "launch": {
    "command": "opencode",
    "variants": [ { "id": "v2", "package": "@opencode/cli", "minVersion": "2.0.0" } ],
    "modes": ["interactive", "headless", "desktop"],
    "headless": { "args": ["run", "--format", "json"], "verified": false }
  },
  "capability": { "headless": true, "mcp": true, "skills": true, "resume": true },
  "health": { "versionCmd": "opencode --version", "versionPattern": "v?(\\d+\\.\\d+\\.\\d+)" },
  "status": "active",                // active | deprecated | eol
  "statusNote": "",
  "verifiedAt": "2026-10-23",
  "source": "https://github.com/anomalyco/opencode"
}
```

四条硬规则：
1. `platforms` 是**三值枚举**，不是布尔——Amp 属 `windows: "wsl"`；
2. **一个产品一条记录**，版本差异放 `launch.variants[]`；
3. `status` 三态：`deprecated` = 还能用但不推荐，`eol` = 禁止启动只留迁移说明；
4. `verifiedAt` 超过 90 天在 UI 标黄；`supersedes` / `supersededBy` 表达继任（gemini→antigravity、kimi-cli→kimi-code、Pi 旧包→新包）。

**冻结名单**（18 首批 + 1 WSL）见风暴稿 §3「Round A3′ 合并裁定」表格，逐条含 Windows 首选安装命令。

### 3.3 目录分发（Content Catalog）

- **托管**：`agentfloat.ginyva.site/catalog/`（Cloudflare Pages，主）→ `dl.ginyva.site/catalog/`（R2 镜像）→ GitHub raw（兜底）。
- **粒度**：`manifest.json`（~2KB，`catalogVersion` 单调递增、`minAfVersion`、`shards` 哈希文件名、`mirrors[]`、`signature`）+ 按分组分包 `intl-*.json` / `cn-*.json` / `desktop-*.json` / `wsl-*.json`。
- **刷新**：启动后异步拉 manifest（ETag、24h TTL、3s 超时），失败静默；打开 Hub 或安装时才拉分包。
- **信任**：Ed25519 签名，公钥内嵌客户端；**远程只能覆盖易变层**（安装方式 / 包名 / 命令名 / headless / 版本区间 / status），稳定层（id、名称、图标、描述）只能随包发。
- **发布流水线**：

```bash
python tools/catalog_cli.py verify          # 并发查 npm/winget/官方页，输出 diff
python tools/catalog_cli.py publish --channel beta    # 校验 schema → 签名 → 写 manifest
python tools/catalog_cli.py promote --channel stable  # beta 用一周没问题再提
```

> `verify` 不是锦上添花：没有它，改 18 条 JSON 要半天，目录会退化成「半年更新一次」。这一刀必须一起做。

### 3.4 M1 验收

- Claude Code / Codex / OpenCode / dsh 四个**真实安装 + 启动**跑通；
- 安装失败可回滚（备份 + 恢复）；
- 版本检测准确；
- **同一任务分别走「远程目录」与「内置目录」，合并结果一致**；
- 断网时 AF 正常启动，Hub 显示内置目录。

---

## 4. 命令与环境

```bash
# 测试（工作树 venv）
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest tests/test_catalog_schema.py -q -s

# 构建 + 装机（ASCII 联接路径，中文路径会炸）
cd C:\AIAgentBase\AgentFloat_build
.venv\Scripts\python.exe build_exe.py
.venv\Scripts\python.exe build_installer.py     # 产物 → versions/v<ver>/dist/

# Web 预览（无构建）
python -m http.server 8126 --directory src/agentfloat/webshell
```

装机流程：`taskkill /IM AgentFloat.exe` → 旧版 `unins000.exe /VERYSILENT` → 新版 `/VERYSILENT` → 启动 → 看 `%APPDATA%\AgentFloat\logs\AgentFloat.log`。

---

## 5. 可用技能（本机 opencode 14 个，已加载）

路径 `C:\Users\zhenl\.config\opencode\skills\`。按需触发，不用的不要硬套。

| 技能 | 用途 | 在本项目什么时候用 |
|---|---|---|
| **ginyva-release** | Ginyva 系项目迭代与发布铁律、构建/装机/Release 流程 | 每次构建、发版、改 VERSION/CHANGELOG |
| **win-cn-env** | Windows 中文环境编码守则（UTF-8/BOM/PowerShell 5.1/时区） | 写任何脚本、批量处理中文文件 |
| **super-brainstorm** | 多轮快问快答 + 路线图 + 决策门 + 名单时效核查 | 方案阶段（本次 vNext 即由此产出） |
| **webapp-testing** | Playwright 驱动本地 Web 应用、截图、看控制台日志 | 改 Web 控制台 / 安装页 / 日报三栏后验收 |
| **motion-ui-design** | 帧率无关动画模型、微交互词汇库、反模式清单 | 浮动球 / 面板动效调手感 |
| **icon-assets** | 本机图标库检索（3.7 万 SVG / 14 集合）与许可核对 | Agent 卡片图标、安装页品牌 Logo |
| **cn-deliverables** | 中文交付规范（报告精简、md/docx/pdf 产出、分享包） | 写交付报告、导出文档 |
| **humanizer** | 去 AI 味改写（少用排比、破折号、套话） | 官网文案、更新说明、README |
| **ginyva-site** | 工具站架构与运营（Pages 部署、R2 镜像、后台、统计） | **发布 catalog 到 agentfloat 子域时** |
| **ginyva-promo-art** | 官网素材、朋友圈九宫格、OG 卡（Impeccable 质量门） | 正式版宣发 |
| **ginyva-promo-video** | 产品发布片 / 功能演示短片（HyperFrames） | 正式版视频 |
| **onetake** | 单 HTML 时间函数式动效短片（不依赖 HyperFrames/Remotion） | 15–30s 功能演示、无录屏复刻 UI |
| **drawio-skill** | 生成可编辑 `.drawio`（架构/UML/时序/泳道） | 需要给人改的架构图（内部讨论用 archify/HTML 更快） |
| **personal-archive** | 用户的 DPAPI 加密个人档案（履历/偏好/目标） | 需要用户画像时；**禁止外泄** |

---

## 6. 已知坑

1. **中文路径 + PyInstaller**：构建一律走 `C:\AIAgentBase\AgentFloat_build`（ASCII 联接），不要在 `Project3-AgentFloat克隆仓库` 里直接构建。
   **但 Git Bash 的 `cd` 会把 cwd 解析成中文真路径**，触发 `check_ascii_build_path` 直接退出——构建必须在 PowerShell（或 cmd）里执行，`(Get-Location).Path` 应显示 `C:\AIAgentBase\AgentFloat_build`。
2. **测试吃真实 config**：`FloatingWidget()` 默认读根 `config.json`；任何涉及语录/启动行为的测试都要先隔离配置（本次红灯就是这个）。
3. **PowerShell 5.1**：无三元运算符；`.ps1/.bat` 不写中文字面量；`Select-Object -First N` 会杀上游进程；内联 `node -e` 反斜杠会被吃 → 写 `.mjs`。
4. **Web 整页 `innerHTML` 重渲染**（`app.js:1076` 附近）会丢焦点与滚动位置——详情切换只重绘详情容器。
5. **推送**：GitHub 走代理时 `GIT_CONFIG_GLOBAL=C:\Users\zhenl\AppData\Local\Temp\opencode\gitconfig-push`；失败不要反复重试，列现状等用户决定。
6. **不主动 push / 不删文件 / 不覆盖 versions**（AGENTS.md 强制）；本地迭代（测试→构建→装机）已授权自动执行。
7. **AI 操作日志**：每个任务完成写 `logs/ai/*.json`（`python -m projectdock.cli log ...`），不写视为未完成。
8. **构建收尾会被批量删除保护拦下**：`build_exe.py` 最后 `prune_onedir()` 要删 92 个 Qt 翻译文件（`dist/AgentFloat/_internal/PyQt5/Qt5/translations`），超过单轮删除阈值 → 删掉 17 个后中止，脚本退出码 1，`write_build_version()` 没执行。
   - 产物本身完整，可继续 `build_installer.py`；
   - 需手工补 `dist/.build_version`（内容为新版本号）；
   - 体积比彻底裁剪多约 8MB。**要彻底裁剪需用户授权一次批量删除**，别自己绕过安全闸。
9. **装机在本会话必须走"沙箱外 + PowerShell"**：Bash 里直接跑 Setup 会被 SIGTERM 掐掉、且不产生 `/LOG`；PowerShell 的 `Start-Process -PassThru`（沙箱外）可用。卸载器同理。覆盖安装（不先卸载）也能成功。

---

## 7. 下一步打钩清单

- [x] 修 `test_interaction_flow` 夹具隔离，全量 pytest 绿（2026-10-23，`6b3ce2b`）
- [x] 构建 + 装机 v3.16.3，健康检查通过（后由 v3.16.4 覆盖）
- [x] B3 收尾（`confirmDialog` / 骨架 / 错误卡 / 空态 + 请求超时）——v3.16.4 已装机
- [x] `catalog/schema.py` + 单测（AgentSpec 校验、三值 platforms、variants）——21 项
- [x] `catalog/merge.py` + 单测（bundled < remote < user）——13 项
- [x] `catalog/store.py` + 单测（原子写 / last-known-good / 分包哈希 / TTL）——7 项
- [ ] `catalog/client.py` + 单测（ETag / 超时 / mirrors 回退 / 断网）
- [ ] `catalog/agents/*.json` 18+1 条（按风暴稿冻结表逐条填）
- [ ] `tools/catalog_cli.py verify`（npm + winget 探测，输出 diff）
- [ ] 签名链路（Ed25519）+ 公钥内嵌 + 校验失败整份拒绝
- [ ] `catalog/api.py` 只读接口（list_agents / get_agent / refresh）
- [ ] Pages 目录上线（`agentfloat.ginyva.site/catalog/`）+ R2 镜像
- [ ] M1 验收：四个真实 Agent 安装/启动/回滚
