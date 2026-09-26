# -*- coding: utf-8 -*-
"""AgentFloat — 通用对话框"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox


def _update_box(parent=None, icon=QMessageBox.Information, title="", text="",
                buttons=QMessageBox.Ok, default=QMessageBox.Ok):
    """自动更新相关消息框（置顶，避免被其他窗口遮挡）"""
    box = QMessageBox(icon, title, text, buttons, parent)
    box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
    box.setDefaultButton(default)
    return box.exec_()
