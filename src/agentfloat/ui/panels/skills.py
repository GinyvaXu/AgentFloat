# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skills 辅助窗（v3.12.0 用 panel_kit 重做）

- 外壳 / 搜索 / 列表 / 空态统一由 ui/panel_kit 提供（更小更轻：660×520）
- 左：按 skill 包分类的扁平列表（分类行可点击折叠，skill 行带触发角标）
- 右：详情区（中英对照三态切换、触发指令可见可复制）
"""
import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QLabel, QLineEdit, QComboBox, QTextBrowser, QSplitter, QPushButton,
    QHBoxLayout, QVBoxLayout, QWidget, QApplication,
)

from agentfloat.core.theme import get_colors
from agentfloat.services.skills.scanner import scan_skills, default_skill_roots, categorize_skills
from agentfloat.services.skills.translations import get_zh
from agentfloat.ui import panel_kit as kit
from agentfloat.ui import states
from agentfloat.ui.tokens import FONT, SPACE


class _TitleBar(kit._Header):
    """兼容旧调用（喝水面板等）：可拖动标题栏 + lbl_count 计数标签

    新面板请直接用 panel_kit.PanelShell（自带标题栏），不要再用本类。
    """

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setObjectName("titleBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("pkTitle")
        f = QFont(t.font())
        f.setPixelSize(FONT.body)
        f.setBold(True)
        t.setFont(f)
        lay.addWidget(t)
        lay.addStretch(1)
        self.lbl_count = QLabel("")
        f2 = QFont(self.lbl_count.font())
        f2.setPixelSize(FONT.micro)
        self.lbl_count.setFont(f2)
        self.lbl_count.setStyleSheet("color: #%02X%02X%02X;" % get_colors(getattr(parent, "_theme", "light"))["HINT"])
        lay.addWidget(self.lbl_count)
        btn = QPushButton("✕")
        btn.setObjectName("pkClose")
        btn.setFixedSize(20, 20)
        btn.setToolTip("关闭")
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(parent.close)
        lay.addWidget(btn)


class SkillsPanel(kit.PanelShell):
    """Skills 辅助窗：左侧分类列表 + 右侧详情"""

    def __init__(self, skills_cfg, theme="light", parent=None):
        super().__init__("Skills 辅助窗", "", theme=theme, width=660, height=520, parent=parent)
        self.setWindowTitle("AgentFloat — Skills 辅助窗")
        self._skills_cfg = skills_cfg or {}
        self._theme = theme
        self._all_skills = []
        self._grouped = []
        self._collapsed = set()
        self._current = None
        self._lang_mode = "both"
        self._lang_cycle = ["en", "zh", "both"]
        self._cjk = "Microsoft YaHei"
        c = get_colors(theme)
        self._accent_hex = "#%02X%02X%02X" % c["ACCENT"]
        self._hint_hex = "#%02X%02X%02X" % c["HINT"]
        self._setup_ui()
        self.refresh()

    # ── 界面 ────────────────────────────────────
    def _setup_ui(self):
        bar = QHBoxLayout()
        bar.setSpacing(SPACE.xs + 2)
        self.search_edit = kit.search_box("搜索 skill 名称 / 描述（中英文均可）…",
                                          on_change=lambda _t: self._apply_filter())
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("pkCombo")
        self.source_combo.currentIndexChanged.connect(lambda _i: self._apply_filter())
        self.btn_lang = kit.ghost_button("中英对照", on_click=self._cycle_lang)
        self.btn_lang.setToolTip("切换显示语言：英文 / 中文 / 中英对照")
        bar.addWidget(self.search_edit, 3)
        bar.addWidget(self.source_combo, 1)
        bar.addWidget(self.btn_lang, 0)
        self.body.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(2)
        split.setStyleSheet("QSplitter::handle { background: none; }")   # 默认把手在透明窗上会画成黑条

        self.list = kit.ListView()
        self.list.itemClicked.connect(self._on_item_clicked)
        split.addWidget(self.list)

        detail = QWidget()
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(SPACE.sm + 2, 0, 0, 0)
        dv.setSpacing(SPACE.xs + 2)
        self.lbl_name = QLabel("—")
        f = QFont(self._cjk)
        f.setPixelSize(FONT.body + 2)
        f.setBold(True)
        self.lbl_name.setFont(f)
        dv.addWidget(self.lbl_name)
        self.lbl_source = QLabel("")
        fs = QFont(self._cjk)
        fs.setPixelSize(FONT.micro)
        self.lbl_source.setFont(fs)
        self.lbl_source.setStyleSheet("color: %s;" % self._hint_hex)
        dv.addWidget(self.lbl_source)
        self.desc_view = QTextBrowser()
        self.desc_view.setObjectName("pkDetail")
        self.desc_view.setOpenExternalLinks(False)
        dv.addWidget(self.desc_view, 1)

        tri = QHBoxLayout()
        tri.setSpacing(SPACE.xs + 2)
        tri_lbl = QLabel("触发指令")
        ft = QFont(self._cjk)
        ft.setPixelSize(FONT.micro)
        tri_lbl.setFont(ft)
        tri_lbl.setStyleSheet("color: %s;" % self._hint_hex)
        self.ed_trigger = QLineEdit()
        self.ed_trigger.setObjectName("pkSearch")
        self.ed_trigger.setReadOnly(True)
        self.ed_trigger.setPlaceholderText("无触发指令（该 skill 由 AI 自动调用）")
        self.btn_copy = kit.ghost_button("复制", on_click=self._copy_trigger)
        self.btn_copy.setEnabled(False)
        tri.addWidget(tri_lbl, 0)
        tri.addWidget(self.ed_trigger, 1)
        tri.addWidget(self.btn_copy, 0)
        dv.addLayout(tri)

        self.lbl_status = QLabel("")
        self.lbl_status.setFont(fs)
        self.lbl_status.setStyleSheet("color: %s;" % self._hint_hex)
        dv.addWidget(self.lbl_status)

        split.addWidget(detail)
        split.setSizes([250, 380])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        self.body.addWidget(split, 1)

        hint = QLabel("分类按 skill 包划分，点击类名折叠；触发指令复制后粘贴到 AI 聊天框即可")
        hint.setFont(fs)
        hint.setStyleSheet("color: %s;" % self._hint_hex)
        self.footer.insertWidget(0, hint)
        self.btn_close = kit.ghost_button("关闭", on_click=self.close)
        self.footer.addWidget(self.btn_close)
        self.show_footer(True)

    # ── 数据 ────────────────────────────────────
    def refresh(self):
        roots = self._skills_cfg.get("roots") or default_skill_roots()
        self._all_skills = scan_skills(roots)
        self._grouped = categorize_skills(self._all_skills)
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
        return get_zh(s.name, os.path.basename(os.path.dirname(s.path)))

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

    def _category_row(self, text, count):
        """分类行：强调色粗体 + 右侧计数（比列表行更像"标题"）"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(SPACE.xs + 2)
        t = QLabel(text)
        f = QFont(self._cjk)
        f.setPixelSize(FONT.body)
        f.setBold(True)
        t.setFont(f)
        t.setStyleSheet("color: %s;" % self._accent_hex)
        h.addWidget(t, 1)
        c = QLabel(str(count))
        f2 = QFont(self._cjk)
        f2.setPixelSize(FONT.micro)
        c.setFont(f2)
        c.setStyleSheet("color: %s;" % self._hint_hex)
        h.addWidget(c, 0)
        return w

    def _apply_filter(self):
        kw = self.search_edit.text().strip().lower()
        src = self.source_combo.currentData()
        self.list.clear()
        total = 0
        for cat, items in self._grouped:
            matched = []
            for s in items:
                if src and s.root != src:
                    continue
                if kw and kw not in self._searchable_text(s):
                    continue
                matched.append(s)
            if not matched:
                continue
            total += len(matched)
            collapsed = (cat in self._collapsed) and not kw
            arrow = "▸" if collapsed else "▾"
            it, w = kit.item_for(self._category_row("%s %s" % (arrow, cat), len(matched)),
                                 data=("cat", cat))
            it.setFlags(Qt.ItemIsEnabled)
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            if collapsed:
                continue
            for s in matched:
                sub = "⚡ 有指令" if s.trigger else ""
                it2, w2 = kit.item_for(
                    kit.list_row("   " + self._display_name(s), sub,
                                 "", self._accent_hex, compact=True),
                    data=("skill", s))
                it2.setToolTip(s.path)
                self.list.addItem(it2)
                self.list.setItemWidget(it2, w2)
        self.set_subtitle("共 %d 个 skill%s" % (total, "（已折叠）" if self._collapsed else ""))
        if total and self._current is None:
            self.desc_view.setPlainText(states.empty("Skill 详情", "从左侧点选一个 skill 查看说明与触发指令"))
        if total == 0:
            self.lbl_name.setText("—")
            self.desc_view.setPlainText(states.empty("匹配的 Skill", "换个关键词，或在设置里调整扫描根目录"))
            self.ed_trigger.clear()
            self.btn_copy.setEnabled(False)
            self._current = None

    # ── 交互 ────────────────────────────────────
    def _on_item_clicked(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        kind, payload = data
        if kind == "cat":
            if payload in self._collapsed:
                self._collapsed.discard(payload)
            else:
                self._collapsed.add(payload)
            self._apply_filter()
            return
        self._show_skill(payload)

    def _show_skill(self, s):
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
        else:
            self.lbl_name.setText("%s（%s）" % (zh_name, s.name) if zh_name else s.name)
            if has_zh:
                txt = "【中文】%s\n\n【English】%s" % (zh_desc, s.description or "（无描述）")
            else:
                txt = (s.description or "（无描述）") + "\n\n（暂无中文翻译）"
        if s.trigger:
            txt += "\n\n⚡ 触发指令：`%s`" % s.trigger
        elif s.has_manual_trigger and s.trigger_doc:
            txt += "\n\n⚡ 手动触发说明：\n%s" % s.trigger_doc
        elif s.has_manual_trigger:
            txt += "\n\n（该 skill 需要手动触发，具体指令见 SKILL.md 正文）"
        txt += "\n\n路径：%s" % s.path
        self.desc_view.setPlainText(txt)
        self.lbl_source.setText(os.path.basename(os.path.dirname(s.path)) or s.root)
        self.lbl_status.setText("")
        if s.trigger:
            self.ed_trigger.setText(s.trigger)
            self.btn_copy.setEnabled(True)
        else:
            self.ed_trigger.clear()
            if s.has_manual_trigger:
                self.ed_trigger.setPlaceholderText("无短触发指令（手动触发说明见上方正文）")
            else:
                self.ed_trigger.setPlaceholderText("无触发指令（该 skill 由 AI 自动调用）")
            self.btn_copy.setEnabled(False)

    # ── 语言切换 / 动作 ──────────────────────────
    def _cycle_lang(self):
        idx = (self._lang_cycle.index(self._lang_mode) + 1) % len(self._lang_cycle)
        self._lang_mode = self._lang_cycle[idx]
        label = {"en": "English", "zh": "中文", "both": "中英对照"}[self._lang_mode]
        self.btn_lang.setText(label)
        self.btn_lang.setToolTip("切换显示语言：英文 / 中文 / 中英对照（当前：%s）" % label)
        self._apply_filter()
        if self._current is not None:
            self._show_skill(self._current)

    def _copy_trigger(self):
        text = self.ed_trigger.text().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.lbl_status.setText("已复制「%s」✓" % text)
            QTimer.singleShot(1800, lambda: self.lbl_status.setText(""))
