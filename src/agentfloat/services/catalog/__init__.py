# -*- coding: utf-8 -*-
"""AgentFloat — Content Catalog（共享底座第 7 块）

远程可更新的内容清单：manifest + 分包 + 签名 + 缓存 + 三层合并。
首版只服务 Agent 目录；B 线的 ``sources.json``、C 线的 ``skill-index.json``
后续接同一套（避免三套下载器 / 三种签名）。

分层：
- ``schema``  结构与校验（AgentSpec / CatalogManifest）
- ``merge``   bundled < remote < user 三层合并
- 后续：``store``（本地缓存）/ ``client``（拉取）/ ``verify``（签名）/ ``api``（只读接口）
"""
from .schema import (  # noqa: F401
    GROUP_LABELS,
    GROUPS,
    SCHEMA_VERSION,
    AgentSpec,
    CatalogError,
    CatalogManifest,
    InstallStep,
    LaunchSpec,
    ShardRef,
    validate_agents,
)
from .merge import MergeResult, diff_specs, merge_layers  # noqa: F401
from .store import CatalogStore  # noqa: F401

__all__ = [
    "AgentSpec",
    "CatalogError",
    "CatalogManifest",
    "CatalogStore",
    "GROUP_LABELS",
    "GROUPS",
    "InstallStep",
    "LaunchSpec",
    "MergeResult",
    "SCHEMA_VERSION",
    "ShardRef",
    "diff_specs",
    "merge_layers",
    "validate_agents",
]
