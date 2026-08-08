# -*- coding: utf-8 -*-
"""剪贴板历史 — 轻量记录 + 极简面板

- 记录纯文本剪贴内容（上限 60 条，去重相邻重复），持久化到 config.json
- 面板无边框毛玻璃风格，与 Skills 辅助窗一致
- 点击条目即可再次复制；右键可删除单条；支持一键清空
"""
import time

from PyQt5.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMenu, QApplication,
)
from PyQt5.QtGui import QFont

from af_theme import get_colors

HISTORY_KEY = "clipboard_history"
MAX_ITEMS = 60


class ClipboardHistory(object):
    """剪贴板历史存储（内存 + 写入 config dict，由主程序统一持久化）"""

    def __init__(self, config=None, max_items=MAX_ITEMS):
        self._config = config if config is not None else {}
        self._max = int(max_items or MAX_ITEMS)
        self._items = []
        self.load()

    def load(self):
        raw = self._config.get(HISTORY_KEY) or []
        self._items = []
        for e in raw:
            if isinstance(e, dict) and e.get("text"):
                self._items.append({"text": str(e["text"]), "ts": str(e.get("ts") or "")})

    def save(self):
        self._config[HISTORY_KEY] = self._items[:self._max]

    def push(self, text):
        text = (text or "").strip()
        if not text or len(text) > 20000:
            return False
        if self._items and self._items[0]["text"] == text:
            return False
        self._items.insert(0, {"text": text, "ts": time.strftime("%H:%M:%S")})
        del self._items[self._max:]
        self.save()
        return True

    def entries(self):
        return list(self._items)

    def remove(self, text):
        self._items = [e for e in self._items if e.get("text") != text]
        self.save()

    def clear(self):
        self._items = []
        self.save()


class ClipboardPanel(QDialog):
    """剪贴板历史面板：点击条目复制回剪贴板"""

    copied = pyqtSignal(str)

    def __init__(self, history, theme="light", parent=None):
        super().__init__(parent)
        self._history = history
        self._theme = theme
        self.setWindowTitle("AgentFloat — 剪贴板历史")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(460, 480)
        self._setup_ui()
        self.refresh()

    # ── UI ────────────────────────────────────
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
        title = QLabel("剪贴板历史")
        f = QFont("Microsoft YaHei", 13, QFont.Bold)
        title.setFont(f)
        bar.addWidget(title)
        self.lbl_count = QLabel("")
        bar.addWidget(self.lbl_count)
        bar.addStretch()
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear_all)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_clear)
        bar.addWidget(self.btn_close)
        root.addLayout(bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["ACCENT"])
        self.lbl_status.setVisible(False)
        root.addWidget(self.lbl_status)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._copy_item)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        root.addWidget(self.list, 1)

    def refresh(self):
        self.list.clear()
        entries = self._history.entries()
        for e in entries:
            text = e.get("text") or ""
            ts = e.get("ts") or ""
            preview = text.replace("\n", " ").replace("\r", " ")
            if len(preview) > 200:
                preview = preview[:200] + "…"
            it = QListWidgetItem(("[%s]  %s" % (ts, preview)) if ts else preview)
            it.setData(Qt.UserRole, text)
            it.setToolTip(text[:1000])
            it.setSizeHint(QSize(0, 46))
            self.list.addItem(it)
        self.lbl_count.setText("共 %d 条" % len(entries))
        if not entries:
            self.list.addItem("暂无剪贴板记录")

    def _copy_item(self, item):
        text = item.data(Qt.UserRole)
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.copied.emit(text)
        self.lbl_status.setText("✓ 已复制到剪贴板")
        self.lbl_status.setVisible(True)
        QTimer.singleShot(1500, lambda: self.lbl_status.setVisible(False))

    def _context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_copy = menu.addAction("复制")
        act_del = menu.addAction("删除此条")
        act = menu.exec_(self.list.mapToGlobal(pos))
        if act == act_copy:
            self._copy_item(item)
        elif act == act_del:
            text = item.data(Qt.UserRole)
            if text:
                self._history.remove(text)
                self.refresh()

    def _clear_all(self):
        self._history.clear()
        self.refresh()
        self.lbl_status.setText("已清空")
        self.lbl_status.setVisible(True)
        QTimer.singleShot(1500, lambda: self.lbl_status.setVisible(False))
