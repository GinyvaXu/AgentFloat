# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skills 中英对照翻译表

内置常见 skills 的中文名称与简介；未收录项由 Skills 辅助窗回退显示原文。
键：skill 名称（或目录名）；值：(中文名, 中文简介)
"""
import json
import os
import sys

SKILL_ZH = {
    "agent-browser": ("浏览器自动化", "AI 代理专用的浏览器自动化命令行工具：导航网页、填写表单、点击按钮、截图、提取数据、测试 Web 应用。"),
    "caveman": ("穴居人模式", "极简压缩沟通模式，大幅减少输出字数（实测省 65%），保持技术准确性；支持 lite/full/ultra 等强度。"),
    "claudefloat-dev": ("ClaudeFloat 开发规范", "ClaudeFloat 浮窗工具开发全流程规范：版本管理、PyInstaller 构建、代码归档、UI 设计审查、文档生成。"),
    "find-skills": ("发现 Skills", "帮助用户发现并安装 Agent Skills：回答「怎么用某功能」「找 skills」等需求，扩展智能体能力。"),
    "godot-assets": ("Godot 视觉资源", "Godot 游戏的视觉质量体系：用着色器、粒子、程序化绘制创建精致分层视觉效果，兼顾性能。"),
    "godot-builder": ("Godot 构建主管", "Godot 4 游戏生成的总路由与编排器，负责统筹 AI 游戏生成全流程，只做 Godot 4 项目。"),
    "godot-dev": ("Godot 插件开发", "用于开发 AI Game Builder 插件本身，而非做游戏；指导修改插件 skills、MCP 服务、Godot 插件。"),
    "godot-director": ("Godot 游戏导演", "游戏项目管理角色：负责游戏生成的需求拆解、方案规划与资源协调，把控整体方向。"),
    "godot-distiller": ("Godot 需求蒸馏", "把需求（GDD/PRD/功能列表）提炼为可执行的构建方案，防止范围失控，产出单会话可完成的计划。"),
    "godot-effects": ("Godot 音效特效", "游戏音频、视觉特效、补间动画与手感打磨：爆炸、音效反馈、粒子、UI 过渡等。"),
    "godot-enemies": ("Godot 敌人系统", "游戏敌人 AI、刷怪系统、群体行为与物理碰撞，为 Godot 4 提供完整脚本方案。"),
    "godot-gdscript": ("GDScript 语言规范", "GDScript 语言模式、惯用法与常见错误修正：编写、语法检查、调试脚本时的最佳实践。"),
    "godot-init": ("Godot 项目初始化", "从零搭建 Godot 4 项目：初始化文件夹结构、配置 project.godot、验证项目可用性。"),
    "godot-ops": ("Godot 运维调试", "MCP 工具操作：运行游戏、读取错误、重载文件系统、迭代修复的「开发-构建-修复」循环。"),
    "godot-physics": ("Godot 物理系统", "碰撞层、碰撞体、物理关节与物理运动模式：配置冲突、创建碰撞体、调试物理问题。"),
    "godot-player": ("Godot 玩家控制器", "各类型游戏的玩家控制器实现：移动、跳跃、射击、交互，覆盖常见玩法与手感调优。"),
    "godot-polish": ("Godot 游戏打磨", "游戏手感和视觉体验打磨：果汁感（game feel）、动效、UI 过渡与细节抛光。"),
    "godot-scene-arch": ("Godot 场景架构", "场景搭建与节点层级架构设计：程序化创建与手动布局的取舍、节点组织规范。"),
    "godot-templates": ("Godot 模板库", "按类型分类的游戏模板：每个模板包含完整文件清单、目录结构、核心机制。"),
    "godot-ui": ("Godot UI 系统", "Godot 4 的 UI 系统：HUD、菜单、弹窗、血量条、屏幕过渡、对话系统等。"),
    "project-git-mgmt": ("项目 Git 管理", "项目 Git 仓库的初始化、分支、提交、发布等管理规范。"),
    "create-skills": ("创建 Skills", "用户想创建新的 Codex Skill、编写 SKILL.md、把工作流变成可复用 Skill、构建自定义自动化时使用。"),
    "ui-ux-pro-max": ("UI/UX 设计智库", "Web/移动端 UI/UX 设计智能库：50+ 风格、161 配色、57 字体搭配、99 UX 准则、25 图表类型。"),
    "整理工作区": ("工作区整理", "按 ORGANIZATION_STANDARD.md 规范分析并整理工作区文件夹结构：归类散落文件、建项目骨架、多版本处理、清理空文件。"),
    "workspace-organizer": ("工作区整理", "按 ORGANIZATION_STANDARD.md 规范分析并整理工作区文件夹结构：归类散落文件、建项目骨架、多版本处理、清理空文件。"),
    "animate": ("动画制作", "从零构建动画：先判断是否该动、目的、工具、属性、曲线与时长，再决定呈现方式。"),
    "animation-vocabulary": ("动画词汇表", "反向查询术语表：把模糊的动效描述翻译成准确术语（弹跳打开→Pop in，iOS 橡皮筋→Rubber-banding）。"),
    "apple-design": ("Apple 设计语言", "Apple 的界面设计与流畅物理动效方法论（面向 Web）：手势驱动 UI、弹簧动画、拖拽/滑动交互、动量和惯性。"),
    "emil-design-eng": ("设计工程哲学", "Emil Kowalski 的 UI 打磨哲学：组件设计、动画决策、让软件「感觉好」的隐形细节。"),
    "find-animation-opportunities": ("寻找动画机会", "只读审查代码库或 UI 中「该动没动」的地方，提出精确动效方案，不实现。"),
    "firecrawl": ("Firecrawl 抓取", "通过 Firecrawl CLI 搜索、抓取、交互网页：研究主题、查找资料、抓取页面内容。"),
    "firecrawl-agent": ("AI 自主抓取", "AI 驱动的自主数据提取：导航复杂网站，返回结构化 JSON。"),
    "firecrawl-crawl": ("全站爬取", "批量提取整个网站或站点区块内容：抓取全部页面并跟进链接。"),
    "firecrawl-download": ("网站下载", "把整个网站下载为本地文件：Markdown、截图或多种格式，供离线使用。"),
    "firecrawl-interact": ("浏览器交互", "在已抓取页面上操控实时浏览器会话：点击、填表、导航、用自然语言提取数据。"),
    "firecrawl-map": ("站点地图发现", "发现并列出网站全部 URL，支持过滤与搜索，梳理站点结构。"),
    "firecrawl-monitor": ("内容变更监控", "检测网站内容变化并通过 Webhook 或邮件通知，无需定时任务脚本。"),
    "firecrawl-parse": ("本地文件解析", "把本地 PDF、DOCX、DOC、XLSX、XLS、HTML 高效转换为干净的 Markdown 存到磁盘。"),
    "firecrawl-scrape": ("单页抓取", "从任意 URL 提取干净 Markdown，支持 JS 渲染的 SPA 页面。"),
    "firecrawl-search": ("搜索+全文提取", "网络搜索并提取完整页面内容：查资料、找新闻、发现新信息源。"),
    "grill-me": ("拷问式审问", "用不间断的尖锐提问打磨方案或设计，帮助把想法思考得更扎实。"),
    "grill-with-docs": ("带文档审问", "结合文档的拷问式审问：在审问中自动查阅相关资料，让论证更严谨。"),
    "improve-animations": ("动效改进审计", "以资深动效顾问视角审查代码动效，产出分级审计与可执行改进方案，只读不改。"),
    "karpathy-guidelines": ("Karpathy 编码准则", "减少常见 LLM 编码错误的规范：避免过度复杂化、外科手术式改动、暴露假设、定义可验证标准。"),
    "pick-ui-library": ("UI 库选择", "为前端任务选择合适库：数字输入、验证码、命令菜单、拖拽、统计图表、样式等，仅在选择时触发。"),
    "prototype": ("原型对比", "为一个 UI 片段构建多个风格迥异的版本，可视化切换预览，选出最合适的那个。"),
    "review-animations": ("动效代码审查", "按 Emil Kowalski 设计工程的高标准审查动效代码，默认挑刺，达标才放行。"),
    "imagegen": ("图像生成", "任务需要 AI 生成位图视觉素材时使用：照片、插画、纹理、精灵图、原型图、透明底素材等。"),
    "openai-docs": ("OpenAI 官方文档", "解答 OpenAI 产品/API 构建问题、Codex 选型、官方文档查证与引用时使用。"),
    "plugin-creator": ("插件创建器", "为 Codex 创建插件目录骨架：plugin.json、清单、可选文件，默认写入个人市场。"),
    "review-agent": ("缺陷优先审查", "对指定代码变更做只读、缺陷优先的审查，先找问题再给结论。"),
    "skill-creator": ("Skill 创建指南", "创建或更新 Skill 的指南：专用知识、工作流、模板，让智能体能力可扩展。"),
    "skill-installer": ("Skill 安装器", "把 Codex Skills 安装到 $CODEX_HOME/skills：从精选列表或 GitHub 仓库安装。"),
}

_ALIAS = {
    "workspace-organizer": "整理工作区",
}


def _custom_path():
    """AI 自检服务生成的补充翻译文件（用户目录）"""
    if getattr(sys, "frozen", False):
        d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AgentFloat")
    else:
        d = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(d, "skills_translations_ai.json")


def _load_custom():
    """懒加载 AI 生成的补充翻译：{"skill-name": ["中文名", "中文简介"]}"""
    cached = getattr(_load_custom, "_cache", None)
    if cached is not None:
        return cached
    data = {}
    try:
        with open(_custom_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            data = {k: v for k, v in raw.items() if isinstance(v, (list, tuple)) and len(v) >= 2}
    except Exception:
        pass
    _load_custom._cache = data
    return data


def get_zh(skill_name, dir_name=None):
    """返回 (中文名, 中文简介)；未收录返回 (None, None)。
    AI 补充翻译优先于内置表，便于本地自检服务持续扩充。"""
    key = skill_name
    custom = _load_custom()
    if key in custom:
        return custom[key][0], custom[key][1]
    if key in SKILL_ZH:
        return SKILL_ZH[key]
    if key in _ALIAS and _ALIAS[key] in SKILL_ZH:
        return SKILL_ZH[_ALIAS[key]]
    if dir_name and dir_name in SKILL_ZH:
        return SKILL_ZH[dir_name]
    if dir_name and dir_name in custom:
        return custom[dir_name][0], custom[dir_name][1]
    return None, None
