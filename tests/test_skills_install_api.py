# -*- coding: utf-8 -*-
"""Skill 车间安装/卸载封装的最小测试（不联网）。"""
from agentfloat.services.skills.report import install_skill, uninstall_skill


def test_install_requires_id():
    assert install_skill("")["ok"] is False


def test_uninstall_requires_id():
    assert uninstall_skill("")["ok"] is False
