# -*- coding: utf-8 -*-
"""AgentFloat — 版本号（唯一来源：VERSION 文件，随包分发）"""
from agentfloat.core.paths import version_path


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
