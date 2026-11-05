# -*- coding: utf-8 -*-
"""D 线 L0 雷达条 + L1 快面板（贴浮球，不抢焦点，稳定不抖）。"""
from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import (Qt, QTimer, QFileSystemWatcher, QSettings,
                          QPropertyAnimation, QEasingCurve, QRectF,
                          pyqtProperty, pyqtSignal)
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect,
                             QHBoxLayout, QLabel, QMenu, QPushButton,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from agentfloat.core.theme import FONT_FAMILY, get_colors
from agentfloat.core.window_focus import focus_window
from agentfloat.ui.tokens import FONT, RADIUS
from agentfloat.services.progress import store
from agentfloat.ui.progress_cockpit import open_cockpit

WIDTH = 260
SHADOW_PAD = 20          # 外窗口给投影留的空白（面板本体仍占 WIDTH）
PANEL_RADIUS = 12
ROW_H = 60
ROW_H_COMPACT = 32
SEGMENTS = 6
STATUS_RANK = {"need_input": 0, "failed": 1, "running": 2}
STATUS_DOT = {"need_input": "!", "failed": "×", "running": "●"}
STEP_ICON = {"done": "✓", "running": "▶", "failed": "×", "pending": "○"}


def status_color(status, theme="dark"):
    """状态色：需要输入琥珀 / 失败红 / 运行灰 / 完成绿。"""
    status = str(status or "running")
    if theme == "light":
        table = {
            "need_input": QColor(255, 149, 0),
            "failed": QColor(255, 59, 48),
            "running": QColor(142, 142, 147),
            "done": QColor(52, 199, 89),
        }
    else:
        table = {
            "need_input": QColor(255, 159, 10),
            "failed": QColor(255, 69, 58),
            "running": QColor(142, 142, 150),
            "done": QColor(48, 209, 88),
        }
    return table.get(status, table["running"])


def seg_color(status, theme="dark"):
    """分段进度填充色：阻塞/失败跟随状态，其余用品牌蓝。"""
    status = str(status or "running")
    if status in ("need_input", "failed"):
        return status_color(status, theme)
    accent = get_colors(theme)["ACCENT"]
    return QColor(accent[0], accent[1], accent[2])


def row_meta(data):
    """行内次要信息：需要确认 / 失败原因 / 当前步骤。"""
    status = str(data.get("status") or "")
    if status == "need_input":
        return "需要确认：%s" % (data.get("question") or "等待确认")
    if status == "failed":
        return "失败：%s" % (data.get("error") or "已失败")
    cur = current_step(data)
    eta = (data.get("eta") or {}).get("etaText") or ""
    if cur and cur.get("title"):
        text = "正在做：%s" % cur.get("title")
    else:
        text = "准备中"
    if eta and eta != "待估":
        text += " · %s" % eta
    return text


def row_right(data):
    """右侧固定显示 done/total；ETA 归到 meta 行，避免同一列两种含义。"""
    done, total = step_counts(data)
    return "%d/%d" % (done, total)


class SegBar(QWidget):
    """6 段圆角进度块（替代 ▰▱ 字符，11px 下不再糊成一排）。"""

    def __init__(self, status="running", theme="dark", parent=None):
        super().__init__(parent)
        self._status = str(status or "running")
        self._theme = theme if theme in ("dark", "light") else "dark"
        self._done = 0
        self._total = 0
        self.setFixedHeight(3)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_status(self, status):
        self._status = str(status or "running")
        self.update()

    def set_progress(self, done, total):
        self._done = max(0, int(done or 0))
        self._total = max(0, int(total or 0))
        self.update()

    def fill_count(self):
        if self._total <= 0:
            return 0
        filled = int(round(SEGMENTS * min(self._done, self._total) / float(self._total)))
        return max(0, min(SEGMENTS, filled))

    def _track_color(self):
        return QColor(255, 255, 255, 26) if self._theme == "dark" else QColor(0, 0, 0, 20)

    def paintEvent(self, _event):
        width = float(self.width())
        if width <= 0:
            return
        gap = 2.0
        seg_w = max(0.0, (width - gap * (SEGMENTS - 1)) / float(SEGMENTS))
        filled = self.fill_count()
        fill = seg_color(self._status, self._theme)
        track = self._track_color()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        for i in range(SEGMENTS):
            rect = QRectF(i * (seg_w + gap), 0, seg_w, float(self.height()))
            path = QPainterPath()
            path.addRoundedRect(rect, 2.0, 2.0)
            painter.fillPath(path, fill if i < filled else track)
        painter.end()


class _StatusDot(QWidget):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(7, 7)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())
        painter.end()


