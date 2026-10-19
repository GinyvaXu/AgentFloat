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
from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from agentfloat.core.theme import get_colors
from agentfloat.ui import states
from agentfloat.ui.anim import fade_in, fade_out
from agentfloat.ui.motion import Tokens, drive, legacy_motion, reduced_motion, spring
from agentfloat.ui.panel_style import panel_css
from agentfloat.ui.tokens import FONT, RADIUS, SPACE


def panel_qss(theme="light"):
    """面板公共样式（在 panel_css 之上补本库组件的类名）"""
    c = get_colors(theme)
    hint = "#%02X%02X%02X" % tuple(c["HINT"])
    return panel_css(theme) + (
        # 面板头
        "QLabel#pkTitle { font-size: %(fb)dpx; font-weight: 700; }"
        "QLabel#pkSubtitle { color: %(hint)s; font-size: %(fm)dpx; padding-left: 6px; }"
        "QPushButton#pkClose { background: none; border: none; color: %(hint)s;"
        " font-size: %(fm)dpx; border-radius: %(r)dpx; }"
        "QPushButton#pkClose:hover { background: %(hover)s; color: %(acc)s; }"
        "QFrame#pkHeader { background: none; }"
        # 搜索框
        "QLineEdit#pkSearch { background: %(card)s; border: 1px solid %(bd)s;"
        " border-radius: %(r)dpx; padding: 6px 10px; font-size: %(fb)dpx; }"
        "QLineEdit#pkSearch:focus { border-color: %(acc)s; }"
        # 下拉框 / 详情区
        "QComboBox#pkCombo { background: %(card)s; color: %(tx)s; border: 1px solid %(bd)s;"
        " border-radius: %(r)dpx; padding: 3px 8px; font-size: %(fc)dpx; }"
        "QComboBox#pkCombo::drop-down { border: none; width: 16px; }"
        "QComboBox#pkCombo QAbstractItemView { background: %(card)s; color: %(tx)s;"
        " border: 1px solid %(bd)s; selection-background-color: %(acc)s; }"
        "QTextBrowser#pkDetail { background: %(card)s; color: %(tx)s; border: 1px solid %(bd)s;"
        " border-radius: %(r)dpx; padding: 8px; font-size: %(fb)dpx; }"
        # 列表：统一密度与悬停
        "QListWidget#pkList { background: none; border: none; padding: 2px; }"
        "QListWidget#pkList::item { padding: 5px 8px; border-radius: %(r)dpx;"
        " margin: 1px 0px; }"
        "QListWidget#pkList::item:hover { background: %(hover)s; }"
        "QListWidget#pkList::item:selected { background: %(sel)s; }"
        # 底部操作条
        "QFrame#pkFooter { background: none; border-top: 1px solid %(bd)s; }"
        "QPushButton#pkGhost { background: none; color: %(acc)s;"
        " border: 1px solid %(bd)s; border-radius: %(r)dpx; padding: 3px 10px;"
        " font-size: %(fc)dpx; }"
        "QPushButton#pkGhost:hover { background: %(hover)s; }"
        "QPushButton#pkGhost:disabled { color: %(hint)s; border-color: %(bd)s; background: none; }"
        "QPushButton#pkDanger { color: #FF453A; }"
        "QPushButton#pkPrimary { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        " stop:0 %(acc)s, stop:1 #AF52DE); color: #FFF; border: none;"
        " border-radius: %(r)dpx; padding: 4px 12px; font-size: %(fc)dpx;"
        " font-weight: 600; }"
        "QPushButton#pkPrimary:disabled { background: %(card)s; color: %(hint)s;"
        " border: 1px solid %(bd)s; }"
        % {"hint": hint, "fc": FONT.caption, "fb": FONT.body,
           "fm": FONT.micro, "r": RADIUS.sm, "card": "#2C2C31" if theme == "dark" else "#FFFFFF",
           "bd": "rgba(255,255,255,0.10)" if theme == "dark" else "rgba(60,60,67,0.12)",
           "hover": "rgba(255,255,255,0.08)" if theme == "dark" else "rgba(120,120,128,0.10)",
           "acc": "#%02X%02X%02X" % tuple(c["ACCENT"]),
           "tx": "#%02X%02X%02X" % tuple(c["TEXT"]),
           "sel": "rgba(10,132,255,0.22)" if theme == "dark" else "rgba(10,132,255,0.14)"}
    )


