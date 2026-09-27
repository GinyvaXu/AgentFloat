# -*- coding: utf-8 -*-
"""pytest 共享配置：offscreen Qt + 单例 QApplication"""
import os

import pytest

# 必须在任何 PyQt 导入前设置（P2 起 UI 测试在无头模式运行）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# PATCH 3.0.1：非 ASCII 项目路径下 PyQt5 的 Qt 插件前缀会解析成乱码，
# 导致 QApplication 创建卡死/崩溃；显式补插件搜索路径（不影响正常环境）
if not os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
    try:
        import PyQt5 as _pyqt5
        _plugins = os.path.join(os.path.dirname(os.path.abspath(_pyqt5.__file__)),
                                "Qt5", "plugins")
        if os.path.isdir(os.path.join(_plugins, "platforms")):
            os.environ.setdefault("QT_PLUGIN_PATH", _plugins)
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH",
                                  os.path.join(_plugins, "platforms"))
    except Exception:
        pass


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