class _ElideLabel(QLabel):
    """单行省略：保留全文，按当前宽度用 QFontMetrics 省略。"""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setText(text)

    def setText(self, text):
        self._full = str(text or "")
        self._apply_elide()

    def full_text(self):
        return self._full

    def _apply_elide(self):
        if not self._full:
            super().setText("")
            return
        fm = self.fontMetrics()
        width = max(0, self.width())
        super().setText(fm.elidedText(self._full, Qt.ElideRight, width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()


class TaskRow(QWidget):
    """dot + 标题 + 次要信息 + 分段进度 + 右侧计数；整行可点。"""

    def __init__(self, data, theme="dark", expanded=False, compact=False,
                 on_toggle=None, parent=None):
        super().__init__(parent)
        self._sid = str(data.get("sessionId") or "")
        self._on_toggle = on_toggle
        status = str(data.get("status") or "")
        self.setObjectName("radarRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(ROW_H_COMPACT if compact else ROW_H)
        hover = ("rgba(255,255,255,0.06)" if theme == "dark"
                 else "rgba(0,0,0,0.04)")
        selected = "rgba(10,132,255,0.13)"
        base = selected if expanded else "transparent"
        sheet = ("#radarRow { background: %s; border-radius: 8px; }" % base)
        if not expanded:
            sheet += "#radarRow:hover { background: %s; }" % hover
        self.setStyleSheet(sheet)

        lay = QHBoxLayout(self)
        top = 6 if compact else 8
        lay.setContentsMargins(6, top, 6, top)
        lay.setSpacing(9)

        dot_wrap = QWidget()
        dot_lay = QVBoxLayout(dot_wrap)
        dot_lay.setContentsMargins(0, 0 if compact else 5, 0, 0)
        dot_lay.setSpacing(0)
        dot = _StatusDot(status_color(status, theme))
        dot_lay.addWidget(dot, 0, Qt.AlignHCenter)
        dot_lay.addStretch(1)
        dot_wrap.setFixedWidth(7)
        lay.addWidget(dot_wrap, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(1)
        name = _ElideLabel(display_name(data))
        name_font = QFont(FONT_FAMILY)
        name_font.setPixelSize(12)
        name_font.setWeight(QFont.DemiBold)
        name.setFont(name_font)
        name.setStyleSheet("color: rgb(%d,%d,%d);" % get_colors(theme)["TEXT"])
        body.addWidget(name)
        if not compact:
            meta = _ElideLabel(row_meta(data))
            meta_font = QFont(FONT_FAMILY)
            meta_font.setPixelSize(10)
            meta.setFont(meta_font)
            meta.setStyleSheet("color: rgb(%d,%d,%d);" % get_colors(theme)["HINT"])
            body.addWidget(meta)
            body.addSpacing(7)
            done, total = step_counts(data)
            seg = SegBar(status, theme)
            seg.set_progress(done, total)
            body.addWidget(seg)
        lay.addLayout(body, 1)

        right = QLabel(row_right(data))
        right_font = QFont(FONT_FAMILY)
        right_font.setPixelSize(10)
        right.setFont(right_font)
        right.setStyleSheet("color: rgb(%d,%d,%d);" % get_colors(theme)["HINT"])
        right.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(right, 0, Qt.AlignTop)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            if self._on_toggle:
                self._on_toggle(self._sid)
            return
        super().mouseReleaseEvent(event)

    def seg_bar(self):
        return self.findChild(SegBar)


def _dt(text):
    try:
        return datetime.fromisoformat(str(text or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def is_stale(data, now=None):
    """旧会话不再占用雷达：运行中 10 分钟无更新、阻塞/失败超过 4 小时。"""
    status = str(data.get("status") or "")
    stamp = _dt(data.get("updatedAt")) or _dt(data.get("createdAt"))
    if not stamp:
        return False
    now = now or datetime.now().astimezone()
    try:
        age = (now - stamp).total_seconds()
    except TypeError:
        return False
    limit = 600 if status == "running" else 4 * 3600
    return age > limit


def qualifies(data, now=None):
    """是否值得出现在 L0：需要输入/失败，或运行中且 ≥3 步 / 超 2 分钟。"""
    if is_stale(data, now):
        return False
    status = str(data.get("status") or "")
    if status in ("need_input", "failed"):
        return True
    if status != "running":
        return False
    # 运行中任务至少持续 2 分钟才浮现；避免一启动就整块挡在屏幕上
    created = _dt(data.get("createdAt"))
    if not created:
        return False
    now = now or datetime.now().astimezone()
    try:
        return (now - created).total_seconds() >= 120
    except TypeError:
        return False


def sort_key(data):
    return (STATUS_RANK.get(str(data.get("status")), 9), data.get("updatedAt") or "")


def display_name(data):
    return str(data.get("title") or data.get("project") or data.get("sessionId") or "任务")


def step_counts(data):
    steps = data.get("steps") or []
    done = sum(1 for s in steps if s.get("status") == "done")
    return done, len(steps)


def current_step(data):
    sid = str(data.get("currentStepId") or "")
    for step in data.get("steps") or []:
        if step.get("id") == sid:
            return step
    return next((s for s in data.get("steps") or [] if s.get("status") == "running"), None)


def segment_text(done, total, width=8):
    """用方块字符画分段进度，避免再加一条细线。"""
    total = max(1, int(total or 0))
    width = max(4, int(width or 8))
    filled = int(round(width * max(0, min(done, total)) / float(total)))
    return "▰" * filled + "▱" * (width - filled)


def row_text(data):
    done, total = step_counts(data)
    cur = current_step(data) or {}
    status = str(data.get("status") or "")
    eta = (data.get("eta") or {}).get("etaText") or "待估"
    if cur.get("title"):
        step_title = cur.get("title")
    elif status == "need_input":
        step_title = "等待确认"
    elif status == "failed":
        step_title = "已失败"
    else:
        step_title = "准备中"
    if status in ("need_input", "failed"):
        eta = "—"
    head = "%s %s" % (STATUS_DOT.get(status, "●"), display_name(data))
    detail = "%d/%d · %s · %s" % (done, total, step_title, eta)
    return head, detail


def content_signature(sessions, expanded=""):
    """只按内容签名重绘，避免定时器每次都重建控件。"""
    parts = [str(expanded or "")]
    for data in sessions:
        parts.append("|".join([
            str(data.get("sessionId") or ""),
            str(data.get("status") or ""),
            str(data.get("updatedAt") or ""),
            str(data.get("currentStepId") or ""),
            "%d/%d" % step_counts(data),
            str(data.get("question") or ""),
            str(data.get("error") or ""),
        ]))
    return "||".join(parts)


class RadarTab(QWidget):
    """横排 ••• + 数量，hover 16→20；窗口留白给投影。"""

    clicked = pyqtSignal()
    PAD = 8

    def __init__(self, anchor, theme="dark"):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._anchor = anchor
        self._theme = theme if theme in ("dark", "light") else "dark"
        self._count = 0
        self._status = "running"

        self._body = QPushButton(self)
        self._body.setCursor(Qt.PointingHandCursor)
        self._body.clicked.connect(self.clicked.emit)
        self._body.setGeometry(self.PAD, self.PAD, 16, 44)
        self._shadow = QGraphicsDropShadowEffect(self._body)
        self._shadow.setBlurRadius(16)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(QColor(0, 0, 0, 110))
        self._body.setGraphicsEffect(self._shadow)

        self._anim = QPropertyAnimation(self, b"tabWidth", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._apply_style()
        self._set_tab_width(16)

    def _get_tab_width(self):
        return self._body.width()

    def _set_tab_width(self, width):
        width = max(16, min(24, int(width)))
        self._body.setFixedSize(width, 44)
        self.setFixedSize(width + 2 * self.PAD, 44 + 2 * self.PAD)

    tabWidth = pyqtProperty(int, _get_tab_width, _set_tab_width)

    def _animate_width(self, width):
        self._anim.stop()
        self._anim.setStartValue(self._body.width())
        self._anim.setEndValue(int(width))
        self._anim.start()

    def enterEvent(self, event):
        self._animate_width(20)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_width(16)
        super().leaveEvent(event)

    def _apply_style(self):
        if self._theme == "dark":
            top, bottom = "#50505A", "#2D2D34"
            border, text = "rgba(255,255,255,46)", "#E8E8EE"
            hover = "#5E5E69"
        else:
            top, bottom = "#EDEDF1", "#D6D6DC"
            border, text = "rgba(0,0,0,32)", "#3A3A3C"
            hover = "#F2F2F6"
        color = status_color(self._status, self._theme)
        self._body.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 %s, stop:1 %s);"
            " border: 1px solid %s;"
            " border-top: 2px solid rgb(%d,%d,%d); border-radius: %dpx;"
            " color: %s; font-family: '%s'; font-size: %dpx; font-weight: 700;"
            " padding: 0; }"
            "QPushButton:hover { background: %s; }"
            % (top, bottom, border, color.red(), color.green(), color.blue(),
               RADIUS.sm, text, FONT_FAMILY, FONT.micro, hover))

    def text(self):
        return self._body.text()

    def set_count(self, n):
        self._count = int(n or 0)
        self._body.setText("•••\n%d" % self._count)
        self._body.setToolTip("%d 个后台任务" % self._count)

    def set_status(self, status):
        status = str(status or "running")
        if status == self._status:
            return
        self._status = status
        self._apply_style()

    def place(self):
        if not self._anchor:
            return
        screen = QApplication.screenAt(self._anchor.frameGeometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        if self._anchor.isVisible():
            geo = self._anchor.frameGeometry()
            # 始终朝屏幕内侧：右半边放左侧，左半边放右侧
            if geo.center().x() > area.center().x():
                x = geo.left() - self.width() + self.PAD - 6
            else:
                x = geo.right() + 6 - self.PAD
            y = geo.center().y() - self.height() // 2
        else:
            x = area.right() - self.width() - 10
            y = area.center().y() - self.height() // 2
        x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
        y = max(area.top(), min(y, area.bottom() - self.height()))
        self.move(x, y)


class ProgressRadar(QWidget):
    def __init__(self, anchor, theme="dark", parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(WIDTH + 2 * SHADOW_PAD)
        self._anchor = anchor
        self._theme = theme if theme in ("dark", "light") else "dark"
        self._colors = get_colors(self._theme)
        self._expanded = ""
        self._last_sig = ""
        self._settings = QSettings("AgentFloat", "ProgressRadar")
        self._dismiss_sig = str(self._settings.value("dismissed", "") or "")
        self._panel_open = False
        self._compact = False
        self._tab = RadarTab(anchor, self._theme)
        self._tab.clicked.connect(self._expand)
        self._last_pos = None

        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        # 裁切容器：高度动画时面板保持最终尺寸，由容器从下往上「揭开」，
        # 行不会被压扁，布局最小高度也不会把窗口瞬间撑大。
        self._clip = QWidget(self)
        self._clip.setAttribute(Qt.WA_TranslucentBackground)
        self._box.addWidget(self._clip)
        self._panel = QFrame(self._clip)
        self._panel.setObjectName("radarPanel")
        self._panel.setFixedWidth(WIDTH)
        self._panel.move(SHADOW_PAD, SHADOW_PAD)
        # WA_TranslucentBackground 下 QFrame 默认不画样式表背景，必须显式开启
        self._panel.setAttribute(Qt.WA_StyledBackground, True)
        self._panel.setStyleSheet(self._style())
        self._shadow = QGraphicsDropShadowEffect(self._panel)
        self._shadow.setBlurRadius(40)
        self._shadow.setOffset(0, 12)
        self._shadow.setColor(QColor(0, 0, 0, 115))
        self._panel.setGraphicsEffect(self._shadow)
        self._body = QVBoxLayout(self._panel)
        self._body.setContentsMargins(10, 10, 10, 8)
        self._body.setSpacing(2)

        self._watcher = QFileSystemWatcher(self)
        try:
            self._watcher.addPath(store.progress_dir())
        except Exception:  # noqa: BLE001
            pass
        self._watcher.directoryChanged.connect(self._tick)
        self._watcher.fileChanged.connect(self._tick)

        self._timer = QTimer(self)
        self._timer.setInterval(1200)
        self._timer.timeout.connect(self._tick)
        self._place_timer = QTimer(self)
        self._place_timer.setInterval(500)
        self._place_timer.timeout.connect(self._place)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(10000)
        self._hide_timer.timeout.connect(self._auto_hide)
        self.hide()

    # ── 生命周期 ──────────────────────────────────
    def start(self):
        self._timer.start()
        self._place_timer.start()
        self._tick()

    def _auto_hide(self):
        self._expanded = ""
        self._last_sig = ""
        self._panel_open = False
        self._tab.hide()
        self._fade(0.0, 140)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(150, self._after_auto_hide)

    def _after_auto_hide(self):
        self.hide()
        self.setWindowOpacity(1.0)

    def _dismiss(self):
        """手动关闭：有新的任务内容时再出现。"""
        self._expanded = ""
        sessions = [s for s in store.list_sessions() if qualifies(s)]
        sessions.sort(key=sort_key)
        sig = content_signature(sessions, "")
        self._dismiss_sig = sig
        self._last_sig = sig
        self._settings.setValue("dismissed", sig)
        self._panel_open = False
        self._tab.hide()
        self.hide()

    def reset_dismissed(self):
        """清除「手动关闭」标记（设置页重新开启进度条时用）。"""
        self._dismiss_sig = ""
        self._last_sig = ""
        self._settings.remove("dismissed")

    def pause(self):
        self._timer.stop()
        self._place_timer.stop()
        self._panel_open = False
        self._tab.hide()
        self.hide()

    def resume(self):
        self._timer.start()
        self._place_timer.start()
        self._tick()
        try:
            if self._tab.isVisible():
                self._tab.raise_()
        except Exception:  # noqa: BLE001
            pass

    def _toggle_compact(self):
        self._compact = not self._compact
        self._last_sig = ""
        self._tick()

    def _open_cockpit(self):
        try:
            from agentfloat.ui.progress_cockpit import open_cockpit
            open_cockpit(theme=self._theme)
        except Exception:  # noqa: BLE001
            pass

    def _expand(self):
        # 用户主动展开：清掉「手动关闭」标记，保证必然重新渲染（否则会弹出空面板）
        if self._dismiss_sig:
            self._dismiss_sig = ""
            self._settings.remove("dismissed")
        self._panel_open = True
        self._tab.hide()
        self._last_sig = ""
        self._tick()
        self.setWindowOpacity(0.0)
        self.show()
        self._place(force=True)
        self._fade(1.0, 180)
        try:
            self.activateWindow()
            self.setFocus()
        except Exception:  # noqa: BLE001
            pass

    def _fade(self, target, ms):
        try:
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(ms)
            anim.setStartValue(self.windowOpacity())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._opacity_anim = anim
            anim.start()
        except Exception:  # noqa: BLE001
            self.setWindowOpacity(target)

    def _minimize(self):
        self._panel_open = False
        self._expanded = ""
        self._fade(0.0, 140)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(150, self._after_minimize)

    def _after_minimize(self):
        self.hide()
        self.setWindowOpacity(1.0)
        self._tab.show()
        self._tab.place()

    def _tick(self):
        try:
            sessions = [s for s in store.list_sessions() if qualifies(s)]
        except Exception:  # noqa: BLE001
            return
        sessions.sort(key=sort_key)
        if not sessions:
            self._last_sig = ""
            self._panel_open = False
            self._tab.hide()
            if self.isVisible() and not self._hide_timer.isActive():
                self._hide_timer.start()
            return
        self._hide_timer.stop()
        self._tab.set_count(len(sessions))
        self._tab.set_status(str(sessions[0].get("status") or "running"))
        if not self._panel_open:
            # 折叠态也要尊重「手动关闭」：内容没变就不再冒出来（否则 Esc 1.2s 后被撤销）
            sig = content_signature(sessions, "")
            if self._dismiss_sig:
                if sig == self._dismiss_sig:
                    self._tab.hide()
                    if self.isVisible():
                        self.hide()
                    return
                self._dismiss_sig = ""
                self._settings.remove("dismissed")
            if not self._tab.isVisible():
                self._tab.show()
            self._tab.place()
            return
        self._tab.hide()
        if self._expanded and not any(s.get("sessionId") == self._expanded for s in sessions):
            self._expanded = ""
        sig = content_signature(sessions, self._expanded)
        if sig == self._last_sig:
            if not self.isVisible():
                self.show()
                self._place(force=True)
            else:
                self._place()
            return
        self._last_sig = sig
        self._rebuild(sessions)
        if not self.isVisible():
            self.show()
            self._place(force=True)
        else:
            self._place()

    def _detail_steps_h(self, steps):
        """明细步骤区高度：按内容取，但封顶 160px，超出交给滚动条。"""
        return min(max(20, len(steps or []) * 16 + 4), 160)

    def _available_height(self):
        try:
            geo = self._anchor.frameGeometry() if self._anchor else None
            screen = QApplication.screenAt(geo.center()) if geo else QApplication.primaryScreen()
            if screen is None:
                return 600
            return max(240, int(screen.availableGeometry().height()) - 40)
        except Exception:  # noqa: BLE001
            return 600

    def _fit(self, sessions, animate=False):
        # 让布局给出真实内容高度：行/明细/滚动区都是固定高度，sizeHint 可靠
        try:
            # 不能量 _panel.sizeHint()：面板被上一次 setFixedHeight 卡住上限，量出来只会越来越小。
            # 直接量内容布局（含 contentsMargins）。
            lay = self._body
            lay.activate()
            hint = lay.sizeHint().height()
        except Exception:  # noqa: BLE001
            hint = 240
        h = max(44, int(hint))
        # 不超出屏幕可用高度（多任务 + 长计划时会出屏）；明细步骤区独立滚动
        limit = max(120, self._available_height() - 2 * SHADOW_PAD)
        h = min(h, limit)
        self._apply_height(h + 2 * SHADOW_PAD, animate=animate)

    def _get_panel_height(self):
        return self.height()

    def _set_panel_height(self, value):
        h = int(value)
        self.setFixedHeight(h)
        if getattr(self, "_clip", None) is not None:
            self._clip.setFixedHeight(h)

    panelHeight = pyqtProperty(int, _get_panel_height, _set_panel_height)

    def _apply_height(self, target, animate=False):
        """高度变化用动画过渡，避免展开/收起时窗口瞬移。"""
        target = int(target)
        inner = max(1, target - 2 * SHADOW_PAD)
        # 面板始终按最终高度排版；裁切容器决定露出多少
        self._panel.setFixedHeight(inner)
        if animate and self.isVisible() and abs(self.height() - target) > 2:
            try:
                anim = QPropertyAnimation(self, b"panelHeight", self)
                anim.setDuration(200)
                anim.setStartValue(self.height())
                anim.setEndValue(target)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                self._height_anim = anim
                anim.start()
                return
            except Exception:  # noqa: BLE001
                pass
        self._clip.setFixedHeight(target)
        self.setFixedHeight(target)

    def _place(self, force=False):
        if not self.isVisible() or not self._anchor:
            return
        try:
            if not self._anchor.isVisible():
                return
            geo = self._anchor.frameGeometry()
            screen = QApplication.screenAt(geo.center()) or QApplication.primaryScreen()
            area = screen.availableGeometry()
            w, h = self.width(), self.height()
            x = geo.right() + 10 - SHADOW_PAD
            if x + w - SHADOW_PAD > area.right():
                x = geo.left() - w - 10 + SHADOW_PAD
            x = max(area.left(), min(x, area.right() - w))
            if self._last_pos and not force:
                # 高度变化时保持顶边不动，否则展开会整窗跳到垂直居中位置
                y = self._last_pos[1]
            else:
                y = geo.center().y() - h // 2
            y = max(area.top(), min(y, area.bottom() - h))
            if force or not self._last_pos or abs(x - self._last_pos[0]) > 1 or abs(y - self._last_pos[1]) > 1:
                self.move(x, y)
                self._last_pos = (x, y)
        except Exception:  # noqa: BLE001
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self._expanded:
                self._expanded = ""
                self._last_sig = ""
                self._tick()
            else:
                self._dismiss()
            return
        super().keyPressEvent(event)

    # ── 渲染 ──────────────────────────────────────
    def _overlay(self, dark_alpha, light_alpha):
        """浅色主题下白色叠加等于隐身：按主题换成黑系低透明度。"""
        if self._theme == "dark":
            return "rgba(255,255,255,%s)" % dark_alpha
        return "rgba(0,0,0,%s)" % light_alpha

    def _style(self):
        c = self._colors
        # 没有 backdrop blur 时，0.97 的底色仍会让亮色页面文字透上来；直接不透明更干净
        bg = "#1B1B1F" if self._theme == "dark" else "#FAFAFC"
        border = "rgba(255,255,255,0.09)" if self._theme == "dark" else "rgba(0,0,0,0.10)"
        text = "rgb(%d,%d,%d)" % c["TEXT"]
        return (
            "#radarPanel { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            "QLabel { color: %s; font-family: '%s'; }"
            % (bg, border, RADIUS.md, text, FONT_FAMILY)
        )

    def _clear(self):
        while self._body.count():
            item = self._body.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _ghost_style(self, font_size="10.5px", radius=RADIUS.sm):
        c = self._colors
        return (
            "QPushButton { border:none; background:transparent; padding:0 7px;"
            " border-radius:%dpx; font-size:%s; color: rgb(%d,%d,%d); }"
            "QPushButton:hover { background:%s; color: rgb(%d,%d,%d); }"
            % (radius, font_size, c["HINT"][0], c["HINT"][1], c["HINT"][2],
               self._overlay("0.06", "0.06"),
               c["TEXT"][0], c["TEXT"][1], c["TEXT"][2]))

    def _rebuild(self, sessions):
        self._clear()
        c = self._colors
        head_row = QHBoxLayout()
        head_row.setContentsMargins(2, 0, 2, 8)
        head = QLabel("后台任务 · %d" % len(sessions))
        head_font = QFont(FONT_FAMILY)
        head_font.setPixelSize(11)
        head_font.setWeight(QFont.DemiBold)
        head.setFont(head_font)
        head.setStyleSheet("color: rgb(%d,%d,%d);" % c["TEXT_SECONDARY"])
        compact_btn = QPushButton("详细" if self._compact else "简略")
        compact_btn.setFixedHeight(20)
        compact_btn.setCursor(Qt.PointingHandCursor)
        compact_btn.setStyleSheet(self._ghost_style())
        compact_btn.clicked.connect(self._toggle_compact)
        mini = QPushButton("—")
        mini.setFixedSize(20, 20)
        mini.setCursor(Qt.PointingHandCursor)
        mini.setToolTip("收回成贴边条")
        mini.setStyleSheet(
            "QPushButton { text-align:center; border:none; background:transparent;"
            " border-radius:%dpx; font-size:12px; color: rgb(%d,%d,%d); padding:0; }"
            "QPushButton:hover { background: %s; }"
            % (RADIUS.sm, c["HINT"][0], c["HINT"][1], c["HINT"][2],
               self._overlay("0.06", "0.06")))
        mini.clicked.connect(self._minimize)
        head_row.addWidget(head)
        head_row.addStretch(1)
        head_row.addWidget(compact_btn)
        head_row.addWidget(mini)
        head_wrap = QWidget()
        head_wrap.setLayout(head_row)
        self._body.addWidget(head_wrap)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background:%s; border:none;" % self._overlay("0.09", "0.10"))
        self._body.addWidget(divider)

        for data in sessions[:4]:
            sid = str(data.get("sessionId") or "")
            row = TaskRow(data, self._theme, sid == self._expanded,
                          self._compact, self._toggle)
            self._body.addWidget(row)
            if sid == self._expanded:
                self._build_l1(data)

        if len(sessions) > 4:
            more = QLabel("还有 %d 个任务…" % (len(sessions) - 4))
            more_font = QFont(FONT_FAMILY)
            more_font.setPixelSize(10)
            more.setFont(more_font)
            more.setStyleSheet("color: rgb(%d,%d,%d); padding-left:4px;" % c["HINT"])
            self._body.addWidget(more)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        cockpit = QPushButton("打开驾驶舱")
        cockpit.setCursor(Qt.PointingHandCursor)
        cockpit.setFixedHeight(24)
        cockpit.setStyleSheet(
            "QPushButton { border:1px solid %s; border-radius:8px; padding:0 10px;"
            " background:transparent; font-size:10.5px; color: rgb(%d,%d,%d); }"
            "QPushButton:hover { background: %s; border-color:%s; }"
            % (self._overlay("0.18", "0.14"),
               c["TEXT"][0], c["TEXT"][1], c["TEXT"][2],
               self._overlay("0.10", "0.06"),
               self._overlay("0.28", "0.22")))
        cockpit.clicked.connect(lambda: self._open_cockpit())
        foot.addWidget(cockpit)
        foot.addStretch(1)
        foot_wrap = QWidget()
        foot_wrap.setLayout(foot)
        self._body.addWidget(foot_wrap)
        if self.isVisible():
            # 可见时等布局刷新后再量真实高度，并用动画过渡（展开/收起不跳）
            QTimer.singleShot(0, lambda s=list(sessions): self._fit(s, animate=True))
        else:
            self._fit(sessions)

    def _build_l1(self, data):
        c = self._colors
        box = QFrame()
        box.setObjectName("radarDetail")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setStyleSheet("#radarDetail { background: %s; border-radius: 8px; }"
                          % self._overlay("0.035", "0.035"))
        lay = QVBoxLayout(box)
        lay.setContentsMargins(9, 7, 9, 7)
        lay.setSpacing(5)
        steps = data.get("steps") or []
        lines = []
        for step in steps:
            icon = STEP_ICON.get(str(step.get("status")), "○")
            lines.append("%s %s" % (icon, step.get("title") or ""))
        if not steps:
            lines.append("没有步骤信息（只显示活跃/停滞）")
        info = QLabel("\n".join(lines))
        info.setWordWrap(True)
        info.setStyleSheet("font-size:11px; color: rgb(%d,%d,%d);" % c["TEXT_SECONDARY"])
        # 步骤多时（如 20 步）不再把面板撑出屏幕：明细区自带滚动
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(self._detail_steps_h(steps))
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 6px; background: transparent; margin: 0; }"
            "QScrollBar::handle:vertical { background: %s; border-radius: 4px; min-height: 18px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
            % self._overlay("0.18", "0.18"))
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host_lay = QVBoxLayout(host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)
        host_lay.addWidget(info)
        host_lay.addStretch(1)
        scroll.setWidget(host)
        lay.addWidget(scroll)
        if data.get("status") == "need_input" and data.get("question"):
            q = QLabel("需要确认：" + str(data.get("question")))
            q.setWordWrap(True)
            q.setStyleSheet("font-size:11px; color: rgb(%d,%d,%d);" % c["WARNING"])
            lay.addWidget(q)
        if data.get("status") == "failed" and data.get("error"):
            err = QLabel("失败：" + str(data.get("error")))
            err.setWordWrap(True)
            err.setStyleSheet("font-size:11px; color: rgb(%d,%d,%d);" % c["WARN_FG"])
            lay.addWidget(err)

        # 动作行：1 主 + 1 次 + 「更多…」；5 个按钮挤在 238px 会被压到 40px 读不全
        row = QHBoxLayout()
        row.setSpacing(6)
        sid = str(data.get("sessionId") or "")
        status = str(data.get("status") or "")
        if status in ("need_input", "failed"):
            again = QPushButton("继续" if status == "need_input" else "重试")
            again.setFixedHeight(24)
            again.setStyleSheet(self._action_style(True))
            again.clicked.connect(lambda _=False: self._resume(data))
            row.addWidget(again)
        elif status == "running":
            stop = QPushButton("中断")
            stop.setFixedHeight(24)
            stop.setStyleSheet(self._action_style(False))
            stop.clicked.connect(lambda _=False: self._cancel(sid))
            row.addWidget(stop)
        cockpit = QPushButton("驾驶舱")
        cockpit.setFixedHeight(24)
        cockpit.setStyleSheet(self._action_style(False))
        cockpit.clicked.connect(lambda _=False: open_cockpit(sid, self._theme))
        row.addWidget(cockpit)
        more = QPushButton("更多…")
        more.setFixedHeight(24)
        more.setStyleSheet(self._action_style(False))
        more.setMenu(self._more_menu(data, more))
        row.addWidget(more)
        row.addStretch(1)
        lay.addLayout(row)
        wrap = QWidget()
        wrap_lay = QHBoxLayout(wrap)
        wrap_lay.setContentsMargins(22, 0, 6, 6)
        wrap_lay.addWidget(box)
        self._body.addWidget(wrap)

    def _more_menu(self, data, parent):
        c = self._colors
        sid = str(data.get("sessionId") or "")
        menu = QMenu(parent)
        menu.setStyleSheet(
            "QMenu { background: %s; border: 1px solid %s; border-radius: 8px;"
            " padding: 4px; color: rgb(%d,%d,%d); }"
            "QMenu::item { padding: 5px 16px; border-radius: 8px; font-size: 11px; }"
            "QMenu::item:selected { background: rgba(10,132,255,0.18); }"
            % ("rgba(38,38,42,0.98)" if self._theme == "dark" else "rgba(252,252,255,0.99)",
               self._overlay("0.12", "0.10"),
               c["TEXT"][0], c["TEXT"][1], c["TEXT"][2]))
        copy = menu.addAction("复制 ID")
        copy.triggered.connect(lambda _=False: QApplication.clipboard().setText(sid))
        if data.get("window"):
            focus = menu.addAction("聚焦窗口")
            focus.triggered.connect(lambda _=False: focus_window(data.get("window")))
        menu.addSeparator()
        close = menu.addAction("收起")
        close.triggered.connect(lambda _=False: self._toggle(sid))
        return menu

    def _action_style(self, primary):
        c = self._colors
        if primary:
            return ("QPushButton { border:none; background: rgba(10,132,255,0.22);"
                    " border-radius:8px; padding:4px 10px; font-size:11px; color: rgb(%d,%d,%d); }"
                    "QPushButton:hover { background: rgba(10,132,255,0.34); }"
                    % c["TEXT"])
        return ("QPushButton { border:none; background: %s;"
                " border-radius:8px; padding:4px 10px; font-size:11px; color: rgb(%d,%d,%d); }"
                "QPushButton:hover { background: %s; }"
                "QPushButton::menu-indicator { image: none; }"
                % (self._overlay("0.06", "0.05"),
                   c["TEXT_SECONDARY"][0], c["TEXT_SECONDARY"][1], c["TEXT_SECONDARY"][2],
                   self._overlay("0.12", "0.09")))

    # ── 动作 ──────────────────────────────────────
    def _toggle(self, sid):
        self._expanded = "" if self._expanded == sid else sid
        self._last_sig = ""
        self._tick()

    def _cancel(self, sid):
        try:
            store.update(sid, {"action": "cancel", "source": "qt"})
        except Exception:  # noqa: BLE001
            pass
        self._tick()

    def _resume(self, data):
        sid = str(data.get("sessionId") or "")
        try:
            # 与驾驶舱同源：retry 复位原步骤，避免 fail 后追加伪步骤
            store.update(sid, {"action": "retry", "source": "qt"})
        except Exception:  # noqa: BLE001
            pass
        self._tick()
