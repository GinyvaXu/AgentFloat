# -*- coding: utf-8 -*-
"""pytest 共享配置：offscreen Qt + 单例 QApplication"""
import os

import pytest

# 必须在任何 PyQt 导入前设置（P2 起 UI 测试在无头模式运行）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
