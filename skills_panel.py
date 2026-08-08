# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skills 辅助窗（v1.0.6）

无边框毛玻璃窗口：
- 标题栏：整合式（底部细分隔线 + 强调色圆点 + 计数 + 可见关闭按钮），可拖动；
- 左侧：按默认分类（包）的树状列表，点击类名展开/收起，再点 skill 查看详情；
- 搜索时自动展开匹配分类；中英对照三态切换；触发指令可见可复制。
"""
import os

from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QVariantAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QTreeWidget, QTreeWidgetItem, QPushButton, QTextBrowser, QFrame,
    QApplication, QSplitter, QStyle, QProxyStyle,
)

from af_theme import get_colors
from skills_scanner import scan_skills, default_skill_roots, categorize_skills
from skills_translations import get_zh


class _CloseButton(QPushButton):
    """精致版关闭按钮 B：灰圆底 ✕ → 悬停红实底 + 轻微放大（动画过渡）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("关闭")
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_hover)

    def _set_hover(self, v):
        self._hover = float(v)
        self.update()

    def enterEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self._hover
        r = self.rect().adjusted(1, 1, -1, -1)
        # 底圆：灰 → 红
        if h > 0.999:
            bg = QColor(232, 66, 66)
        else:
            g = int(120 + (255 - 120) * h)
            rv = int(120 + (66 - 120) * h)
            b = int(120 + (66 - 120) * h)
            a = int(30 + 215 * h)
            bg = QColor(g, rv, b, a)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawEllipse(r)
        # ✕ 两笔划线（悬停变白并轻微放大）
        cx, cy = self.width() / 2.0, self.height() / 2.0
        s_len = 4.6 + 0.6 * h
        pen = QPen(QColor(255, 255, 255) if h > 0.45 else QColor(132, 132, 132),
                   1.7 + 0.3 * h)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.save()
        p.translate(cx, cy)
        p.scale(1.0 + 0.08 * h, 1.0 + 0.08 * h)
        p.drawLine(QPointF(-s_len, -s_len), QPointF(s_len, s_len))
        p.drawLine(QPointF(-s_len, s_len), QPointF(s_len, -s_len))
        p.restore()
        p.end()


class _ThemedTreeStyle(QProxyStyle):
    """主题色分类树分支箭头（▶ / ▼），替代默认丑陋三角"""

    def __init__(self, accent):
        # 无 base：标准 QProxyStyle 用法，避免包装现有样式导致 teardown 崩溃
        super().__init__()
        self._accent = QColor(*accent)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_IndicatorBranch:
            if option.state & QStyle.State_Children:
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing)
                cx = option.rect.center().x()
                cy = option.rect.center().y()
                s = 4.5
                pen = QPen(self._accent, 1.6)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(self._accent)
                path = QPainterPath()
                if option.state & QStyle.State_Open:
                    path.moveTo(cx - s, cy - s * 0.6)
                    path.lineTo(cx + s, cy - s * 0.6)
                    path.lineTo(cx, cy + s * 0.8)
                else:
                    path.moveTo(cx - s * 0.6, cy - s)
                    path.lineTo(cx - s * 0.6, cy + s)
                    path.lineTo(cx + s * 0.8, cy)
                path.closeSubpath()
                painter.drawPath(path)
                painter.restore()
            return
        return super().drawPrimitive(element, option, painter, widget)


class _TitleBar(QFrame):
    """整合式标题栏：毛玻璃横幅 + 拖动窗口 + 计数 + 精致关闭按钮"""

    def __init__(self, parent, title):
        super().__init__(parent)
        self._parent = parent
        self._drag_pos = None
        self.setObjectName("titleBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(8)

        # 强调色圆点 + 标题
        dot = QLabel("●")
        dot.setStyleSheet("color: %s; font-size: 10px; border: none;" %
                          ("#%02X%02X%02X" % get_colors(parent._theme)["ACCENT"]))
        lay.addWidget(dot)
        t = QLabel(title)
        t.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        lay.addWidget(t)
        lay.addStretch()
        self.lbl_count = QLabel("")
        self.lbl_count.setFont(QFont("Microsoft YaHei", 10))
        lay.addWidget(self.lbl_count)

        btn = _CloseButton()
        btn.clicked.connect(parent.close)
        lay.addWidget(btn)
        self._btn_close = btn

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self._parent.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.LeftButton):
            self._parent.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()


