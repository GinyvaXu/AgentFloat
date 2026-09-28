# -*- coding: utf-8 -*-
"""面板统一新风格（PATCH 3.3.0）

对齐环形菜单的「深色玻璃 + 品牌渐变」设计语言：
- 窗口：径向渐变玻璃底 + 1px 边框 + 16px 圆角
- 标题栏：品牌渐变分隔线 + 半透明底
- 控件：主按钮品牌渐变、幽灵按钮半透明、危险按钮红、输入/列表/滚动条统一

用法：各面板在自己的样式前拼接 ``panel_css(theme)``，再用局部规则覆盖细节。
"""
from agentfloat.core.theme import get_colors

ACCENT = "#0a84ff"
ACCENT_2 = "#af52de"


def _hex(rgb):
    return "#%02X%02X%02X" % (rgb[0], rgb[1], rgb[2])


def panel_css(theme="light"):
    c = get_colors(theme)
    is_dark = theme == "dark"
    tx = _hex(c["TEXT"])
    hint = _hex(c["HINT"])
    sep = _hex(c["SEPARATOR"])
    accent = _hex(c.get("ACCENT", (10, 132, 255)))
    surface = _hex(c["SURFACE"])
    card = "#2c2c31" if is_dark else "#FFFFFF"
    hover = "rgba(255,255,255,0.08)" if is_dark else "rgba(120,120,128,0.10)"
    glass_top = "rgba(40,40,48,0.98)" if is_dark else "rgba(252,252,255,0.98)"
    glass_bottom = "rgba(20,20,25,0.98)" if is_dark else "rgba(238,238,246,0.98)"
    header = "rgba(255,255,255,0.06)" if is_dark else "rgba(255,255,255,0.65)"
    return (
        # 窗口玻璃底 + 圆角
        "QDialog { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        " stop:0 %(top)s, stop:1 %(bottom)s); border: 1px solid %(sep)s;"
        " border-radius: 16px; }" % {"top": glass_top, "bottom": glass_bottom, "sep": sep} +
        "QFrame#titleBar { background: %(h)s; border-top-left-radius: 16px;"
        " border-top-right-radius: 16px; border-bottom: 2px solid qlineargradient("
        "x1:0,y1:0,x2:1,y2:0, stop:0 %(a1)s, stop:1 %(a2)s); }" % {"h": header, "a1": ACCENT, "a2": ACCENT_2} +
        "QFrame#titleBar QLabel { font-size: 13px; font-weight: 600; }" +
        # 文字
        "QLabel { color: %s; font-size: 12px; background: transparent; }" % tx +
        "QLabel#hint, QLabel.hint { color: %s; }" % hint +
        # 按钮
        "QPushButton { background: %(card)s; color: %(ac)s; border: 1px solid %(sep)s;"
        " border-radius: 9px; padding: 6px 13px; font-size: 12px; }" % {"card": card, "ac": accent, "sep": sep} +
        "QPushButton:hover { background: %s; }" % hover +
        "QPushButton:pressed { background: %s; }" % surface +
        "QPushButton#primary, QPushButton.primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        " stop:0 %(a1)s, stop:1 %(a2)s); color: #FFF; border: none; font-weight: 600; }" % {"a1": ACCENT, "a2": ACCENT_2} +
        "QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        " stop:0 %(a2)s, stop:1 %(a1)s); }" % {"a1": ACCENT, "a2": ACCENT_2} +
        "QPushButton#danger, QPushButton.danger { color: #FF453A; }" +
        # 输入
        "QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {"
        " background: %(card)s; color: %(tx)s; border: 1px solid %(sep)s;"
        " border-radius: 9px; padding: 6px 9px; font-size: 12px;"
        " selection-background-color: %(ac)s; }" % {"card": card, "tx": tx, "sep": sep, "ac": accent} +
        "QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid %s; }" % accent +
        "QComboBox QAbstractItemView { background: %(card)s; color: %(tx)s;"
        " border: 1px solid %(sep)s; border-radius: 8px; selection-background-color: %(ac)s; }"
        % {"card": card, "tx": tx, "sep": sep, "ac": accent} +
        # 列表 / 树
        "QListWidget, QTreeWidget, QTableWidget { background: %(card)s; color: %(tx)s;"
        " border: 1px solid %(sep)s; border-radius: 12px; padding: 5px; font-size: 12px;"
        " outline: 0; }" % {"card": card, "tx": tx, "sep": sep} +
        "QListWidget::item, QTreeWidget::item { padding: 8px 9px; border-radius: 8px; margin: 2px; }" +
        "QListWidget::item:hover, QTreeWidget::item:hover { background: %s; }" % hover +
        "QListWidget::item:selected, QTreeWidget::item:selected { background: qlineargradient("
        "x1:0,y1:0,x2:1,y2:1, stop:0 %(a1)s, stop:1 %(a2)s); color: #FFF; border-radius: 8px; }"
        % {"a1": ACCENT, "a2": ACCENT_2} +
        "QHeaderView::section { background: transparent; color: %s; border: none; padding: 6px; }" % hint +
        # 滚动条（细、半透明）
        "QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }" +
        "QScrollBar::handle:vertical { background: %s; border-radius: 4px; min-height: 30px; }" % (
            "rgba(255,255,255,0.22)" if is_dark else "rgba(0,0,0,0.18)") +
        "QScrollBar::handle:vertical:hover { background: %s; }" % (
            "rgba(255,255,255,0.34)" if is_dark else "rgba(0,0,0,0.30)") +
        "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }" +
        "QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 4px; }" +
        "QScrollBar::handle:horizontal { background: %s; border-radius: 4px; min-width: 30px; }" % (
            "rgba(255,255,255,0.22)" if is_dark else "rgba(0,0,0,0.18)") +
        # 提示/状态
        "QToolTip { background: %(card)s; color: %(tx)s; border: 1px solid %(sep)s;"
        " border-radius: 8px; padding: 5px 8px; }" % {"card": card, "tx": tx, "sep": sep}
    )


class FadePanelMixin(object):
    """统一渐入渐出 + Esc 关闭（PATCH 3.3.0/3.3.1）

    用法： ``class XxxPanel(FadePanelMixin, QDialog)``
    """

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from agentfloat.ui.anim import fade_in
            fade_in(self)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event):
        try:
            from agentfloat.ui.anim import fade_out
            event.ignore()
            fade_out(self, on_done=self.hide)
        except Exception:  # noqa: BLE001
            super().closeEvent(event)

    def keyPressEvent(self, event):
        """Esc 关闭面板（渐出）"""
        try:
            from PyQt5.QtCore import Qt
            if event.key() == Qt.Key_Escape:
                self.close()
                return
        except Exception:  # noqa: BLE001
            pass
        super().keyPressEvent(event)
