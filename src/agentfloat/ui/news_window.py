# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — AI 日报独立窗口（B 线 2.0，Qt 三栏阅读器）

左栏：日期（历史期数）/ 过滤（全部·未读·收藏）/ 来源
中栏：按分类分组的条目列表（未读 / 收藏角标 + 排序理由）
右栏：条目详情（摘要 + 为什么 + 因子条 + 相关来源 + 原文链接）
顶部：源健康条（正常 / 降级 / 失败 + 单源重试）

数据层完全复用 services/news/fetcher（报告 v2 + B 线附加字段 + 已读收藏状态），
生成仍走浮球的 NewsWorker：窗口只发 generate / cancel / retry 信号。
"""
import os

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtCore import QUrl
from PyQt5.QtWidgets import (
    QFrame, QLabel, QScrollArea, QTextBrowser, QSplitter, QHBoxLayout,
    QVBoxLayout, QWidget,
)

from agentfloat.core.theme import get_colors
from agentfloat.services.news import fetcher as nf
from agentfloat.ui import panel_kit as kit
from agentfloat.ui import states
from agentfloat.ui.tokens import FONT, SPACE

CAT_LABEL = {
    "模型": "模型", "工具": "工具", "论文": "论文", "产品": "产品",
    "行业": "行业", "综合": "综合",
    "ai": "AI", "dev": "开发", "product": "产品", "other": "其它",
}
STATUS_LABEL = {"ok": "正常", "degraded": "降级", "failed": "失败"}


class NewsWindow(kit.PanelShell):
    """AI 日报三栏阅读器"""

    generate_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    retry_source_requested = pyqtSignal(str)
    state_changed = pyqtSignal()

    def __init__(self, theme="light", parent=None):
        super().__init__("AI 日报", "", theme=theme, width=1000, height=640, parent=parent)
        self.setWindowTitle("AgentFloat — AI 日报")
        self._theme = theme
        self._report = None
        self._date = ""
        self._filter = "all"          # all / unread / starred
        self._source = ""             # "" = 全部
        self._current = None
        c = get_colors(theme)
        self._accent_hex = "#%02X%02X%02X" % c["ACCENT"]
        self._hint_hex = "#%02X%02X%02X" % c["HINT"]
        self._ok_hex = "#%02X%02X%02X" % c["OK"]
        self._warn_hex = "#%02X%02X%02X" % c["WARN_FG"]
        self._warning_hex = "#%02X%02X%02X" % c["WARNING"]
        self._cjk = "Microsoft YaHei"
        self._setup_ui()
        self.refresh()

    # ── 界面 ────────────────────────────────────
    def _setup_ui(self):
        self.btn_generate = kit.ghost_button("生成日报", on_click=self.generate_requested.emit)
        self.footer.addWidget(self.btn_generate)
        self.btn_cancel = kit.ghost_button("取消生成", on_click=self.cancel_requested.emit,
                                           danger=True)
        self.btn_cancel.setVisible(False)
        self.footer.insertWidget(1, self.btn_cancel)
        self.btn_export = kit.ghost_button("导出 Markdown", on_click=self._export)
        self.footer.addWidget(self.btn_export)
        self.btn_close = kit.ghost_button("关闭", on_click=self.close)
        self.footer.addWidget(self.btn_close)
        self.show_footer(True)

        # 顶部源健康条（横向滚动，避免 15 个源挤压三栏）
        self.health_scroll = QScrollArea()
        self.health_scroll.setObjectName("newsHealth")
        self.health_scroll.setWidgetResizable(True)
        self.health_scroll.setFixedHeight(42)
        self.health_scroll.setFrameShape(QFrame.NoFrame)
        self.health_scroll.setFixedHeight(0)      # 初始不占位，有源状态后再展开
        try:
            self.health_scroll.viewport().setAutoFillBackground(False)
        except Exception:  # noqa: BLE001
            pass
        self.health_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # v3.18.1：容器/视口透明，避免出现一条未上主题的灰白横条
        self.health_scroll.setStyleSheet(
            "QScrollArea#newsHealth, QScrollArea#newsHealth > QWidget > QWidget"
            " { background: none; border: none; }")
        try:
            self.health_scroll.viewport().setStyleSheet("background: none;")
        except Exception:  # noqa: BLE001
            pass
        self.health_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.health_host = QWidget()
        self.health_row = QHBoxLayout(self.health_host)
        self.health_row.setContentsMargins(0, 0, 0, 0)
        self.health_row.setSpacing(SPACE.xs)
        self.health_scroll.setWidget(self.health_host)
        self.body.addWidget(self.health_scroll)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(2)
        split.setStyleSheet("QSplitter::handle { background: none; }")

        # 左栏：日期 / 过滤 / 来源
        self.left = kit.ListView()
        self.left.itemClicked.connect(self._on_left_clicked)
        self.left.setMaximumWidth(220)
        split.addWidget(self.left)

        # 中栏：搜索 + 分类分组列表
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(SPACE.xs_plus)
        self.search_edit = kit.search_box("搜索标题 / 摘要 / 来源 / 理由…",
                                         on_change=lambda _t: self._fill_items())
        mv.addWidget(self.search_edit)
        self.list = kit.ListView()
        self.list.itemClicked.connect(self._on_item_clicked)
        mv.addWidget(self.list, 1)
        split.addWidget(mid)

        # 右栏：详情
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(SPACE.sm_plus, 0, 0, 0)
        rv.setSpacing(SPACE.xs_plus)
        self.lbl_title = QLabel("—")
        ft = QFont(self._cjk)
        ft.setPixelSize(FONT.body + 2)
        ft.setBold(True)
        self.lbl_title.setFont(ft)
        self.lbl_title.setWordWrap(True)
        rv.addWidget(self.lbl_title)
        self.lbl_meta = QLabel("")
        fm = QFont(self._cjk)
        fm.setPixelSize(FONT.micro)
        self.lbl_meta.setFont(fm)
        self.lbl_meta.setStyleSheet("color: %s;" % self._hint_hex)
        self.lbl_meta.setWordWrap(True)
        rv.addWidget(self.lbl_meta)
        self.detail = QTextBrowser()
        self.detail.setObjectName("pkDetail")
        self.detail.setOpenExternalLinks(False)
        rv.addWidget(self.detail, 1)
        acts = QHBoxLayout()
        acts.setSpacing(SPACE.xs_plus)
        self.btn_open = kit.ghost_button("打开原文", on_click=self._open_url)
        self.btn_star = kit.ghost_button("收藏", on_click=self._toggle_star)
        self.btn_unread = kit.ghost_button("标记未读", on_click=self._mark_unread)
        acts.addWidget(self.btn_open)
        acts.addWidget(self.btn_star)
        acts.addWidget(self.btn_unread)
        acts.addStretch(1)
        rv.addLayout(acts)
        split.addWidget(right)

        split.setSizes([200, 390, 410])
        self.body.addWidget(split, 1)

        self.lbl_status = QLabel("")
        fs = QFont(self._cjk)
        fs.setPixelSize(FONT.micro)
        self.lbl_status.setFont(fs)
        self.lbl_status.setStyleSheet("color: %s;" % self._hint_hex)
        self.footer.insertWidget(0, self.lbl_status)

    # ── 数据 ────────────────────────────────────
    def refresh(self, date=None):
        """加载某期（默认最新）日报并重建三栏"""
        report = nf.load_archive(date) if date else nf.load_latest()
        if isinstance(report, dict):
            nf.apply_state(report)
        self._report = report if isinstance(report, dict) else None
        self._date = (self._report or {}).get("date") or date or ""
        self._current = None
        self._fill_health()
        _health = (self._report or {}).get("source_health") or []
        self.health_scroll.setVisible(bool(_health))
        self._fill_left()
        self._fill_items()
        self._show_placeholder()

    def _fill_health(self):
        """源健康条：正常 / 降级 / 失败 + 单源重试"""
        self._clear_layout(self.health_row)
        try:
            self.health_host.setMinimumWidth(0)
        except Exception:  # noqa: BLE001
            pass
        label = QLabel("源健康")
        lf = QFont(self._cjk)
        lf.setPixelSize(FONT.micro)
        lf.setBold(True)
        label.setFont(lf)
        label.setStyleSheet("color: %s;" % self._accent_hex)
        self.health_row.addWidget(label)
        sources = (self._report or {}).get("sources") or []
        if not sources:
            # v3.18.1：没有源状态就把高度归零（隐藏仍占位会留一条白带）
            self.health_scroll.setVisible(False)
            self.health_scroll.setFixedHeight(0)
            _box = self.health_row.parentWidget()
            if _box is not None:
                _box.setVisible(False)
            hint = QLabel("暂无源状态（生成后显示）")
            hf = QFont(self._cjk)
            hf.setPixelSize(FONT.micro)
            hint.setFont(hf)
            hint.setStyleSheet("color: %s;" % self._hint_hex)
            self.health_row.addWidget(hint)
            self.health_row.addStretch(1)
            return
        self.health_scroll.setVisible(True)
        self.health_scroll.setFixedHeight(42)
        try:
            self.health_scroll.viewport().setAutoFillBackground(False)
        except Exception:  # noqa: BLE001
            pass
        _box = self.health_row.parentWidget()
        if _box is not None:
            _box.setVisible(True)
            _box.setStyleSheet("background: none; border: none;")
        try:
            self.health_scroll.widget().setStyleSheet("background: none;")
        except Exception:  # noqa: BLE001
            pass
        for src in sources:
            status = src.get("status") or ("ok" if src.get("ok") else "failed")
            color = {"ok": self._ok_hex, "degraded": self._warning_hex,
                     "failed": self._warn_hex}.get(status, self._hint_hex)
            count = int(src.get("count") or 0)
            text = "● %s %s" % (src.get("name") or src.get("id") or "?",
                               count if status != "failed" else STATUS_LABEL["failed"])
            chip = QLabel(text)
            cf = QFont(self._cjk)
            cf.setPixelSize(FONT.micro)
            chip.setFont(cf)
            chip.setStyleSheet("color: %s;" % color)
            tip = ["信任 %.2f" % float(src.get("trust") or 0.6)]
            if src.get("error"):
                tip.append(str(src["error"]))
            if src.get("attempts"):
                tip.append("尝试 %s 次" % src["attempts"])
            chip.setToolTip(" · ".join(tip))
            self.health_row.addWidget(chip)
            if status != "ok":
                btn = kit.ghost_button(
                    "重试",
                    on_click=lambda _checked=False, sid=src.get("id"): self.retry_source_requested.emit(sid))
                btn.setFixedHeight(26)
                btn.setToolTip("重新抓取 %s（并回当日日报，不重跑 AI）" % (src.get("name") or ""))
                self.health_row.addWidget(btn)
        self.health_row.addStretch(1)
        try:
            # 15 个源横向排列时允许横向滚动，不挤压三栏
            self.health_host.setMinimumWidth(self.health_row.sizeHint().width())
        except Exception:  # noqa: BLE001
            pass

    def _fill_left(self):
        self.left.clear()
        self._add_static(self.left, self._section("日期"))
        archives = nf.list_archives() or []
        if self._report and self._date and all(d != self._date for d, _c in archives):
            archives = [(self._date, len(self._report.get("items") or []))] + archives
        if not archives:
            self._add_static(self.left, self._plain("（暂无历史）"))
        for d, n in archives[:14]:
            label = "%s%s" % (d, "  ● 当前" if d == self._date else "")
            it, w = kit.item_for(kit.list_row(label, str(n)), data=("date", d))
            self.left.addItem(it)
            self.left.setItemWidget(it, w)

        self._add_static(self.left, self._section("过滤"))
        unread = int((self._report or {}).get("unread") or 0)
        starred = sum(1 for it in ((self._report or {}).get("items") or []) if it.get("starred"))
        for key, label, count in (("all", "全部", len((self._report or {}).get("items") or [])),
                                  ("unread", "未读", unread),
                                  ("starred", "收藏", starred)):
            it, w = kit.item_for(kit.list_row(("● " if key == self._filter else "   ") + label, str(count)),
                                 data=("filter", key))
            self.left.addItem(it)
            self.left.setItemWidget(it, w)

        self._add_static(self.left, self._section("来源"))
        counts = {}
        for it in ((self._report or {}).get("items") or []):
            src = it.get("source") or "其它"
            counts[src] = counts.get(src, 0) + 1
        it, w = kit.item_for(kit.list_row(("● " if not self._source else "   ") + "全部", str(sum(counts.values()))),
                             data=("source", ""))
        self.left.addItem(it)
        self.left.setItemWidget(it, w)
        for src, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            it, w = kit.item_for(kit.list_row(("● " if src == self._source else "   ") + src, str(n)),
                                 data=("source", src))
            self.left.addItem(it)
            self.left.setItemWidget(it, w)

    def _visible_items(self):
        items = ((self._report or {}).get("items") or [])
        kw = self.search_edit.text().strip().lower()
        out = []
        for it in items:
            if self._filter == "unread" and it.get("read"):
                continue
            if self._filter == "starred" and not it.get("starred"):
                continue
            if self._source and (it.get("source") or "其它") != self._source:
                continue
            if kw:
                blob = ("%s %s %s %s" % (it.get("title") or "", it.get("summary") or "",
                                         it.get("source") or "", it.get("why") or "")).lower()
                if kw not in blob:
                    continue
            out.append(it)
        return out

    def _fill_items(self):
        self.list.clear()
        items = self._visible_items()
        groups = {}
        order = []
        for it in items:
            cat = it.get("category") or "other"
            if cat not in groups:
                groups[cat] = []
                order.append(cat)
            groups[cat].append(it)
        for cat in order:
            rows = groups[cat]
            self._add_static(self.list, self._cat_row(CAT_LABEL.get(cat, cat), len(rows)))
            for row in rows:
                badge, bcolor = "", None
                if row.get("starred"):
                    badge, bcolor = "★", self._warning_hex
                title = row.get("title") or "（无标题）"
                if len(title) > 30:
                    title = title[:29].rstrip("，。；、,. ") + "…"
                it2, w2 = kit.item_for(
                    kit.list_row(title, self._row_meta(row), badge, bcolor, compact=False),
                    data=("item", row))
                self.list.addItem(it2)
                self.list.setItemWidget(it2, w2)
                # v3.18.1：行高必须跟 widget 一致，否则 QListWidget 按默认高度排布导致文字重叠
                it2.setSizeHint(QSize(0, max(34, w2.sizeHint().height())))
        total = len((self._report or {}).get("items") or [])
        unread = int((self._report or {}).get("unread") or 0)
        self.set_subtitle("%s · 共 %d 条 · 未读 %d" % (self._date or "无数据", total, unread))
        if not items:
            self._add_static(self.list, self._plain("（当前过滤下没有条目）"))

    def _row_meta(self, row):
        """列表第二行：来源 · 分数（why/因子只在详情，避免行过高）"""
        parts = []
        if row.get("source"):
            parts.append(str(row["source"]))
        if row.get("score"):
            parts.append("%s 分" % row["score"])
        if not row.get("read"):
            parts.append("未读")
        return " · ".join(parts)

    def _show_placeholder(self):
        self.lbl_title.setText("—")
        self.lbl_meta.setText("")
        self.btn_star.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.btn_unread.setEnabled(False)
        if self._report is None:
            self.detail.setPlainText(states.empty("AI 日报", "点底部「生成日报」抓取今日内容"))
        else:
            self.detail.setPlainText(states.empty("日报条目", "从中间列表点选一条查看摘要、评分理由与原文链接"))

    # ── 交互 ────────────────────────────────────
    def _on_left_clicked(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        kind, payload = data
        if kind == "date" and payload != self._date:
            self.refresh(payload)
            return
        if kind == "filter":
            self._filter = payload
        elif kind == "source":
            self._source = payload
        self._fill_left()
        self._fill_items()

    def _on_item_clicked(self, item):
        data = item.data(Qt.UserRole)
        if not data or data[0] != "item":
            return
        self._show_item(data[1])

    def _show_item(self, row):
        self._current = row
        self.lbl_title.setText(row.get("title") or "（无标题）")
        meta = " · ".join(x for x in (row.get("source") or "",
                                      CAT_LABEL.get(row.get("category") or "", ""),
                                      row.get("time") or "",
                                      ("%s 分" % row["score"]) if row.get("score") else "") if x)
        self.lbl_meta.setText(meta)
        parts = []
        if row.get("why"):
            parts.append("【为什么】\n%s" % row["why"])
        if row.get("summary"):
            parts.append("【摘要】\n%s" % row["summary"])
        if row.get("ai_summary"):
            parts.append("【AI 摘要】\n%s" % row["ai_summary"])
        if row.get("desc"):
            parts.append(str(row["desc"]))
        factors = row.get("factors") or {}
        if factors:
            parts.append("【评分】综合 %s 分\n%s" % (
                row.get("score") or 0, self._factor_text(factors)))
        related = row.get("related") or []
        if related:
            lines = ["- [%s] %s" % (r.get("source") or "来源", r.get("title") or "链接")
                     for r in related[:4]]
            parts.append("【相关来源】\n%s" % "\n".join(lines))
        if row.get("degraded"):
            parts.append("（该条 AI 输出不完整，已逐条降级：保留原文 / 抽取式摘要）")
        if row.get("translated") is False:
            parts.append("（该条未完成翻译，保留原文标题/摘要）")
        if not parts:
            parts.append("（该条无摘要，点「打开原文」阅读全文）")
        parts.append("\n原文：%s" % (row.get("url") or ""))
        self.detail.setPlainText("\n\n".join(parts))
        self.btn_star.setText("取消收藏" if row.get("starred") else "收藏")
        for b in (self.btn_star, self.btn_open, self.btn_unread):
            b.setEnabled(True)
        # 点开即已读
        if not row.get("read"):
            row["read"] = True
            try:
                nf.mark_read(row.get("id") or nf.item_id(row.get("url", ""), row.get("title", "")))
            except Exception:  # noqa: BLE001
                pass
            self._after_state_change()

    @staticmethod
    def _factor_text(factors):
        """因子条文本（详情页展示完整五项）"""
        rows = (("信任", "trust", 25), ("新鲜", "freshness", 20), ("兴趣", "interest", 20),
                ("重要性", "importance", 25), ("多样性", "diversity", 10))
        return " · ".join("%s %s/%d" % (label, factors.get(key) or 0, top)
                          for label, key, top in rows)

    def _after_state_change(self):
        """状态变化后重算未读并刷新界面（左栏计数 + 中栏角标 + 浮球红点）"""
        if isinstance(self._report, dict):
            nf.apply_state(self._report)
        self._fill_left()
        self._fill_items()
        self.state_changed.emit()

    def _toggle_star(self):
        if not self._current:
            return
        iid = self._current.get("id") or nf.item_id(self._current.get("url", ""),
                                                   self._current.get("title", ""))
        try:
            _st, starred = nf.toggle_star(iid)
        except Exception:  # noqa: BLE001
            return
        self._current["starred"] = starred
        self.btn_star.setText("取消收藏" if starred else "收藏")
        self._flash("已收藏 ✓" if starred else "已取消收藏")
        self._after_state_change()
        self._show_item(self._current)

    def _mark_unread(self):
        if not self._current:
            return
        iid = self._current.get("id") or nf.item_id(self._current.get("url", ""),
                                                   self._current.get("title", ""))
        try:
            nf.mark_read(iid, False)
        except Exception:  # noqa: BLE001
            return
        self._current["read"] = False
        self._flash("已标记未读")
        self._after_state_change()

    def _open_url(self):
        url = (self._current or {}).get("url") or ""
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _export(self):
        """导出 Markdown"""
        try:
            res = nf.export_markdown(self._date or None)
            path, err = res if isinstance(res, tuple) else (res, "")
            if path:
                self._flash("已导出：%s" % os.path.basename(path))
            else:
                self._flash("导出失败：%s" % (err or "未知错误"))
        except Exception as e:  # noqa: BLE001
            self._flash("导出失败：%s" % e)

    def _flash(self, text):
        """v3.14.0：统一走 PanelShell.flash（150ms 淡出）"""
        self.flash(text, label=self.lbl_status)

    # ── 生成流程（由浮球驱动）─────────────────────
    def set_generating(self, flag):
        self.btn_generate.setEnabled(not flag)
        self.btn_cancel.setVisible(bool(flag))
        self.btn_cancel.setEnabled(bool(flag))
        if flag:
            self.lbl_status.setText("正在生成…")
            self.set_subtitle("生成中…")

    def set_progress(self, info):
        info = info or {}
        label = info.get("label") or ""
        done, total = int(info.get("done") or 0), int(info.get("total") or 0)
        text = "%s %s" % (label, ("(%d/%d)" % (done, total)) if total else "")
        self.lbl_status.setText(text)
        if self.btn_cancel.isVisible():
            self.set_subtitle("生成中 · %s" % (label or "处理中"))

    def set_error(self, message):
        """生成失败 / 取消：恢复按钮并在详情区给出可操作提示"""
        self.set_generating(False)
        self.set_subtitle("")
        self.lbl_status.setText(str(message or "生成失败"))
        self.detail.setPlainText(states.empty("生成失败", str(message or "未知错误")))
        self._flash("生成失败：%s" % (message or "未知错误"))

    def on_generated(self, payload):
        self.set_generating(False)
        self._flash("已生成：%s（%d 条）" % (payload.get("date", ""), payload.get("count", 0)))
        self.refresh()

    def on_source_retried(self, result):
        """单源重试回调：刷新源健康与列表"""
        self.set_subtitle("")
        if not result.get("ok"):
            self.refresh()
            self._flash("重试失败：%s" % (result.get("error") or "未知错误"))
            return
        self._flash("已补抓 %d 条（重复 %d%s）" % (
            int(result.get("added") or 0), int(result.get("duplicates") or 0),
            "，配额跳过 %d" % int(result["quota_skipped"])
            if result.get("quota_skipped") else ""))
        self.refresh()

    def _cat_row(self, text, count):
        """分类小标题（粗体强调色 + 右侧计数）"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 4, 2, 2)
        lab = QLabel(text)
        f = QFont(self._cjk)
        f.setPixelSize(FONT.body)
        f.setBold(True)
        lab.setFont(f)
        lab.setStyleSheet("color: %s;" % self._accent_hex)
        h.addWidget(lab, 1)
        cnt = QLabel(str(count))
        f2 = QFont(self._cjk)
        f2.setPixelSize(FONT.micro)
        cnt.setFont(f2)
        cnt.setStyleSheet("color: %s;" % self._hint_hex)
        h.addWidget(cnt, 0)
        return kit.item_for(w, data=None)

    # ── 小工具 ──────────────────────────────────
    def _section(self, text):
        """分组小标题（返回 item+widget，调用方负责 setItemWidget）"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 4, 2, 2)
        lab = QLabel(text)
        f = QFont(self._cjk)
        f.setPixelSize(FONT.micro)
        f.setBold(True)
        lab.setFont(f)
        lab.setStyleSheet("color: %s;" % self._accent_hex)
        h.addWidget(lab, 1)
        return kit.item_for(w, data=None)

    def _plain(self, text):
        return kit.item_for(kit.list_row(text, "", "", None), data=None)

    def _add_static(self, view, pair):
        """把 (item, widget) 这种只读行加进列表（禁用选中）"""
        it, w = pair
        it.setFlags(Qt.ItemIsEnabled)
        view.addItem(it)
        view.setItemWidget(it, w)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
