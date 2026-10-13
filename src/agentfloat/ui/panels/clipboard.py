# -*- coding: utf-8 -*-
"""剪贴板历史 — 轻量记录 + 极简面板（v3.12.0 用 panel_kit 重做）

- 记录纯文本剪贴内容（上限 60 条，去重相邻重复），持久化到 config.json
- 面板外观统一由 ui/panel_kit 提供（玻璃底 / 品牌渐变标题栏 / 统一列表与空态）
- 新增搜索；点击条目再次复制；右键删除单条；底部一键清空
"""
import time

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import QMenu, QApplication

from agentfloat.ui import panel_kit as kit

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


class ClipboardPanel(kit.PanelShell):
    """剪贴板历史面板（panel_kit 样板实现）：点击条目复制回剪贴板"""

    copied = pyqtSignal(str)

    def __init__(self, history, theme="light", parent=None):
        super().__init__("剪贴板历史", "", theme=theme, width=360, height=460, parent=parent)
        self.setWindowTitle("AgentFloat — 剪贴板历史")
        self._history = history
        self._query = ""

        self.search = kit.search_box("搜索剪贴板内容…", on_change=self._on_search)
        self.body.addWidget(self.search)

        self.list = kit.ListView()
        self.list.itemClicked.connect(self._copy_item)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.body.addWidget(self.list, 1)

        self.empty = kit.empty_state("剪贴板记录", "复制任意文本后会自动收录", theme)
        self.body.addWidget(self.empty)

        self.status = kit.empty_state("", "", theme)     # 复用样式做一行提示
        self.status.setObjectName("stateHint")
        self.status.setVisible(False)
        self.body.addWidget(self.status)

        self.btn_clear = kit.ghost_button("清空全部", danger=True, on_click=self._clear_all)
        self.btn_close = kit.ghost_button("关闭", on_click=self.close)
        self.footer.insertWidget(0, self.btn_clear)
        self.footer.addWidget(self.btn_close)
        self.show_footer(True)

        self.refresh()

    # ── 数据 → 列表 ────────────────────────────
    def _on_search(self, text):
        self._query = (text or "").strip().lower()
        self.refresh()

    def _visible_entries(self):
        rows = self._history.entries()
        if not self._query:
            return rows
        return [e for e in rows if self._query in (e.get("text") or "").lower()]

    def refresh(self):
        self.list.clear()
        entries = self._visible_entries()
        total = len(self._history.entries())
        for e in entries:
            text = e.get("text") or ""
            ts = e.get("ts") or ""
            preview = text.replace("\n", " ").replace("\r", " ").strip()
            if len(preview) > 120:
                preview = preview[:120] + "…"
            meta = "%s · %d 字符" % (ts, len(text)) if ts else "%d 字符" % len(text)
            kind = "代码" if any(k in text for k in ("def ", "class ", "{", "};", "=>")) else "文本"
            it, w = kit.item_for(
                kit.list_row(preview, meta, kind, "#0A84FF" if kind == "代码" else "#7F8C8D"),
                data=text)
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
        has = bool(entries)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        if self._query and not has:
            self.empty.setText("匹配的剪贴板记录\n换个关键词试试")
        else:
            self.empty.setText("暂无剪贴板记录\n复制任意文本后会自动收录")
        self.set_subtitle("共 %d 条%s" % (total, ("，命中 %d 条" % len(entries)) if self._query else ""))

    # ── 交互 ──────────────────────────────────
    def _copy_item(self, item):
        text = item.data(Qt.UserRole)
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.copied.emit(text)
        self._flash("✓ 已复制到剪贴板")

    def _flash(self, text):
        self.status.setText(text)
        self.status.setVisible(True)
        QTimer.singleShot(1500, lambda: self.status.setVisible(False))

    def _context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(self.styleSheet())
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
        self._flash("已清空")
