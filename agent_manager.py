# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Agent 管理对话框 + Skills 设置对话框"""
import copy
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QListWidget, QListWidgetItem, QPushButton, QCheckBox, QSpinBox,
    QGroupBox, QMessageBox, QFileDialog, QWidget,
)

from af_theme import get_colors
from agent_registry import normalize_agents, default_agents, get_primary_agent
from skills_scanner import default_skill_roots

_CJK = "Microsoft YaHei"


def _font(size=12, bold=False):
    f = QFont(_CJK, size)
    f.setBold(bold)
    return f


def _style(theme):
    c = get_colors(theme)
    is_dark = theme == "dark"
    sf = "#%02X%02X%02X" % c["SURFACE"]
    tx = "#%02X%02X%02X" % c["TEXT"]
    hi = "#%02X%02X%02X" % c["HINT"]
    ac = "#%02X%02X%02X" % c["ACCENT"]
    bd = "#%02X%02X%02X" % c["SEPARATOR"]
    card = "#333336" if is_dark else "#FFFFFF"
    return (
        "QDialog { background: %s; }" % sf +
        "QGroupBox { color: %s; background: %s; border: 1px solid %s; border-radius: 10px;"
        " margin-top: 10px; padding-top: 12px; font-size: 13px; font-weight: bold; }" % (tx, card, bd) +
        "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }" +
        "QListWidget, QLineEdit, QComboBox, QSpinBox { background: %s; color: %s;"
        " border: 1px solid %s; border-radius: 8px; padding: 5px; font-size: 12px; }" % (card, tx, bd) +
        "QListWidget::item { padding: 6px 8px; border-radius: 6px; }" +
        "QListWidget::item:selected { background: %s; color: #FFF; }" % ac +
        "QPushButton { background: %s; color: %s; border: 1px solid %s; border-radius: 8px;"
        " padding: 6px 14px; font-size: 12px; }" % (card, ac, bd) +
        "QPushButton:hover { background: %s; }" % sf +
        "QPushButton:disabled { color: %s; }" % hi +
        "QCheckBox { color: %s; font-size: 12px; }" % tx +
        "QLabel { color: %s; font-size: 12px; }" % tx
    )