class SkillsPanel(QDialog):
    def __init__(self, skills_cfg, theme="light", parent=None):
        super().__init__(parent)
        self._skills_cfg = skills_cfg or {}
        self._theme = theme
        self._all_skills = []
        self._grouped = []            # [(category, [SkillInfo,...])]
        self._current = None
        self._lang_mode = "both"      # en / zh / both
        self._lang_cycle = ["en", "zh", "both"]
        self._cjk = "Microsoft YaHei"
        self.setWindowTitle("AgentFloat — Skills 辅助窗")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(920, 600)
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
        banner = "rgba(255,255,255,0.06)" if is_dark else "rgba(255,255,255,0.62)"
        hover_bg = "rgba(255,255,255,0.09)" if is_dark else "rgba(120,120,128,0.10)"
        return (
            "QDialog { background: %s; border: 1px solid %s; border-radius: 14px; }" % (sf, bd) +
            "QFrame#titleBar { background: %s; border-top-left-radius: 14px;"
            " border-top-right-radius: 14px; border-bottom: 1px solid %s; }" % (banner, bd) +
            "QTreeWidget, QTextBrowser, QLineEdit, QComboBox { background: %s; color: %s;"
            " border: 1px solid %s; border-radius: 8px; padding: 6px; font-size: 12px; }" % (card, tx, bd) +
            "QTreeWidget::item { padding: 6px 6px; border-radius: 7px; }" +
            "QTreeWidget::item:hover { background: %s; }" % hover_bg +
            "QTreeWidget::item:selected { background: %s; color: #FFF; border-radius: 7px; }" % ac +
            "QTreeWidget::branch { background: transparent; }" +
            "QPushButton { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 6px 14px; font-size: 12px; }" % (card, ac, bd) +
            "QPushButton:hover { background: %s; }" % sf +
            "QPushButton:disabled { color: %s; }" % hi +
            "QLabel { color: %s; font-size: 12px; }" % tx +
            "QFrame#detailCard { background: %s; border: 1px solid %s; border-radius: 10px; }" % (card, bd)
        )

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 14)
        root.setSpacing(10)

        self._title = _TitleBar(self, "Skills 辅助窗")
        root.addWidget(self._title)

        bar = QHBoxLayout()
        bar.setSpacing(8)
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

        left = QFrame()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)   # 原生平滑展开/收起动画
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 保留引用：QProxyStyle 需存活于 widget 生命周期，否则 teardown 崩溃
        self._tree_style = _ThemedTreeStyle(get_colors(self._theme)["ACCENT"])
        self.tree.setStyle(self._tree_style)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.tree)
        split.addWidget(left)

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

        tri = QHBoxLayout()
        tri_lbl = QLabel("触发指令：")
        tri_lbl.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        self.ed_trigger = QLineEdit()
        self.ed_trigger.setReadOnly(True)
        self.ed_trigger.setPlaceholderText("无触发指令（该 skill 由 AI 自动调用）")
        tri.addWidget(tri_lbl)
        tri.addWidget(self.ed_trigger, 1)
        self.btn_copy = QPushButton("复制")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_trigger)
        tri.addWidget(self.btn_copy)
        dv.addLayout(tri)

        act = QHBoxLayout()
        self.lbl_status = QLabel("")
        act.addWidget(self.lbl_status)
        act.addStretch()
        dv.addLayout(act)

        split.addWidget(detail)
        split.setSizes([360, 540])
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        hint = QLabel("提示：分类按 skill 包划分，点击类名展开；触发指令复制后粘贴到对应 AI 聊天框即可。")
        hint.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        bottom.addWidget(hint)
        bottom.addStretch()
        root.addLayout(bottom)

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

    def _apply_filter(self):
        kw = self.search_edit.text().strip().lower()
        src = self.source_combo.currentData()
        ac = "#%02X%02X%02X" % get_colors(self._theme)["ACCENT"]
        self.tree.blockSignals(True)
        self.tree.clear()
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
            top = QTreeWidgetItem(["%s（%d）" % (cat, len(matched))])
            top.setData(0, Qt.UserRole, None)
            top.setFlags(Qt.ItemIsEnabled)
            top.setFont(0, QFont(self._cjk, 12, QFont.Bold))
            top.setForeground(0, QBrush(QColor(ac)))
            top.setToolTip(0, "点击展开 / 收起该分类")
            for s in matched:
                child = QTreeWidgetItem(["%s%s" % (self._display_name(s), "  ⚡" if s.trigger else "")])
                child.setData(0, Qt.UserRole, s)
                child.setToolTip(0, s.path)
                child.setFont(0, QFont(self._cjk, 11))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            if kw:
                top.setExpanded(True)
            total += len(matched)
        self.tree.blockSignals(False)
        self._title.lbl_count.setText("共 %d 个 skill" % total)
        if total == 0:
            self.lbl_name.setText("—")
            self.desc_view.setPlainText("未找到匹配的 skill。")
            self.ed_trigger.clear()
            self.btn_copy.setEnabled(False)
            self._current = None
        elif self.tree.topLevelItemCount():
            top0 = self.tree.topLevelItem(0)
            if not kw and not src:
                top0.setExpanded(True)   # 默认展开第一个分类
            self.tree.setCurrentItem(top0)

    # ── 选中 ────────────────────────────────────
    def _on_item_clicked(self, item, column):
        if item is not None and item.parent() is None:
            item.setExpanded(not item.isExpanded())

    def _on_select(self, current, previous):
        if current is None:
            return
        s = current.data(0, Qt.UserRole)
        if s is None:
            self._show_category(current.text(0))
        else:
            self._show_skill(s)

    def _show_category(self, text):
        self.lbl_name.setText(text)
        self.lbl_source.setText("分类")
        self.desc_view.setPlainText("这是一个 skill 分类，共包含多个 skill。\n\n点击分类名可展开 / 收起；点击下方条目查看详情。")
        self.ed_trigger.clear()
        self.btn_copy.setEnabled(False)
        self.lbl_status.setText("")
        self._current = None

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
        else:  # both
            self.lbl_name.setText("%s（%s）" % (zh_name, s.name) if zh_name else s.name)
            if has_zh:
                txt = "【中文】%s\n\n【English】%s" % (zh_desc, s.description or "（无描述）")
            else:
                txt = s.description or "（无描述）"
                txt += "\n\n（暂无中文翻译）"
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
        text = self.ed_trigger.text().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.lbl_status.setText("已复制「%s」✓" % text)
            QTimer.singleShot(1800, lambda: self.lbl_status.setText(""))
