# -*- coding: utf-8 -*-
"""面板公共组件库（v3.12.0）—— 让所有 Qt 子面板长得一样

背景：Skills / 剪贴板 / 命令 / 喝水 等面板各自写样式，间距、字号、列表项、
空态、底部操作条都不一样，和 Web 端（快报 / 指南）也是两套语言。

本模块提供一套「积木」，面板只需拼装：

    from agentfloat.ui import panel_kit as kit

    class MyPanel(kit.PanelShell):          # 玻璃底 + 品牌渐变标题栏 + Esc 渐出
        def __init__(...):
            super().__init__("剪贴板历史", subtitle="最近 200 条", width=420, height=560)
            self.body.addWidget(kit.search_box("搜索剪贴板…", on_change=self._filter))
            self.list = kit.ListView()
            self.body.addWidget(self.list, 1)
            self.body.addWidget(kit.empty_state("剪贴板记录", "复制任意文本后会自动收录"))
            self.footer.addWidget(kit.ghost_button("清空", danger=True, on_click=...))

设计令牌统一取自 ui/tokens，配色取自 core/theme，状态文案取自 ui/states。
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from agentfloat.core.theme import get_colors
from agentfloat.ui import states
from agentfloat.ui.anim import fade_in, fade_out
from agentfloat.ui.panel_style import panel_css
from agentfloat.ui.tokens import FONT, RADIUS, SPACE


def panel_qss(theme="light"):
    """面板公共样式（在 panel_css 之上补本库组件的类名）"""
    c = get_colors(theme)
    hint = "#%02X%02X%02X" % tuple(c["HINT"])
    return panel_css(theme) + (
        # 面板头
        "QLabel#pkTitle { font-size: %(ft)dpx; font-weight: 700; }"
        "QLabel#pkSubtitle { color: %(hint)s; font-size: %(fc)dpx; }"
        "QFrame#pkHeader { background: transparent; }"
        # 搜索框
        "QLineEdit#pkSearch { background: %(card)s; border: 1px solid %(bd)s;"
        " border-radius: %(r)dpx; padding: 6px 10px; font-size: %(fb)dpx; }"
        "QLineEdit#pkSearch:focus { border-color: %(acc)s; }"
        # 列表：统一密度与悬停
        "QListWidget#pkList { background: transparent; border: none; padding: 2px; }"
        "QListWidget#pkList::item { padding: 8px 10px; border-radius: %(r)dpx;"
        " margin: 2px 0px; }"
        "QListWidget#pkList::item:hover { background: %(hover)s; }"
        "QListWidget#pkList::item:selected { background: %(acc)s; color: #FFF; }"
        # 底部操作条
        "QFrame#pkFooter { background: transparent; border-top: 1px solid %(bd)s; }"
        "QPushButton#pkGhost { background: transparent; color: %(acc)s;"
        " border: 1px solid %(bd)s; border-radius: %(r)dpx; padding: 5px 12px;"
        " font-size: %(fb)dpx; }"
        "QPushButton#pkGhost:hover { background: %(hover)s; }"
        "QPushButton#pkDanger { color: #FF453A; }"
        "QPushButton#pkPrimary { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        " stop:0 %(acc)s, stop:1 #AF52DE); color: #FFF; border: none;"
        " border-radius: %(r)dpx; padding: 6px 14px; font-size: %(fb)dpx;"
        " font-weight: 600; }"
        % {"hint": hint, "ft": FONT.title, "fc": FONT.caption, "fb": FONT.body,
           "r": RADIUS.sm, "card": "#2C2C31" if theme == "dark" else "#FFFFFF",
           "bd": "rgba(255,255,255,0.10)" if theme == "dark" else "rgba(60,60,67,0.12)",
           "hover": "rgba(255,255,255,0.08)" if theme == "dark" else "rgba(120,120,128,0.10)",
           "acc": "#%02X%02X%02X" % tuple(c["ACCENT"])}
    )


class PanelShell(QDialog):
    """面板外壳：玻璃底 + 品牌渐变标题栏 + Esc 渐出 + 统一内边距

    子类用 self.body 放内容、self.footer 放底部操作（footer 默认隐藏）。
    """

    closed = pyqtSignal()

    def __init__(self, title, subtitle="", theme="light", width=420, height=560,
                 parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(width, height)
        self.setStyleSheet(panel_qss(theme))

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.md, SPACE.sm + 2, SPACE.md, SPACE.md)
        root.setSpacing(SPACE.sm)

        head = QFrame()
        head.setObjectName("pkHeader")
        h = QHBoxLayout(head)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(SPACE.sm)
        box = QVBoxLayout()
        box.setSpacing(1)
        self._title = QLabel(title)
        self._title.setObjectName("pkTitle")
        box.addWidget(self._title)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("pkSubtitle")
        self._subtitle.setVisible(bool(subtitle))
        box.addWidget(self._subtitle)
        h.addLayout(box)
        h.addStretch(1)
        self._close = QPushButton("✕")
        self._close.setObjectName("pkGhost")
        self._close.setFixedSize(24, 24)
        self._close.clicked.connect(self.close)
        h.addWidget(self._close)
        root.addWidget(head)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                          " stop:0 #0A84FF, stop:1 #AF52DE); border: none;")
        root.addWidget(sep)

        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE.sm)
        root.addLayout(self.body, 1)

        self._footer = QFrame()
        self._footer.setObjectName("pkFooter")
        self.footer = QHBoxLayout(self._footer)
        self.footer.setContentsMargins(0, SPACE.sm, 0, 0)
        self.footer.setSpacing(SPACE.sm)
        self.footer.addStretch(1)
        self._footer.setVisible(False)
        root.addWidget(self._footer)

    # 便捷 API
    def set_subtitle(self, text):
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def show_footer(self, visible=True):
        self._footer.setVisible(visible)

    def paintEvent(self, event):
        """玻璃底 + 圆角 + 描边（透明窗上样式表背景不可靠，这里显式绘制）"""
        from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPen
        from PyQt5.QtCore import QRectF
        c = get_colors(self._theme)
        dark = self._theme == "dark"
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        rad = float(RADIUS.xl)
        base = QColor(28, 28, 33) if dark else QColor(252, 252, 255)
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        a = base
        a.setAlpha(250 if dark else 246)
        b = QColor(base)
        b.setAlpha(238 if dark else 234)
        grad.setColorAt(0.0, a)
        grad.setColorAt(1.0, b)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(r, rad, rad)
        sep = QColor(*c["SEPARATOR"])
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(sep, 1.0))
        p.drawRoundedRect(r, rad, rad)
        p.end()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            fade_in(self)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event):
        try:
            event.ignore()
            fade_out(self, on_done=self._after_close)
        except Exception:  # noqa: BLE001
            super().closeEvent(event)

    def _after_close(self):
        self.hide()
        self.closed.emit()
        try:
            self.finished.emit(0)      # 兼容按 QDialog.finished 清理引用的调用方
        except Exception:  # noqa: BLE001
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


def search_box(placeholder, on_change=None, width=None):
    """统一搜索框（回车/输入即时回调）"""
    box = QLineEdit()
    box.setObjectName("pkSearch")
    box.setPlaceholderText(placeholder)
    box.setClearButtonEnabled(True)
    if width:
        box.setFixedWidth(width)
    if on_change is not None:
        box.textChanged.connect(on_change)
    return box


class ListView(QListWidget):
    """统一样式的列表（密度/悬停/选中由 panel_qss 控制）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pkList")
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setSpacing(0)


