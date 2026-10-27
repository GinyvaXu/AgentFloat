# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skills 辅助窗（v3.12.0 用 panel_kit 重做）

- 外壳 / 搜索 / 列表 / 空态统一由 ui/panel_kit 提供（更小更轻：660×520）
- 左：按 skill 包分类的扁平列表（分类行可点击折叠，skill 行带触发角标）
- 右：详情区（中英对照三态切换、触发指令可见可复制）
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QLabel, QLineEdit, QComboBox, QTextBrowser, QSplitter,
    QHBoxLayout, QVBoxLayout, QWidget, QApplication,
)

from agentfloat.core.theme import get_colors
from agentfloat.services.skills.scanner import scan_skills, default_skill_roots, categorize_skills
from agentfloat.services.skills.translations import get_zh
from agentfloat.ui import panel_kit as kit
from agentfloat.ui import states
from agentfloat.ui.tokens import FONT, SPACE


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
        self._mode = "installed"      # installed | discover（C 线）
        self._cjk = "Microsoft YaHei"
        c = get_colors(theme)
        self._accent_hex = "#%02X%02X%02X" % c["ACCENT"]
        self._hint_hex = "#%02X%02X%02X" % c["HINT"]
        self._setup_ui()
        self.refresh()

    # ── 界面 ────────────────────────────────────
    def _setup_ui(self):
        bar = QHBoxLayout()
        bar.setSpacing(SPACE.xs_plus)
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
        self.btn_discover = kit.ghost_button("发现", on_click=self._toggle_mode)
        self.btn_discover.setToolTip("查看 Skill 车间发现的条目（只读）")
        bar.addWidget(self.btn_discover, 0)
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
        dv.setContentsMargins(SPACE.sm_plus, 0, 0, 0)
        dv.setSpacing(SPACE.xs_plus)
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
        tri.setSpacing(SPACE.xs_plus)
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
        # v3.18.5：workshop 已能 list_entries（38 条），但其条目缺分类根路径，
        # 直接替换会让分类全落到「其他」；列表暂用扫描器，接「发现/可更新」时再切。
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

    def _toggle_mode(self):
        self._mode = "discover" if self._mode == "installed" else "installed"
        self.btn_discover.setText("返回已安装" if self._mode == "discover" else "发现")
        self.search_edit.clear()
        self._apply_filter()

    def _fill_discover(self):
        """发现视图（只读）：workshop 的 entries，按自带 category 分组"""
        self.list.clear()
        entries = []
        try:
            from agentfloat.core.config import load_config
            from agentfloat.services.skills.workshop import default_workshop
            payload = default_workshop(config=load_config()).list_entries()
            entries = payload.get("entries") or []
        except Exception:  # noqa: BLE001
            entries = []
        groups, order = {}, []
        for e in entries:
            cat = e.get("category") or "其他"
            if cat not in groups:
                groups[cat] = []
                order.append(cat)
            groups[cat].append(e)
        for cat in order:
            it, w = kit.item_for(self._category_row("%s %s" % ("▾", cat), len(groups[cat])),
                                 data=("cat", cat))
            it.setFlags(Qt.ItemIsEnabled)
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            for e in groups[cat]:
                badge = "已安装" if e.get("installed") else (
                    "有更新" if e.get("updateAvailable") else "可安装")
                color = self._accent_hex if e.get("installed") else "#7F8C8D"
                sub = (e.get("description") or "")[:56]
                _row = kit.list_row("   " + (e.get("name") or ""), sub, badge, color)
                _btn = None
                if e.get("installable") and not e.get("installed"):
                    _btn = kit.ghost_button("安装", on_click=lambda _c=False, ent=e: self._install_entry(ent))
                elif e.get("updateAvailable"):
                    _btn = kit.ghost_button("更新", on_click=lambda _c=False, ent=e: self._update_entry(ent))
                if _btn is not None:
                    _wrap = QWidget()
                    _h = QHBoxLayout(_wrap)
                    _h.setContentsMargins(0, 0, 0, 0)
                    _h.setSpacing(6)
                    _h.addWidget(_row, 1)
                    _h.addWidget(_btn, 0)
                    _row = _wrap
                it2, w2 = kit.item_for(_row, data=("discover", e))
                self.list.addItem(it2)
                self.list.setItemWidget(it2, w2)
        self.set_subtitle("发现 %d 个条目（只读）" % len(entries))
        if not entries:
            self.desc_view.setPlainText(states.empty("暂无可发现的 Skill", "检查网络或稍后刷新"))
        else:
            self.desc_view.setPlainText(states.empty("Skill 车间", "从左侧选择一个条目查看说明"))

    def _install_entry(self, entry):
        name = entry.get("name") or entry.get("entryId") or "该条目"
        if not kit.confirm(self, "安装 Skill",
                           "将安装「%s」。安装前会自动备份，失败可回滚。" % name,
                           ok_text="安装", theme=self._theme):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from agentfloat.core.config import load_config
            from agentfloat.services.skills.workshop import default_workshop
            res = default_workshop(config=load_config()).install(entry.get("entryId") or "")
            ok = (not isinstance(res, dict)) or res.get("ok", True)
            self.flash(("已安装：%s" % name) if ok else ("安装失败：%s" % (res.get("error") or res)))
        except Exception as e:  # noqa: BLE001
            self.flash("安装失败：%s" % e)
        finally:
            QApplication.restoreOverrideCursor()
        if self._mode == "discover":
            self._fill_discover()

    def _update_entry(self, entry):
        name = entry.get("name") or entry.get("entryId") or "该条目"
        if not kit.confirm(self, "更新 Skill",
                           "将更新「%s」到最新版本。" % name, ok_text="更新", theme=self._theme):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from agentfloat.core.config import load_config
            from agentfloat.services.skills.workshop import default_workshop
            res = default_workshop(config=load_config()).update(entry.get("entryId") or "")
            ok = (not isinstance(res, dict)) or res.get("ok", True)
            self.flash(("已更新：%s" % name) if ok else ("更新失败：%s" % (res.get("error") or res)))
        except Exception as e:  # noqa: BLE001
            self.flash("更新失败：%s" % e)
        finally:
            QApplication.restoreOverrideCursor()
        if self._mode == "discover":
            self._fill_discover()

    def _category_row(self, text, count):
        """分类行：强调色粗体 + 右侧计数（比列表行更像"标题"）"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(SPACE.xs_plus)
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
        if self._mode == "discover":
            self._fill_discover()
            return
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
        if kind == "discover":
            self.lbl_name.setText(payload.get("name") or "")
            self.lbl_source.setText(payload.get("category") or "")
            self.desc_view.setPlainText(payload.get("description") or "")
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
            self.flash("已复制「%s」✓" % text, label=self.lbl_status)   # v3.14.0：统一 flash
