# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skills 辅助窗

双栏布局：左列表（搜索 / 来源过滤 / 中英对照切换）+ 右详情（中英描述 / 触发指令 / 复制）。
"""
import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QListWidget, QListWidgetItem, QPushButton, QTextBrowser, QFrame,
    QApplication, QSplitter,
)

from af_theme import get_colors
from skills_scanner import scan_skills, default_skill_roots
from skills_translations import get_zh


class SkillsPanel(QDialog):
    def __init__(self, skills_cfg, theme="light", parent=None):
        super().__init__(parent)
        self._skills_cfg = skills_cfg or {}
        self._theme = theme
        self._all_skills = []
        self._current = None
        self._lang_mode = "both"          # en / zh / both
        self._lang_cycle = ["en", "zh", "both"]
        self._cjk = "Microsoft YaHei"
        self.setWindowTitle("AgentFloat — Skills 辅助窗")
        self.setMinimumSize(880, 580)
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
        self.search_edit.setPlaceholderText("搜索 skill 名称 / 描述（中英文均可）…")
        self.search_edit.textChanged.connect(self._apply_filter)
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self._apply_filter)
        self.btn_lang = QPushButton("中英对照")
        self.btn_lang.setToolTip("切换显示语言：英文 / 中文 / 中英对照")
        self.btn_lang.clicked.connect(self._cycle_lang)
        bar.addWidget(self.search_edit, 3)
        bar.addWidget(self.source_combo, 1)
        bar.addWidget(self.btn_lang)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)

        # 左：列表
        left = QFrame()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        ll.addWidget(self.list)
        split.addWidget(left)

        # 右：详情
        detail = QFrame()
        detail.setObjectName("detailCard")
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(14, 14, 14, 14)
        dv.setSpacing(8)
        self.lbl_name = QLabel("—")
        self.lbl_name.setFont(QFont(self._cjk, 14, QFont.Bold))
        dv.addWidget(self.lbl_name)
        self.lbl_source = QLabel("")
        self.lbl_source.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        dv.addWidget(self.lbl_source)
        self.desc_view = QTextBrowser()
        self.desc_view.setOpenExternalLinks(False)
        dv.addWidget(self.desc_view, 1)

        act = QHBoxLayout()
        self.btn_copy = QPushButton("复制触发指令")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_trigger)
        act.addWidget(self.btn_copy)
        act.addStretch()
        self.lbl_status = QLabel("")
        act.addWidget(self.lbl_status)
        dv.addLayout(act)

        split.addWidget(detail)
        split.setSizes([320, 540])
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

    def _zh(self, s):
        zh_name, zh_desc = get_zh(s.name, os.path.basename(os.path.dirname(s.path)))
        return zh_name, zh_desc

    def _display_name(self, s):
        if self._lang_mode == "en":
            return s.name
        zh_name, _ = self._zh(s)
        if zh_name and self._lang_mode == "both":
            return "%s（%s）" % (zh_name, s.name)
        if zh_name:
            return zh_name
        return s.name

    def _searchable_text(self, s):
        parts = [s.name, s.description]
        zh_name, zh_desc = self._zh(s)
        if zh_name:
            parts.append(zh_name)
        if zh_desc:
            parts.append(zh_desc)
        return " ".join(parts).lower()

    def _apply_filter(self):
        kw = self.search_edit.text().strip().lower()
        src = self.source_combo.currentData()
        self.list.blockSignals(True)
        self.list.clear()
        for s in self._all_skills:
            if src and s.root != src:
                continue
            if kw and kw not in self._searchable_text(s):
                continue
            item = QListWidgetItem()
            item.setText("%s%s" % (self._display_name(s), "  ⚡" if s.trigger else ""))
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
        zh_name, zh_desc = self._zh(s)
        has_zh = bool(zh_name and zh_desc)
        if self._lang_mode == "en":
            self.lbl_name.setText(s.name)
            txt = s.description or "（无描述）"
        elif self._lang_mode == "zh":
            self.lbl_name.setText(zh_name or s.name)
            if zh_desc:
                txt = zh_desc
            else:
                txt = "%s\n\n（暂无中文翻译，以下为原文）\n%s" % (s.description or "（无描述）", s.description or "")
        else:  # both
            self.lbl_name.setText("%s（%s）" % (zh_name, s.name) if zh_name else s.name)
            if has_zh:
                txt = "【中文】%s\n\n【English】%s" % (zh_desc, s.description or "（无描述）")
            else:
                txt = s.description or "（无描述）"
                txt += "\n\n（暂无中文翻译）"
        if s.trigger:
            txt += "\n\n⚡ 触发指令：`%s`" % s.trigger
        if s.has_manual_trigger and not s.trigger:
            txt += "\n\n（该 skill 需要手动触发，具体指令见 SKILL.md 正文）"
        txt += "\n\n路径：%s" % s.path
        self.desc_view.setPlainText(txt)
        self.lbl_status.setText("")
        self.btn_copy.setEnabled(bool(s.trigger))

    # ── 语言切换 ────────────────────────────────
    def _cycle_lang(self):
        idx = (self._lang_cycle.index(self._lang_mode) + 1) % len(self._lang_cycle)
        self._lang_mode = self._lang_cycle[idx]
        label = {"en": "English", "zh": "中文", "both": "中英对照"}[self._lang_mode]
        self.btn_lang.setText(label)
        self.btn_lang.setToolTip("切换显示语言：英文 / 中文 / 中英对照（当前：%s）" % label)
        self._apply_filter()

    # ── 动作 ────────────────────────────────────
    def _copy_trigger(self):
        s = getattr(self, "_current", None)
        if s and s.trigger:
            QApplication.clipboard().setText(s.trigger)
            self.lbl_status.setText("已复制 ✓")
            QTimer.singleShot(1500, lambda: self.lbl_status.setText(""))
