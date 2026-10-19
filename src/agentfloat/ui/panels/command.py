# -*- coding: utf-8 -*-
"""自定义命令面板 — 快速启动用户自定义命令

- 命令条目：名称 / 命令 / 参数 / 工作目录 / 启动方式
- 启动方式：window（默认，独立窗口）/ console（Windows Terminal）/ background（静默后台）
- 面板内可直接新建 / 编辑 / 删除 / 运行，并带常用预设
"""
import os
import subprocess
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QFormLayout, QMessageBox, QFileDialog,
)
from PyQt5.QtGui import QFont

from agentfloat.core.theme import get_colors
from agentfloat.ui import panel_kit as kit
from agentfloat.ui.tokens import FONT

PRESET_COLORS = ["#5B8DEF", "#16A085", "#E67E22", "#8E44AD", "#2E86C1", "#27AE60"]
PRESET_CHARS = ["⚙", "▶", "⌘", "▣", "◈", "✎"]
PRESETS = [
    ("记事本", "notepad", [], "window"),
    ("计算器", "calc", [], "window"),
    ("资源管理器", "explorer", [], "window"),
    ("命令提示符", "cmd", ["/k", "echo AgentFloat"], "window"),
    ("系统信息", "msinfo32", [], "window"),
]


def run_command(cmd_entry):
    """启动一条自定义命令。返回 (ok, 错误信息)。"""
    raw = (cmd_entry.get("command") or "").strip()
    if not raw:
        return False, "命令为空"
    args = [raw] + list(cmd_entry.get("args") or [])
    mode = cmd_entry.get("launch_mode") or "window"
    workdir = (cmd_entry.get("working_directory") or "").strip()
    if not workdir or not os.path.isdir(workdir):
        workdir = os.environ.get("USERPROFILE") or os.getcwd()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if mode == "console":
        try:
            subprocess.Popen(["wt", "-d", workdir, "--"] + args,
                             creationflags=flags)
            return True, ""
        except Exception:
            pass
    if mode == "background":
        try:
            subprocess.Popen(args, cwd=workdir, creationflags=flags)
            return True, ""
        except Exception as e:
            return False, str(e)
    try:
        subprocess.Popen(["cmd", "/c", "start", "", *args], cwd=workdir,
                         creationflags=flags)
        return True, ""
    except Exception as e:
        return False, str(e)


class CommandEditDialog(QDialog):
    """新建 / 编辑命令条目"""

    def __init__(self, entry=None, theme="light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._entry = dict(entry or {})
        self.setWindowTitle("编辑命令" if entry else "新建命令")
        self.setMinimumWidth(440)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        self.setStyleSheet(kit.panel_qss(self._theme))    # 与面板统一配色/密度
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如：打开项目文档")
        form.addRow("名称", self.ed_name)
        self.ed_cmd = QLineEdit()
        self.ed_cmd.setPlaceholderText("可执行文件或完整路径，如 notepad 或 C:/xxx/tool.exe")
        form.addRow("命令", self.ed_cmd)
        self.ed_args = QLineEdit()
        self.ed_args.setPlaceholderText('空格分隔，支持引号，如 /k 或 "echo hi"')
        form.addRow("参数", self.ed_args)
        self.ed_dir = QLineEdit()
        self.ed_dir.setPlaceholderText("留空 = 用户主目录")
        self.btn_dir = QPushButton("浏览…")
        self.btn_dir.clicked.connect(self._pick_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.ed_dir, 1)
        dir_row.addWidget(self.btn_dir)
        form.addRow("工作目录", dir_row)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("独立窗口（默认）", "window")
        self.cmb_mode.addItem("Windows Terminal 终端", "console")
        self.cmb_mode.addItem("后台静默运行", "background")
        form.addRow("启动方式", self.cmb_mode)
        lay.addLayout(form)
        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("保存")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._save)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_ok)
        lay.addLayout(btns)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择工作目录", self.ed_dir.text() or os.getcwd())
        if d:
            self.ed_dir.setText(d)

    def _load(self):
        self.ed_name.setText(self._entry.get("name") or "")
        self.ed_cmd.setText(self._entry.get("command") or "")
        self.ed_args.setText(" ".join(self._entry.get("args") or []))
        self.ed_dir.setText(self._entry.get("working_directory") or "")
        mode = self._entry.get("launch_mode") or "window"
        i = self.cmb_mode.findData(mode)
        self.cmb_mode.setCurrentIndex(max(0, i))

    def _save(self):
        name = self.ed_name.text().strip()
        cmd = self.ed_cmd.text().strip()
        if not name or not cmd:
            QMessageBox.warning(self, "提示", "请填写名称与命令。")
            return
        args = []
        for part in self.ed_args.text().split():
            args.append(part)
        self._entry.update({
            "name": name,
            "command": cmd,
            "args": args,
            "working_directory": self.ed_dir.text().strip(),
            "launch_mode": self.cmb_mode.currentData() or "window",
        })
        self.accept()

    def result_entry(self):
        return self._entry


