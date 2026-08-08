# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skills 辅助窗

双栏布局：左列表（搜索 / 来源过滤）+ 右详情（描述 / 触发指令 / 复制 / AI 优化）。
"""
import os
import subprocess

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QListWidget, QListWidgetItem, QPushButton, QTextBrowser, QFrame,
    QApplication, QMessageBox, QSplitter,
)

from af_theme import get_colors
from skills_scanner import scan_skills, default_skill_roots

AI_OPTIMIZE_TEMPLATE = (
    "你是技能描述优化助手。请把下面这个 AI Agent skill 的原始描述，"
    "改写为面向用户的、简洁的功能简介（中文，不超过 80 字，保留关键能力，不要解释过程）。\n\n"
    "技能名称：{name}\n原始描述：{desc}\n\n直接输出优化后的简介："
)


class _OptimizeWorker(QThread):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, ai_tool, template, parent=None):
        super().__init__(parent)
        self._ai_tool = ai_tool
        self._template = template

    def run(self):
        tool = (self._ai_tool or "codex exec").strip()
        if tool.startswith("codex"):
            cmd = ["codex", "exec", "--skip-git-repo-check", self._template]
        else:
            cmd = ["claude", "-p", self._template]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=240,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
            if not out:
                self.failed.emit("AI 未返回内容")
            else:
                self.done.emit(out)
        except FileNotFoundError:
            self.failed.emit("未找到 AI 工具（%s）" % tool)
        except subprocess.TimeoutExpired:
            self.failed.emit("AI 优化超时（240s）")
        except Exception as e:
            self.failed.emit("AI 优化失败: %s" % e)


class SkillsPanel(QDialog):
    def __init__(self, skills_cfg, theme="light", parent=None):
        super().__init__(parent)
        self._skills_cfg = skills_cfg or {}
        self._theme = theme
        self._all_skills = []
        self._worker = None
        self._current = None
        self._cjk = "Microsoft YaHei"
        self.setWindowTitle("AgentFloat — Skills 辅助窗")
        self.setMinimumSize(860, 560)
        self.setStyleSheet(self._stylesheet())
        self._setup_ui()
        self.refresh()

    # ── 界面 ────────────────────────────────────
    def _stylesheet(self):
        c = get_colors(self._theme)
        is_dark = self._theme == "dark"
        sf = "#%02X%02X%02X" % c["SURFACE"]
        tx = "#%02X%02X%02X" % c["TEXT"]
        hi = "#%02X%02X%02X" % c["HINT"]
        ac = "#%02X%02X%02X" % c["ACCENT"]
        bd = "#%02X%02X%02X" % c["SEPARATOR"]
        card = "#333336" if is_dark else "#FFFFFF"
        return (
            "QDialog { background: %s; }" % sf +
            "QListWidget, QTextBrowser, QLineEdit, QComboBox { background: %s; color: %s;"
            " border: 1px solid %s; border-radius: 8px; padding: 6px; font-size: 12px; }" % (card, tx, bd) +
            "QListWidget::item { padding: 6px 8px; border-radius: 6px; }" +
            "QListWidget::item:selected { background: %s; color: #FFF; }" % ac +
            "QPushButton { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 6px 14px; font-size: 12px; }" % (card, ac, bd) +
            "QPushButton:hover { background: %s; }" % sf +
            "QPushButton:disabled { color: %s; }" % hi +
            "QLabel { color: %s; font-size: 12px; }" % tx +
            "QFrame#detailCard { background: %s; border: 1px solid %s; border-radius: 10px; }" % (card, bd)
        )

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Skills 辅助窗")
        title.setFont(QFont(self._cjk, 15, QFont.Bold))
        head.addWidget(title)
        head.addStretch()
        self.lbl_count = QLabel("")
        head.addWidget(self.lbl_count)
        root.addLayout(head)

        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索 skill 名称 / 描述…")
        self.search_edit.textChanged.connect(self._apply_filter)
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.search_edit, 3)
        bar.addWidget(self.source_combo, 1)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        self.list.setMinimumWidth(280)
        split.addWidget(self.list)

        detail = QFrame()
        detail.setObjectName("detailCard")
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(14, 12, 14, 12)
        dv.setSpacing(8)
        self.lbl_name = QLabel("—")
        self.lbl_name.setFont(QFont(self._cjk, 14, QFont.Bold))
        dv.addWidget(self.lbl_name)
        self.lbl_source = QLabel("")
        self.lbl_source.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        dv.addWidget(self.lbl_source)
        self.desc_view = QTextBrowser()
        dv.addWidget(self.desc_view, 1)

        act = QHBoxLayout()
        self.btn_copy = QPushButton("复制触发指令")
        self.btn_copy.clicked.connect(self._copy_trigger)
        self.btn_optimize = QPushButton("AI 优化描述")
        self.btn_optimize.clicked.connect(self._optimize_desc)
        act.addWidget(self.btn_copy)
        act.addWidget(self.btn_optimize)
        act.addStretch()
        self.lbl_status = QLabel("")
        act.addWidget(self.lbl_status)
        dv.addLayout(act)

        split.addWidget(detail)
        split.setSizes([300, 540])
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        hint = QLabel("提示：触发指令指需要手动输入的关键词（如 grill me），复制后粘贴到对应 AI 聊天框即可。")
        hint.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        bottom.addWidget(hint)
        bottom.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    # ── 数据 ────────────────────────────────────
    def refresh(self):
        roots = self._skills_cfg.get("roots") or default_skill_roots()
        self._all_skills = scan_skills(roots)
        self._rebuild_sources()
        self._apply_filter()

    def _rebuild_sources(self):
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("全部来源", "")
        seen = []
        for s in self._all_skills:
            if s.root not in seen:
                seen.append(s.root)
        for r in seen:
            self.source_combo.addItem(os.path.basename(r) or r, r)
        self.source_combo.blockSignals(False)

    def _apply_filter(self):
        kw = self.search_edit.text().strip().lower()
        src = self.source_combo.currentData()
        self.list.blockSignals(True)
        self.list.clear()
        for s in self._all_skills:
            if src and s.root != src:
                continue
            if kw and kw not in s.name.lower() and kw not in s.description.lower():
                continue
            item = QListWidgetItem()
            item.setText("%s%s" % (s.name, "  ⚡" if s.trigger else ""))
            item.setData(Qt.UserRole, s)
            item.setToolTip(s.path)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.lbl_count.setText("共 %d 个 skill" % self.list.count())
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.lbl_name.setText("—")
            self.desc_view.setPlainText("未找到匹配的 skill。")

    def _on_select(self, row):
        item = self.list.item(row)
        if item is None:
            return
        s = item.data(Qt.UserRole)
        self._current = s
        self.lbl_name.setText(s.name)
        self.lbl_source.setText(s.root)
        txt = s.description or "（无描述）"
        if s.trigger:
            txt += "\n\n⚡ 触发指令：`%s`" % s.trigger
        if s.has_manual_trigger and not s.trigger:
            txt += "\n\n（该 skill 需要手动触发，具体指令见 SKILL.md 正文）"
        txt += "\n\n路径：%s" % s.path
        self.desc_view.setPlainText(txt)
        self.lbl_status.setText("")
        self.btn_copy.setEnabled(bool(s.trigger))

    # ── 动作 ────────────────────────────────────
    def _copy_trigger(self):
        s = getattr(self, "_current", None)
        if s and s.trigger:
            QApplication.clipboard().setText(s.trigger)
            self.lbl_status.setText("已复制 ✓")
            QTimer.singleShot(1500, lambda: self.lbl_status.setText(""))

    def _optimize_desc(self):
        s = getattr(self, "_current", None)
        if s is None:
            return
        ai_tool = self._skills_cfg.get("ai_tool") or "codex exec"
        template = AI_OPTIMIZE_TEMPLATE.format(name=s.name, desc=(s.description or "无"))
        self.lbl_status.setText("AI 优化中…")
        self.btn_optimize.setEnabled(False)
        self._worker = _OptimizeWorker(ai_tool, template, self)
        self._worker.done.connect(self._on_optimized)
        self._worker.failed.connect(self._on_optimize_failed)
        self._worker.start()

    def _on_optimized(self, text):
        s = getattr(self, "_current", None)
        if s is not None:
            s.description = text.strip()
            self.desc_view.setPlainText(
                "%s\n\n（AI 优化）\n\n路径：%s" % (text.strip(), s.path))
        self.lbl_status.setText("优化完成 ✓")
        self.btn_optimize.setEnabled(True)

    def _on_optimize_failed(self, msg):
        self.lbl_status.setText(msg)
        self.btn_optimize.setEnabled(True)
        QMessageBox.information(self, "AI 优化", msg)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.wait(1000)
        super().closeEvent(event)