def list_row(primary, secondary="", badge="", badge_color=None):
    """统一的列表项（主标题 + 次要说明 + 可选角标）"""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(2, 1, 2, 1)
    v.setSpacing(2)
    top = QHBoxLayout()
    top.setSpacing(6)
    t = QLabel(primary)
    from PyQt5.QtGui import QFont as _QFont
    _f = _QFont(t.font())
    _f.setPixelSize(FONT.body)
    _f.setBold(True)
    t.setFont(_f)
    top.addWidget(t, 1)
    if badge:
        b = QLabel(badge)
        b.setStyleSheet("font-size: %dpx; font-weight: 600; padding: 1px 7px;"
                        " border-radius: 999px; color: #FFF; background: %s;"
                        % (FONT.micro, badge_color or "#7F8C8D"))   # 角标自带配色（不继承）
        top.addWidget(b)
    v.addLayout(top)
    if secondary:
        s = QLabel(secondary)
        _f2 = _QFont(s.font())
        _f2.setPixelSize(FONT.caption)
        s.setFont(_f2)
        s.setWordWrap(False)
        s.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(s)
    return w


def item_for(widget, data=None):
    """把自定义行包装成 QListWidgetItem（保持行高自适应）"""
    it = QListWidgetItem()
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    it.setData(Qt.UserRole, data)
    return it, widget


def empty_state(what, hint="", theme="light"):
    """统一空态（文案与样式来自 ui/states）"""
    from PyQt5.QtWidgets import QLabel as _QLabel
    lab = _QLabel(states.empty(what, hint))
    lab.setObjectName("state")
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet(states.css(theme))
    return lab


def ghost_button(text, on_click=None, danger=False, primary=False):
    """底部/头部操作按钮（ghost / danger / primary 三态）"""
    b = QPushButton(text)
    b.setObjectName("pkPrimary" if primary else ("pkDanger" if danger else "pkGhost"))
    b.setCursor(Qt.PointingHandCursor)
    if on_click is not None:
        b.clicked.connect(on_click)
    return b