class CommandPanel(kit.PanelShell):
    """命令面板：列表 + 运行 / 新建 / 编辑 / 删除 / 预设"""

    commands_changed = pyqtSignal(list)

    def __init__(self, commands, theme="light", parent=None):
        super().__init__("命令面板", "", theme=theme, width=560, height=500, parent=parent)
        self._theme = theme
        self._commands = [dict(c) for c in (commands or [])]
        self.setWindowTitle("AgentFloat — 命令面板")
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        self.lbl_status = QLabel("")
        f = QFont("Microsoft YaHei")
        f.setPixelSize(FONT.micro)
        self.lbl_status.setFont(f)
        self.lbl_status.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["ACCENT"])
        self.lbl_status.setVisible(False)

        self.list = kit.ListView()
        self.list.itemDoubleClicked.connect(lambda _i: self._run_current())
        self.body.addWidget(self.list, 1)

        self.btn_preset = kit.ghost_button("添加示例", on_click=self._add_presets)
        self.btn_add = kit.ghost_button("＋ 新建", on_click=self._add_cmd)
        self.btn_edit = kit.ghost_button("编辑", on_click=self._edit_cmd)
        self.btn_del = kit.ghost_button("删除", on_click=self._del_cmd, danger=True)
        self.btn_run = kit.ghost_button("▶ 运行", on_click=self._run_current)
        self.btn_close = kit.ghost_button("关闭", on_click=self.close)
        # 左组（逆序插入到最前）：状态 / 添加示例 / 新建 / 编辑 / 删除；右侧：运行 / 关闭
        for b in (self.btn_del, self.btn_edit, self.btn_add, self.btn_preset, self.lbl_status):
            self.footer.insertWidget(0, b)
        self.footer.addWidget(self.btn_run)
        self.footer.addWidget(self.btn_close)
        self.show_footer(True)

    def refresh(self):
        self.list.clear()
        for i, e in enumerate(self._commands):
            name = e.get("name") or "未命名"
            cmd = e.get("command") or ""
            mode = e.get("launch_mode") or "window"
            mode_txt = {"window": "窗口", "console": "终端", "background": "后台"}.get(mode, "窗口")
            it, w = kit.item_for(
                kit.list_row(name, "%s · %s" % (cmd or "（无命令）", mode_txt),
                             str(i + 1), "#0A84FF"),
                data=i)
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
        if not self._commands:
            it, w = kit.item_for(
                kit.list_row("暂无自定义命令", "点「＋ 新建」或「添加示例」开始", "", None),
                data=None)
            it.setFlags(Qt.ItemIsEnabled)
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
        self.set_subtitle("共 %d 条" % len(self._commands))

    def _current_index(self):
        it = self.list.currentItem()
        if it is None:
            return None
        return it.data(Qt.UserRole)

    def _run_current(self):
        idx = self._current_index()
        if idx is None or not (0 <= idx < len(self._commands)):
            return
        entry = self._commands[idx]
        ok, err = run_command(entry)
        if ok:
            self._flash("已启动：%s" % (entry.get("name") or "命令"))
        else:
            QMessageBox.warning(self, "启动失败", "%s\n\n%s" % (entry.get("name") or "", err))

    def _add_cmd(self):
        dlg = CommandEditDialog(None, theme=self._theme, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            e = dlg.result_entry()
            e["id"] = "cmd_%d" % int(time.time() * 1000)
            e["icon_color"] = PRESET_COLORS[len(self._commands) % len(PRESET_COLORS)]
            e["icon_char"] = PRESET_CHARS[len(self._commands) % len(PRESET_CHARS)]
            self._commands.append(e)
            self._emit_changed()
            self.refresh()

    def _edit_cmd(self):
        idx = self._current_index()
        if idx is None or not (0 <= idx < len(self._commands)):
            return
        dlg = CommandEditDialog(self._commands[idx], theme=self._theme, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._commands[idx] = dlg.result_entry()
            self._emit_changed()
            self.refresh()

    def _del_cmd(self):
        idx = self._current_index()
        if idx is None or not (0 <= idx < len(self._commands)):
            return
        name = self._commands[idx].get("name") or "该命令"
        if kit.confirm(self, "删除命令", "确定删除「%s」？" % name,
                       ok_text="删除", danger=True, theme=self._theme):
            del self._commands[idx]
            self._emit_changed()
            self.refresh()

    def _add_presets(self):
        existing = {c.get("command") for c in self._commands if c.get("command")}
        added = 0
        for name, cmd, args, mode in PRESETS:
            if cmd in existing:
                continue
            self._commands.append({
                "id": "cmd_%d" % int(time.time() * 1000) + str(added),
                "name": name,
                "command": cmd,
                "args": list(args),
                "working_directory": "",
                "launch_mode": mode,
                "icon_color": PRESET_COLORS[len(self._commands) % len(PRESET_COLORS)],
                "icon_char": PRESET_CHARS[len(self._commands) % len(PRESET_CHARS)],
            })
            added += 1
        if added:
            self._emit_changed()
            self.refresh()
            self._flash("已添加 %d 个示例命令" % added)
        else:
            self._flash("示例命令均已存在")

    def _emit_changed(self):
        self.commands_changed.emit([dict(c) for c in self._commands])

    def _flash(self, msg):
        """v3.14.0：统一走 PanelShell.flash（150ms 淡出），不再 QTimer 硬隐藏"""
        self.flash(msg, label=self.lbl_status)
