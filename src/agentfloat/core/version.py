# -*- coding: utf-8 -*-
"""AgentFloat — 版本号与发布通道

版本号唯一来源：VERSION 文件（随包分发）。

发布通道（用户策略，2026-10-09 起）：
- **测试版（beta，默认）**：本地安装 + 仅 push 源码；不打 tag、不建 Release、不同步官网；
  UI 上版本号带「测试版」标记；**每次打开都视为第一次打开**（引导等首次体验会重播）。
- **正式版（stable）**：用户明确说「发布正式版」后才切换；打 tag、建 Release、
  同步官网镜像与公告。
"""
from agentfloat.core.paths import version_path

CHANNEL_BETA = "beta"
CHANNEL_STABLE = "stable"


def read_version():
    """读取 VERSION 文件；读取失败回退内置值（仅防御，正常构建必带文件）"""
    try:
        with open(version_path(), "r", encoding="utf-8-sig") as f:
            v = f.read().strip()
        if v:
            return v
    except Exception:
        pass
    return "1.3.0"


VERSION = read_version()

# 当前发布通道：测试版期间为 beta；正式发布时由用户确认后改为 stable
CHANNEL = CHANNEL_BETA


def is_beta():
    """是否处于测试版通道（测试版每次打开都当第一次打开）"""
    return CHANNEL == CHANNEL_BETA


def version_label(version=None):
    """展示用版本号：测试版带「测试版」后缀，例如 v3.10.0 测试版"""
    v = version or VERSION
    return "v%s%s" % (v, " 测试版" if is_beta() else "")