class AgentManagerDialog(QDialog):
    """Agent 增删改 + 设为主 Agent"""

    def __init__(self, agents, theme="light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._agents = normalize_agents(agents)
        self._selected_id = None
        self.setWindowTitle("Agent 管理")
        self.setMinimumSize(760, 520)
        self.setStyleSheet(_style(theme))
        self._setup_ui()
        self._reload_list()

    # ── UI ────────────────────────────────────
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QLabel("管理可启动的 AI Agent（主 Agent = 点击浮窗时启动）")
        head.setFont(_font(13, True))
        root.addWidget(head)

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select_row)
        left.addWidget(self.list, 1)
        btns = QHBoxLayout()
        self.btn_add = QPushButton("＋ 新增")
        self.btn_add.clicked.connect(self._add_agent)
        self.btn_del = QPushButton("删除")
        self.btn_del.clicked.connect(self._delete_agent)
        self.btn_set_primary = QPushButton("设为主 Agent")
        self.btn_set_primary.clicked.connect(self._set_primary)
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_del)
        btns.addWidget(self.btn_set_primary)
        left.addLayout(btns)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        box = QGroupBox("Agent 配置")
        vb = QVBoxLayout(box)
        vb.setSpacing(6)
        vb.setContentsMargins(12, 12, 12, 10)

        vb.addWidget(QLabel("名称"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("显示在菜单中的名称，如 Gemini CLI")
        vb.addWidget(self.ed_name)

        vb.addWidget(QLabel("命令"))
        self.ed_cmd = QLineEdit()
        self.ed_cmd.setPlaceholderText("可执行文件或 PATH 命令，如 claude / codex / 完整路径")
        vb.addWidget(self.ed_cmd)

        vb.addWidget(QLabel("附加参数（空格分隔）"))
        self.ed_args = QLineEdit()
        vb.addWidget(self.ed_args)

        vb.addWidget(QLabel("跳过权限参数（可留空）"))
        self.ed_skip = QLineEdit()
        self.ed_skip.setPlaceholderText("如 --dangerously-skip-permissions")
        vb.addWidget(self.ed_skip)

        vb.addWidget(QLabel("默认工作目录（留空 = 用户主目录）"))
        dir_row = QHBoxLayout()
        self.ed_dir = QLineEdit()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.ed_dir, 1)
        dir_row.addWidget(browse)
        vb.addLayout(dir_row)

        vb.addWidget(QLabel("图标颜色（十六进制）"))
        self.ed_color = QLineEdit()
        self.ed_color.setPlaceholderText("#5B8DEF")
        vb.addWidget(self.ed_color)

        vb.addWidget(QLabel("启动模式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("普通模式", "normal")
        self.cmb_mode.addItem("跳过权限", "skip_permissions")
        vb.addWidget(self.cmb_mode)

        self.chk_primary = QCheckBox("设为主 Agent（点击浮窗启动）")
        self.chk_primary.toggled.connect(self._on_primary_toggle)
        vb.addWidget(self.chk_primary)

        right.addWidget(box, 1)
        body.addLayout(right, 2)
        root.addLayout(body, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        foot.addWidget(cancel)
        foot.addWidget(save)
        root.addLayout(foot)

    # ── 列表 ────────────────────────────────────
    def _reload_list(self, select_id=None):
        self.list.blockSignals(True)
        self.list.clear()
        for a in self._agents:
            tag = "★ " if a.get("primary") else ("• " if a.get("builtin") else "+ ")
            item = QListWidgetItem("%s%s" % (tag, a.get("name")))
            item.setData(Qt.UserRole, a.get("id"))
            item.setToolTip("%s\n%s" % (a.get("command"), a.get("description", "")))
            self.list.addItem(item)
            if a.get("id") == select_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if select_id is None and self.list.count():
            self.list.setCurrentRow(0)

    def _on_select_row(self, row):
        item = self.list.item(row)
        if item is None:
            self._selected_id = None
            return
        self._selected_id = item.data(Qt.UserRole)
        a = self._get_agent(self._selected_id)
        if a is None:
            return
        self.ed_name.setText(a.get("name", ""))
        self.ed_cmd.setText(a.get("command", ""))
        self.ed_args.setText(" ".join(a.get("args") or []))
        self.ed_skip.setText(a.get("skip_permissions_arg", ""))
        self.ed_dir.setText(a.get("working_directory", ""))
        self.ed_color.setText(a.get("icon_color", "#5B8DEF"))
        idx = self.cmb_mode.findData(a.get("launch_mode", "normal"))
        self.cmb_mode.setCurrentIndex(max(0, idx))
        self.chk_primary.setChecked(bool(a.get("primary")))
        self._set_editable(not a.get("builtin"))

    def _get_agent(self, aid):
        for a in self._agents:
            if a.get("id") == aid:
                return a
        return None

    def _set_editable(self, editable):
        # 内置 Agent 只允许调整主 Agent / 启动模式，不允许删除
        for w in [self.ed_name, self.ed_cmd, self.ed_args, self.ed_skip,
                  self.ed_dir, self.ed_color]:
            w.setEnabled(editable)
        self.btn_del.setEnabled(editable and self._selected_id is not None)

    # ── 动作 ────────────────────────────────────
    def _add_agent(self):
        n = len([a for a in self._agents if a.get("builtin")]) + 1
        aid = "custom_%d" % n
        while self._get_agent(aid):
            n += 1
            aid = "custom_%d" % n
        self._agents.append({
            "id": aid, "name": "自定义 Agent %d" % n, "command": "",
            "args": [], "skip_permissions_arg": "", "working_directory": "",
            "launch_mode": "normal", "icon_color": "#5B8DEF", "icon_char": "A",
            "check": "", "primary": False, "builtin": False, "description": "用户自定义 Agent",
        })
        self._reload_list(select_id=aid)
        self.list.setCurrentRow(self._row_of(aid))

    def _row_of(self, aid):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == aid:
                return i
        return 0

    def _delete_agent(self):
        aid = self._selected_id
        if not aid:
            return
        a = self._get_agent(aid)
        if a is None:
            return
        if a.get("builtin"):
            QMessageBox.information(self, "Agent 管理", "内置 Agent 不可删除，可新增自定义 Agent。")
            return
        self._agents = [x for x in self._agents if x.get("id") != aid]
        self._reload_list()

    def _set_primary(self):
        aid = self._selected_id
        if not aid:
            return
        for a in self._agents:
            a["primary"] = (a.get("id") == aid)
        self.chk_primary.setChecked(True)
        self._reload_list(select_id=aid)

    def _on_primary_toggle(self, checked):
        aid = self._selected_id
        if not aid:
            return
        if checked:
            for a in self._agents:
                a["primary"] = (a.get("id") == aid)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择工作目录", self.ed_dir.text() or os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
        if d:
            self.ed_dir.setText(d)

    def _save(self):
        aid = self._selected_id
        if aid:
            a = self._get_agent(aid)
            if a and not a.get("builtin"):
                name = self.ed_name.text().strip()
                cmd = self.ed_cmd.text().strip()
                if not name or not cmd:
                    QMessageBox.warning(self, "Agent 管理", "自定义 Agent 必须填写名称与命令。")
                    return
                a["name"] = name
                a["command"] = cmd
                a["args"] = self.ed_args.text().split()
                a["skip_permissions_arg"] = self.ed_skip.text().strip()
                a["working_directory"] = self.ed_dir.text().strip()
                a["icon_color"] = self.ed_color.text().strip() or "#5B8DEF"
                a["launch_mode"] = self.cmb_mode.currentData()
            elif a:
                a["launch_mode"] = self.cmb_mode.currentData()
        if not any(x.get("primary") for x in self._agents):
            self._agents[0]["primary"] = True
        self._agents = normalize_agents(self._agents)
        self.accept()

    @property
    def agents(self):
        return copy.deepcopy(self._agents)


class SkillsSettingsDialog(QDialog):
    """Skills 扫描设置：扫描根目录"""

    def __init__(self, skills_cfg, theme="light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._cfg = dict(skills_cfg or {})
        self._roots = [r for r in (self._cfg.get("roots") or default_skill_roots())]
        self.setWindowTitle("Skills 设置")
        self.setMinimumSize(620, 420)
        self.setStyleSheet(_style(theme))
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        box = QGroupBox("扫描目录")
        vb = QVBoxLayout(box)
        vb.setSpacing(8)
        vb.setContentsMargins(12, 12, 12, 10)
        hint = QLabel("Skills 辅助窗会扫描以下目录中的 SKILL.md（支持 ~ 与 %%USERPROFILE%% 等变量）")
        hint.setWordWrap(True)
        vb.addWidget(hint)
        self.root_list = QListWidget()
        for r in self._roots:
            self.root_list.addItem(r)
        vb.addWidget(self.root_list, 1)
        btns = QHBoxLayout()
        add = QPushButton("添加目录…")
        add.clicked.connect(self._add_root)
        remove = QPushButton("移除选中")
        remove.clicked.connect(self._remove_root)
        restore = QPushButton("恢复默认")
        restore.clicked.connect(self._restore_defaults)
        btns.addWidget(add)
        btns.addWidget(remove)
        btns.addWidget(restore)
        btns.addStretch()
        vb.addLayout(btns)
        root.addWidget(box, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        foot.addWidget(cancel)
        foot.addWidget(save)
        root.addLayout(foot)

    def _add_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择 skills 根目录", os.path.expanduser("~"),
                                             QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
        if d:
            items = [self.root_list.item(i).text() for i in range(self.root_list.count())]
            if d not in items:
                self.root_list.addItem(d)

    def _remove_root(self):
        row = self.root_list.currentRow()
        if row >= 0:
            self.root_list.takeItem(row)

    def _restore_defaults(self):
        self.root_list.clear()
        for r in default_skill_roots():
            self.root_list.addItem(r)

    def _save(self):
        self._cfg["roots"] = [self.root_list.item(i).text() for i in range(self.root_list.count())]
        self._cfg.pop("ai_tool", None)
        self.accept()

    @property
    def config(self):
        return dict(self._cfg)