class _Header(QFrame):
    """面板头：可按住拖动整个面板（无边框窗口的移动方式）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag = None
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPos() - self.window().frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and (event.buttons() & Qt.LeftButton):
            self.window().move(event.globalPos() - self._drag)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        event.accept()


class PanelShell(QDialog):
    """面板外壳：玻璃底 + 品牌渐变标题栏 + Esc 渐出 + 统一内边距

    子类用 self.body 放内容、self.footer 放底部操作（footer 默认隐藏）。
    """

    closed = pyqtSignal()

    def __init__(self, title, subtitle="", theme="light", width=360, height=460,
                 parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(width, height)
        self.setStyleSheet(panel_qss(theme))

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE.sm + 2, SPACE.sm, SPACE.sm + 2, SPACE.sm)
        root.setSpacing(SPACE.xs + 2)

        head = _Header(self)
        head.setObjectName("pkHeader")
        head.setAttribute(Qt.WA_TranslucentBackground, True)
        h = QHBoxLayout(head)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(SPACE.sm)
        self._title = QLabel(title)
        self._title.setObjectName("pkTitle")
        self._title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        h.addWidget(self._title)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("pkSubtitle")
        self._subtitle.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._subtitle.setVisible(bool(subtitle))
        h.addWidget(self._subtitle)      # 单行：副标题跟在标题右侧（更轻）
        h.addStretch(1)
        self._close = QPushButton("✕")
        self._close.setObjectName("pkClose")
        self._close.setFixedSize(20, 20)
        self._close.clicked.connect(self.close)
        h.addWidget(self._close)
        root.addWidget(head)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                          " stop:0 rgba(10,132,255,0.85), stop:1 rgba(175,82,222,0.85));"
                          " border: none;")
        root.addWidget(sep)

        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE.xs + 2)
        root.addLayout(self.body, 1)

        self._footer = QFrame()
        self._footer.setObjectName("pkFooter")
        self._footer.setAttribute(Qt.WA_TranslucentBackground, True)
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

    # ── v3.13.0：统一状态提示（显示 → 150ms 淡出，不再硬切）──────────
    def _flash_label(self):
        lab = getattr(self, "_flash", None)
        if lab is None:
            lab = QLabel("")
            lab.setObjectName("pkSubtitle")        # 复用副标题样式（hint 色 / micro 字号）
            self.footer.insertWidget(0, lab)
            self._flash = lab
        return lab

    def _ensure_flash_anim(self, lab):
        if getattr(lab, "_flash_anim", None) is not None:
            return
        from PyQt5.QtCore import QEasingCurve, QPropertyAnimation
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        fx = QGraphicsOpacityEffect(lab)
        lab.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", lab)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(lambda: lab.setVisible(False))     # 只连一次
        lab._flash_anim = anim
        timer = QTimer(lab)
        timer.setSingleShot(True)
        timer.timeout.connect(anim.start)
        lab._flash_timer = timer

    def flash(self, text, label=None, duration_ms=1600):
        """统一状态提示：显示 text，duration_ms 后 150ms 淡出

        v3.13.0：替代各面板 singleShot(1500/1800) 的瞬间隐藏；
        `motion.legacy_motion()` 打开时回退为立即隐藏（原始观感）。
        """
        lab = label or self._flash_label()
        self._ensure_flash_anim(lab)
        lab.setText(text)
        lab.setVisible(True)
        try:
            lab.graphicsEffect().setOpacity(1.0)
        except Exception:  # noqa: BLE001
            pass
        lab._flash_anim.stop()
        lab._flash_anim.setDuration(1 if legacy_motion() else Tokens.DUR_FLASH_MS)
        lab._flash_timer.stop()
        lab._flash_timer.start(max(200, int(duration_ms)))
        return lab

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
        a.setAlpha(232 if dark else 238)
        b = QColor(base)
        b.setAlpha(214 if dark else 222)
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
        # 透明窗里，子控件若用"透明背景"填充会把父级玻璃擦成透明洞 → 显式声明不绘背景
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.viewport().setAttribute(Qt.WA_TranslucentBackground, True)

    # ── v3.13.0：增删开合动画（列表项从 0 高度展开 / 收拢到 0 静息后释放）───
    def insert_animated(self, widget, data=None, delay_ms=0):
        """带开合动画插入一行；返回 (item, widget)

        - 新项从 0 高度"展开"，其后项同步让位（布局按目标高度算）
        - delay_ms：错峰延迟（配合 stagger_delay() 形成波浪）
        - legacy 模式或 reduced-motion 下直接落位
        """
        it, w = item_for(widget, data=data)
        self.addItem(it)
        self.setItemWidget(it, w)
        if legacy_motion() or reduced_motion() or delay_ms < 0:
            return it, w
        target = max(1, int(w.sizeHint().height()))

        def _apply(v):
            h = int(max(0, min(target, v)))
            it.setSizeHint(QSize(0, h))
            w.setMaximumHeight(h)

        def _begin():
            if self.row(it) < 0:
                return
            st = spring(0.0, Tokens.UI)
            drive(st.to(float(target)), _apply)

        _apply(0)
        if delay_ms:
            QTimer.singleShot(int(delay_ms), _begin)
        else:
            _begin()
        return it, w

    def remove_animated(self, item, on_done=None):
        """收拢到 0 后再真正删除（静息后才释放，避免闪跳）"""
        w = self.itemWidget(item)
        row = self.row(item)
        if w is None or row < 0:
            return
        if legacy_motion() or reduced_motion():
            self.takeItem(row)
            if on_done:
                on_done()
            return
        start = float(max(1, w.height() or w.sizeHint().height()))

        def _apply(v):
            h = int(max(0, v))
            item.setSizeHint(QSize(0, h))
            w.setMaximumHeight(h)

        def _done():
            r = self.row(item)
            if r >= 0:
                self.takeItem(r)
            if on_done:
                on_done()

        st = spring(start, Tokens.UI_COLLAPSE)
        drive(st.to(0.0), _apply, _done)

    def stagger_delay(self, index, selected_index=-1, factor=None):
        """波浪错峰：离选中项越远，延迟越大（list 0.20 / row 0.15）"""
        f = Tokens.STAGGER_ROW if factor is None else float(factor)
        rel = abs(int(index) - int(selected_index)) if selected_index >= 0 else int(index)
        return int(rel * f * 100)


def list_row(primary, secondary="", badge="", badge_color=None, compact=True):
    """统一的列表项（默认单行紧凑：主文本 + 右侧次要信息 + 可选淡角标）

    compact=False 时退化为两行（主文本一行、次要信息一行），适合说明较长的面板。
    """
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(2, 0, 2, 0)
    v.setSpacing(1)
    top = QHBoxLayout()
    top.setSpacing(6)
    from PyQt5.QtGui import QFont as _QFont
    t = QLabel(primary)
    _f = _QFont(t.font())
    _f.setPixelSize(FONT.body)
    t.setFont(_f)
    t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    top.addWidget(t, 1)
    if badge:
        b = QLabel(badge)
        _bc = badge_color or "#7F8C8D"
        b.setStyleSheet("font-size: %dpx; font-weight: 600; padding: 0px 6px;"
                        " border-radius: 999px; color: %s;"
                        " background: rgba(%d,%d,%d,0.16);"
                        " border: 1px solid rgba(%d,%d,%d,0.34);"
                        % (FONT.micro, _bc, int(_bc[1:3], 16), int(_bc[3:5], 16),
                           int(_bc[5:7], 16), int(_bc[1:3], 16), int(_bc[3:5], 16),
                           int(_bc[5:7], 16)))
        top.addWidget(b)
    v.addLayout(top)
    if secondary:
        _f2 = _QFont(t.font())
        _f2.setPixelSize(FONT.micro)
        sec = QLabel(secondary)
        sec.setFont(_f2)
        sec.setWordWrap(False)
        if compact:
            top.addWidget(sec, 0)          # 单行：次要信息靠右
        else:
            sec.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            v.addWidget(sec)
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
