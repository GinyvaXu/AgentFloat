# -*- coding: utf-8 -*-
"""自定义命令面板 — 快速启动用户自定义命令

- 命令条目：名称 / 命令 / 参数 / 工作目录 / 启动方式
- 启动方式：window（默认，独立窗口）/ console（Windows Terminal）/ background（静默后台）
- 面板内可直接新建 / 编辑 / 删除 / 运行，并带常用预设
"""
import os
import subprocess
import time

from PyQt5.QtCore import Qt, pyqtSignal, QSize as _QSize
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QFormLayout,
    QMessageBox, QFileDialog, QApplication,
)
from PyQt5.QtGui import QFont

from af_theme import get_colors

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
    name = (cmd_entry.get("name") or "命令").strip() or "命令"
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
        c = get_colors(self._theme)
        sf = "#%02X%02X%02X" % c["SURFACE"]
        tx = "#%02X%02X%02X" % c["TEXT"]
        ac = "#%02X%02X%02X" % c["ACCENT"]
        bd = "#%02X%02X%02X" % c["SEPARATOR"]
        self.setStyleSheet(
            "QDialog { background: %s; }" % sf +
            "QLabel { color: %s; font-size: 12px; }" % tx +
            "QLineEdit, QComboBox { background: #FFFFFF; color: %s; border: 1px solid %s;"
            " border-radius: 6px; padding: 5px 8px; font-size: 12px; }" % (tx, bd) +
            "QPushButton { background: #FFFFFF; color: %s; border: 1px solid %s;"
            " border-radius: 6px; padding: 5px 14px; font-size: 12px; }" % (ac, bd)
        )
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


class CommandPanel(QDialog):
    """命令面板：列表 + 运行 / 新建 / 编辑 / 删除 / 预设"""

    commands_changed = pyqtSignal(list)

    def __init__(self, commands, theme="light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._commands = [dict(c) for c in (commands or [])]
        self.setWindowTitle("AgentFloat — 命令面板")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(560, 500)
        self._setup_ui()
        self.refresh()

    def _css(self):
        c = get_colors(self._theme)
        is_dark = self._theme == "dark"
        sf = "#%02X%02X%02X" % c["SURFACE"]
        tx = "#%02X%02X%02X" % c["TEXT"]
        hi = "#%02X%02X%02X" % c["HINT"]
        ac = "#%02X%02X%02X" % c["ACCENT"]
        bd = "#%02X%02X%02X" % c["SEPARATOR"]
        card = "#333336" if is_dark else "#FFFFFF"
        hover = "rgba(255,255,255,0.09)" if is_dark else "rgba(120,120,128,0.10)"
        banner = "rgba(255,255,255,0.06)" if is_dark else "rgba(255,255,255,0.62)"
        return (
            "QDialog { background: %s; border: 1px solid %s; border-radius: 14px; }" % (sf, bd) +
            "QFrame#titleBar { background: %s; border-top-left-radius: 14px;"
            " border-top-right-radius: 14px; border-bottom: 1px solid %s; }" % (banner, bd) +
            "QLabel { color: %s; font-size: 12px; }" % tx +
            "QPushButton { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 5px 12px; font-size: 12px; }" % (card, ac, bd) +
            "QPushButton:hover { background: %s; }" % sf +
            "QListWidget { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 4px; font-size: 12px; }" % (card, tx, bd) +
            "QListWidget::item { padding: 8px 8px; border-radius: 7px; margin: 2px; }" +
            "QListWidget::item:hover { background: %s; }" % hover +
            "QListWidget::item:selected { background: %s; color: #FFF; border-radius: 7px; }" % ac
        )

    def _setup_ui(self):
        self.setStyleSheet(self._css())
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 12)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setContentsMargins(14, 10, 14, 4)
        title = QLabel("命令面板")
        f = QFont("Microsoft YaHei", 13, QFont.Bold)
        title.setFont(f)
        bar.addWidget(title)
        bar.addStretch()
        self.btn_preset = QPushButton("添加示例")
        self.btn_preset.clicked.connect(self._add_presets)
        self.btn_add = QPushButton("＋ 新建")
        self.btn_add.clicked.connect(self._add_cmd)
        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(self._edit_cmd)
        self.btn_del = QPushButton("删除")
        self.btn_del.clicked.connect(self._del_cmd)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        for b in (self.btn_preset, self.btn_add, self.btn_edit, self.btn_del, self.btn_close):
            bar.addWidget(b)
        root.addLayout(bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["ACCENT"])
        self.lbl_status.setVisible(False)
        root.addWidget(self.lbl_status)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._run_current())
        root.addWidget(self.list, 1)

        run_bar = QHBoxLayout()
        run_bar.addStretch()
        self.btn_run = QPushButton("▶ 运行")
        self.btn_run.setStyleSheet("QPushButton { background: #%02X%02X%02X; color: #FFF;"
                                   " border: none; border-radius: 8px; padding: 7px 22px;"
                                   " font-size: 13px; font-weight: bold; }" % get_colors(self._theme)["ACCENT"])
        self.btn_run.clicked.connect(self._run_current)
        run_bar.addWidget(self.btn_run)
        root.addLayout(run_bar)

    def refresh(self):
        self.list.clear()
        for i, e in enumerate(self._commands):
            name = e.get("name") or "未命名"
            cmd = e.get("command") or ""
            mode = e.get("launch_mode") or "window"
            mode_txt = {"window": "窗口", "console": "终端", "background": "后台"}.get(mode, "窗口")
            it = QListWidgetItem("%d. %s\n%s  ·  %s" % (i + 1, name, cmd or "（无命令）", mode_txt))
            it.setData(Qt.UserRole, i)
            it.setSizeHint(_QSize(0, 52))
            self.list.addItem(it)
        if not self._commands:
            self.list.addItem("暂无自定义命令，点击「＋ 新建」或「添加示例」")

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
        if QMessageBox.question(self, "删除", "确定删除「%s」？" % name) == QMessageBox.Yes:
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
        self.lbl_status.setText(msg)
        self.lbl_status.setVisible(True)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1800, lambda: self.lbl_status.setVisible(False))
