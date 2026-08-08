# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — AI 快报面板

无边框毛玻璃窗口：左侧日期列表，右侧正文（分类彩色标签 + 可点击链接）。
样式与 Skills 辅助窗同一套主题体系（毛玻璃标题栏 + 精致关闭按钮 + 卡片化排版）。
"""
import re

from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QListWidget, QListWidgetItem, QTextBrowser, QSplitter,
)

from af_theme import get_colors
from skills_panel import _TitleBar
from news_fetcher import list_archives, load_archive, load_latest

# 分类 → (强调色, 浅底)
CAT_COLORS = {
    "模型": ("#5B8DEF", "rgba(91,141,239,0.14)"),
    "工具": ("#16A085", "rgba(22,160,133,0.14)"),
    "论文": ("#8E44AD", "rgba(142,68,173,0.14)"),
    "产品": ("#E67E22", "rgba(230,126,34,0.14)"),
    "行业": ("#E74C3C", "rgba(231,76,60,0.14)"),
    "综合": ("#7F8C8D", "rgba(127,140,141,0.14)"),
}


def _cat_color(cat):
    return CAT_COLORS.get(cat or "综合", CAT_COLORS["综合"])


# ── 内容解析：AI 摘要格式 / 纯列表格式 → 结构化条目 ──
_AITEM_RE = re.compile(r"^##\s*\[([^\]]+)\]\s*(.+)$", re.M)
_SRC_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_RAW_RE = re.compile(r"^(\d+)\.\s*\[([^\]]+)\]\(([^)\s]+)\)(?:\s*—\s*(.*))?$", re.M)


def _split_blocks(text):
    """按 '## ' 标题切分 AI 摘要格式为块列表"""
    lines = (text or "").splitlines()
    blocks, cur = [], None
    for ln in lines:
        if ln.startswith("## "):
            if cur:
                blocks.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
    if cur:
        blocks.append(cur)
    return blocks


def parse_items(text):
    """返回 [{category, title, url, summary, source}]；AI 或纯列表格式均可"""
    items = []
    m = _AITEM_RE.search(text or "")
    if m:
        for block in _split_blocks(text):
            head = block[0]
            hm = _AITEM_RE.match(head)
            if not hm:
                continue
            cat, title = hm.group(1).strip(), hm.group(2).strip()
            url, source = "", ""
            body = [ln.strip() for ln in block[1:] if ln.strip()]
            for ln in body:
                sm = _SRC_RE.search(ln)
                if sm and "来源" in ln:
                    url = sm.group(2)
                    source = sm.group(1)
                    break
            if not url:
                for ln in body:
                    sm = _SRC_RE.search(ln)
                    if sm:
                        url = sm.group(2)
                        source = sm.group(1)
                        break
            summary = ""
            for ln in body:
                if _SRC_RE.search(ln) and ("来源" in ln or url in ln):
                    continue
                summary = ln
                break
            items.append({"category": cat, "title": title, "url": url,
                          "summary": summary, "source": source})
    else:
        for rm in _RAW_RE.finditer(text or ""):
            items.append({"category": "综合", "title": rm.group(2),
                          "url": rm.group(3), "source": (rm.group(4) or "").strip(),
                          "summary": ""})
    return items


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(text, theme="light"):
    """条目 → 卡片式 HTML：彩色分类标签 + 可点击标题 + 摘要 + 来源"""
    c = get_colors(theme)
    tx = "#%02X%02X%02X" % c["TEXT"]
    hi = "#%02X%02X%02X" % c["HINT"]
    sec = "#%02X%02X%02X" % c["TEXT_SECONDARY"]
    sep = "#%02X%02X%02X" % c["SEPARATOR"]
    parts = []
    # 标题下的 headline 行
    for ln in (text or "").splitlines():
        if ln.strip().startswith("**") and "**" in ln[2:]:
            parts.append('<p style="font-size:13px; color:%s; margin:0 0 6px 0;">%s</p>'
                         % (sec, _esc(ln.strip()).replace("**", "")))
            break
    items = parse_items(text)
    if not items:
        return "<p style='color:%s;'>（无内容）</p>" % hi
    for it in items:
        cat = it.get("category") or "综合"
        fg, bg = _cat_color(cat)
        title = _esc(it.get("title") or "?")
        url = (it.get("url") or "").strip()
        summary = _esc(it.get("summary") or "").strip()
        source = _esc(it.get("source") or "")
        link_html = ('<a href="%s" style="color:%s; text-decoration:none;">%s</a>'
                     % (url, tx, title)) if url else ('<span style="color:%s;">%s</span>' % (tx, title))
        src_html = ""
        if url:
            host = re.sub(r"^https?://(www\.)?", "", url).rstrip("/").split("/")[0]
            src_html = ('<span style="color:%s; font-size:11px;">↗ %s</span>'
                        % (hi, _esc(host or source or "链接")))
        elif source:
            src_html = '<span style="color:%s; font-size:11px;">%s</span>' % (hi, source)
        parts.append(
            '<div style="border-bottom:1px solid %s; padding:10px 2px 12px 2px;">'
            '<div style="margin-bottom:5px;"><span style="display:inline-block;'
            ' background:%s; color:%s; border-radius:4px; padding:1px 8px;'
            ' font-size:11px; margin-right:8px;">%s</span>%s</div>'
            % (sep, bg, fg, _esc(cat), link_html))
        if summary:
            parts.append('<p style="color:%s; font-size:12.5px; line-height:1.6; margin:2px 0 4px 0;">%s</p>'
                         % (sec, summary))
        parts.append('<div>%s</div></div>' % src_html)
    return "\n".join(parts)


class NewsPanel(QDialog):
    """AI 快报面板"""
    news_read = pyqtSignal()
    generate_requested = pyqtSignal()

    def __init__(self, theme="light", parent=None):
        super().__init__(parent)
        self._theme = theme
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
        banner = "rgba(255,255,255,0.06)" if is_dark else "rgba(255,255,255,0.62)"
        hover_bg = "rgba(255,255,255,0.09)" if is_dark else "rgba(120,120,128,0.10)"
        return (
            "QDialog { background: %s; border: 1px solid %s; border-radius: 14px; }" % (sf, bd) +
            "QFrame#titleBar { background: %s; border-top-left-radius: 14px;"
            " border-top-right-radius: 14px; border-bottom: 1px solid %s; }" % (banner, bd) +
            "QListWidget, QTextBrowser { background: %s; color: %s;"
            " border: 1px solid %s; border-radius: 8px; padding: 4px; font-size: 12px; }" % (card, tx, bd) +
            "QListWidget::item { padding: 8px 8px; border-radius: 7px; margin: 2px; }" +
            "QListWidget::item:hover { background: %s; }" % hover_bg +
            "QListWidget::item:selected { background: %s; color: #FFF; border-radius: 7px; }" % ac +
            "QPushButton { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 6px 14px; font-size: 12px; }" % (card, ac, bd) +
            "QPushButton:hover { background: %s; }" % sf +
            "QPushButton:disabled { color: %s; }" % hi +
            "QLabel { color: %s; font-size: 12px; }" % tx +
            "QProgressBar { border: none; background: transparent; height: 6px; }" +
            "QProgressBar::chunk { background: %s; border-radius: 3px; }" % ac
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
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_generate = QPushButton("⚡ 生成今日快报")
        self.btn_generate.setToolTip("抓取各数据源并用本地 Agent 生成今日速览")
        self.btn_generate.clicked.connect(self.generate_requested.emit)
        bar.addWidget(self.lbl_latest)
        bar.addStretch()
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_generate)
        root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)          # 忙碌指示
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        split = QSplitter(Qt.Horizontal)
        self.date_list = QListWidget()
        self.date_list.setMaximumWidth(240)
        self.date_list.currentItemChanged.connect(self._on_select)
        split.addWidget(self.date_list)

        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setStyleSheet(
            "QTextBrowser { border: none; padding: 12px; background: %s; }" % (
                "#%02X%02X%02X" % get_colors(self._theme)["GLASS_BG"]))
        split.addWidget(self.viewer)
        split.setSizes([220, 620])
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        hint = QLabel("点击日期查看历史快报；标题可直接点击打开；生成失败会自动回退为标题列表。")
        hint.setStyleSheet("color: #%02X%02X%02X;" % get_colors(self._theme)["HINT"])
        bottom.addWidget(hint)
        bottom.addStretch()
        root.addLayout(bottom)

        self.news_read.emit()

    # ── 数据 ────────────────────────────────────
    def refresh(self):
        self._archives = list_archives()
        latest = load_latest()
        self.date_list.blockSignals(True)
        self.date_list.clear()
        for date, count in self._archives:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, date)
            it.setSizeHint(QSize(0, 40))
            it.setText("%s · %d 条" % (date, count))
            self.date_list.addItem(it)
        self.date_list.blockSignals(False)
        if latest:
            self.lbl_latest.setText("最近生成 %s · %d 条%s" % (
                latest.get("date", "?"), latest.get("count", 0),
                " · AI 摘要" if latest.get("used_ai") else " · 标题列表"))
        else:
            self.lbl_latest.setText("暂无快报，点击「⚡ 生成今日快报」开始")
        if self._archives:
            self.date_list.setCurrentRow(0)
        else:
            self._show_empty()

    def _show_empty(self):
        c = get_colors(self._theme)
        hi = "#%02X%02X%02X" % c["HINT"]
        self.viewer.setHtml(
            '<div style="text-align:center; margin-top:120px;">'
            '<p style="font-size:34px; margin:0;">📰</p>'
            '<p style="color:%s; font-size:14px; margin-top:14px;">尚无快报</p>'
            '<p style="color:%s; font-size:12px;">点击右上角「⚡ 生成今日快报」，'
            'AgentFloat 将抓取 Hacker News / GitHub Trending / 少数派 / 量子位，'
            '并用你的本地 Agent 生成今日 AI 速览。</p></div>' % (hi, hi))

    def on_generated(self, payload):
        self.refresh()
        date = payload.get("date", "")
        if date:
            for i in range(self.date_list.count()):
                if self.date_list.item(i).data(Qt.UserRole) == date:
                    self.date_list.setCurrentRow(i)
                    break

    def set_generating(self, busy):
        self.progress.setVisible(busy)
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
        body = render_html(data.get("raw_md") or "", self._theme)
        err = (data.get("source_errors") or [])
        foot = ""
        if err:
            foot = ('<p style="color:#%02X%02X%02X; font-size:11px; margin-top:12px;">'
                    '部分数据源不可用：%s</p>' % (
                        get_colors(self._theme)["HINT"],
                        "；".join(err[:3])))
        self.viewer.setHtml(body + foot)
