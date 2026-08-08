# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — AI 快报面板

无边框毛玻璃窗口：左侧日期列表，右侧正文（Markdown → HTML，链接可点击）。
样式复用 SkillsPanel 的主题体系与标题栏组件。
"""
import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextBrowser, QSplitter,
)

from af_theme import get_colors
from skills_panel import _TitleBar
from news_fetcher import list_archives, load_archive, load_latest

# ── Markdown 子集 → HTML ──────────────────────────
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_HEAD_RE = re.compile(r"^(#{1,3})\s+(.*)$")


def md_to_html(text):
    """将快报 Markdown 子集（标题/加粗/链接/列表）转为可点击的 HTML"""
    lines = []
    in_list = False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                lines.append("</ul>")
                in_list = False
            continue
        m = _HEAD_RE.match(line)
        if m:
            if in_list:
                lines.append("</ul>")
                in_list = False
            level, content = len(m.group(1)), m.group(2).strip()
            content = _inline(content)
            size = {1: 20, 2: 16, 3: 14}.get(level, 14)
            lines.append('<p style="font-size:%dpx; font-weight:bold; margin:10px 0 4px 0;">%s</p>'
                         % (size, content))
            continue
        if line.startswith(("- ", "* ", "• ")):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            lines.append("<li>%s</li>" % _inline(line[2:]))
            continue
        m2 = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m2:
            if not in_list:
                lines.append("<ol>")
                in_list = True
            lines.append("<li>%s</li>" % _inline(m2.group(2)))
            continue
        if in_list:
            lines.append("</ul>")
            in_list = False
        lines.append('<p style="margin:4px 0;">%s</p>' % _inline(line))
    if in_list:
        lines.append("</ul>")
    return "\n".join(lines)


def _inline(text):
    """行内格式：链接可点击 + 加粗"""
    def _link(m):
        label, url = m.group(1), m.group(2)
        return '<a href="%s" style="color:#2E86C1; text-decoration:none;">%s</a>' % (url, label)
    text = _LINK_RE.sub(_link, text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    return text


class NewsPanel(QDialog):
    """AI 快报面板"""
    news_read = pyqtSignal()       # 面板被打开（清除未读红点）
    generate_requested = pyqtSignal()  # 用户点击「生成今日快报」

    def __init__(self, theme="light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._cjk = "Microsoft YaHei"
        self._archives = []
        self.setWindowTitle("AgentFloat — AI 快报")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(860, 560)
        self.setStyleSheet(self._stylesheet())
        self._setup_ui()
        self.refresh()

    def _stylesheet(self):
        c = get_colors(self._theme)
        is_dark = self._theme == "dark"
        sf = "#%02X%02X%02X" % c["SURFACE"]
        tx = "#%02X%02X%02X" % c["TEXT"]
        hi = "#%02X%02X%02X" % c["HINT"]
        ac = "#%02X%02X%02X" % c["ACCENT"]
        bd = "#%02X%02X%02X" % c["SEPARATOR"]
        card = "#333336" if is_dark else "#FFFFFF"
        hover_bg = "rgba(255,255,255,0.09)" if is_dark else "rgba(120,120,128,0.10)"
        return (
            "QDialog { background: %s; border: 1px solid %s; border-radius: 14px; }" % (sf, bd) +
            "QListWidget, QTextBrowser { background: %s; color: %s;"
            " border: 1px solid %s; border-radius: 8px; padding: 6px; font-size: 12px; }" % (card, tx, bd) +
            "QListWidget::item { padding: 8px 8px; border-radius: 7px; }" +
            "QListWidget::item:hover { background: %s; }" % hover_bg +
            "QListWidget::item:selected { background: %s; color: #FFF; border-radius: 7px; }" % ac +
            "QPushButton { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 6px 14px; font-size: 12px; }" % (card, ac, bd) +
            "QPushButton:hover { background: %s; }" % sf +
            "QLabel { color: %s; font-size: 12px; }" % tx
        )

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 14)
        root.setSpacing(10)
        self._title = _TitleBar(self, "AI 快报")
        root.addWidget(self._title)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.lbl_latest = QLabel("")
        self.lbl_latest.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        self.btn_generate = QPushButton("⚡ 生成今日快报")
        self.btn_generate.setToolTip("抓取各数据源并用本地 Agent 生成今日速览")
        self.btn_generate.clicked.connect(self.generate_requested.emit)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.lbl_latest)
        bar.addStretch()
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_generate)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        self.date_list = QListWidget()
        self.date_list.setMaximumWidth(240)
        self.date_list.currentItemChanged.connect(self._on_select)
        split.addWidget(self.date_list)

        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)   # 链接可点击
        self.viewer.setStyleSheet(
            "QTextBrowser { border: none; padding: 10px; "
            "background: %s; }" % (
                "#%02X%02X%02X" % get_colors(self._theme)["GLASS_BG"]))
        split.addWidget(self.viewer)
        split.setSizes([220, 620])
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        hint = QLabel("提示：点击日期查看历史快报；链接可直接点击打开。生成失败会自动回退为标题列表。")
        hint.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        bottom.addWidget(hint)
        bottom.addStretch()
        root.addLayout(bottom)

        # 打开面板即视为已读
        self.news_read.emit()

    # ── 数据 ────────────────────────────────────
    def refresh(self):
        """刷新日期列表与最新内容"""
        self._archives = list_archives()
        self.date_list.blockSignals(True)
        self.date_list.clear()
        latest = load_latest()
        for date, count in self._archives:
            it = QListWidgetItem("%s  ·  %d 条" % (date, count))
            it.setData(Qt.UserRole, date)
            self.date_list.addItem(it)
        if latest:
            self.lbl_latest.setText("最近生成：%s（%d 条%s）" % (
                latest.get("generated_at", "?"), latest.get("count", 0),
                " · AI 摘要" if latest.get("used_ai") else " · 标题列表"))
        else:
            self.lbl_latest.setText("暂无快报，点击「生成今日快报」开始")
        self.date_list.blockSignals(False)
        if self._archives:
            self.date_list.setCurrentRow(0)
        else:
            self.viewer.setHtml('<p style="color:#888;">尚无快报。点击右上角「⚡ 生成今日快报」，'
                                'AgentFloat 将抓取 Hacker News / GitHub Trending / 少数派 / 量子位 '
                                '并用你的本地 Agent 生成今日 AI 速览。</p>')

    def on_generated(self, payload):
        """生成完成后刷新并选中今日"""
        self.refresh()
        date = payload.get("date", "")
        if date:
            for i in range(self.date_list.count()):
                if self.date_list.item(i).data(Qt.UserRole) == date:
                    self.date_list.setCurrentRow(i)
                    break

    def set_generating(self, busy):
        self.btn_generate.setEnabled(not busy)
        self.btn_generate.setText("⏳ 生成中…" if busy else "⚡ 生成今日快报")

    def _on_select(self, current, _previous):
        if current is None:
            return
        date = current.data(Qt.UserRole)
        data = load_archive(date) if date else None
        if not data:
            self.viewer.setHtml("<p>无法读取该日期数据。</p>")
            return
        html = md_to_html(data.get("raw_md") or "")
        # 补一条生成信息页脚
        foot = ('<p style="color:#888; font-size:11px; margin-top:14px;">'
                '生成于 %s · 来源 %d 项%s</p>' % (
                    data.get("generated_at", "?"), data.get("count", 0),
                    (" · " + "；".join((data.get("source_errors") or [])[:2]))
                    if data.get("source_errors") else ""))
        self.viewer.setHtml(html + foot)
