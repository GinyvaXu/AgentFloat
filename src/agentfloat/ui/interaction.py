# -*- coding: utf-8 -*-
"""浮球交互状态机（纯逻辑，无 Qt 依赖，可单测）

背景：单击/悬停/长按/拖拽/贴边隐藏五路输入此前分散在多个 QTimer 与标志位中，
历史上修复十余次仍互相打架（v1.0.7–v2.2.1）。本模块把「何时该做什么」收敛为
显式状态 + 冷却窗口；视图层只负责计时精度与执行动作。

状态：
    idle       待机（未按压）
    pressed    按下未判定（未超位移阈值、未超时长）
    dragging   拖拽中
    menu_held  长按已唤出菜单（本次按压不再触发点击）

冷却窗口（悬停展开抑制）：
    ① 贴边唤出/按压弹出后 REVEAL_SUPPRESS_S
    ② 拖拽结束后 DRAG_SUPPRESS_S
    ③ 菜单关闭后 MENU_SUPPRESS_S
    ④ 按压/拖拽/菜单打开期间恒抑制
"""
from __future__ import annotations

CLICK_MOVE_PX = 4.0          # 位移超过该值判定为拖拽（兼容旧逻辑）
# PATCH 3.3.0（游戏式手势）：
#   按住不动（中心区）→ 环形进度条 → 约 2s 默认启动
#   按住后立即向外滑（未超移动延迟）→ 环形菜单（轮盘，松手执行）
#   按住超过移动延迟后拖动 → 移动浮窗
CENTER_ZONE_PX = 14.0        # 「中心区」半径：按住期间位移不超过它才算「按住不动」
REVEAL_SUPPRESS_S = 0.35     # ① 贴边唤出后：悬停展开抑制窗口
DRAG_SUPPRESS_S = 0.25       # ② 拖拽结束后：悬停展开抑制窗口
MENU_SUPPRESS_S = 0.30       # ③ 菜单关闭后：悬停展开抑制窗口


class Actions(object):
    """视图层需要执行的动作（字符串常量）"""
    HOVER_IN = "hover_in"
    HOVER_OUT = "hover_out"
    BEGIN_DRAG = "begin_drag"
    BEGIN_WHEEL = "begin_wheel"      # PATCH 3.3.0：按住外滑 → 打开轮盘菜单
    END_DRAG = "end_drag"
    CLICK = "click"
    LAUNCH_HOLD = "launch_hold"      # PATCH 3.3.0：按住不动完成 → 默认启动
    OPEN_MENU = "open_menu"


class BallInteraction(object):
    """浮球交互裁决器（无副作用，除内部状态外不做任何动作）"""

    def __init__(self, radial_cfg=None):
        self.reset()
        self.configure(radial_cfg)

    # ── 生命周期 ──────────────────────────────────
    def reset(self):
        self._state = "idle"
        self._press_moved = 0.0
        self._menu_open = False
        self._press_in_menu = False
        self._t_reveal = -1e9
        self._t_drag_end = -1e9
        self._t_menu_closed = -1e9
        self._enabled = True
        self._hover_ms = 180.0
        self._long_press_ms = 300.0
        self._trigger_mode = "both"
        self._hold_select = True
        self._hold_launch_ms = 2000.0    # PATCH 3.3.0
        self._move_delay_ms = 350.0      # PATCH 3.3.0
        self._wheel_enabled = True       # PATCH 3.3.0
        self._press_t = 0.0
        return self

    def configure(self, radial_cfg=None):
        cfg = radial_cfg or {}
        self._enabled = bool(cfg.get("enabled", True))
        self._hover_ms = float(cfg.get("hover_delay_ms", 180))
        self._long_press_ms = float(cfg.get("long_press_delay_ms", 300))
        mode = cfg.get("trigger_mode", "both")
        self._trigger_mode = mode if mode in ("hover", "long_press", "both", "wheel") else "both"
        self._hold_select = bool(cfg.get("hold_select", True))
        self._hold_launch_ms = max(500.0, float(cfg.get("hold_launch_ms", 2000)))
        self._move_delay_ms = max(120.0, float(cfg.get("move_delay_ms", 350)))
        self._wheel_enabled = bool(cfg.get("wheel_enabled", True))
        return self

    # ── 只读属性 ──────────────────────────────────
    @property
    def state(self):
        return self._state

    @property
    def enabled(self):
        return self._enabled

    @property
    def hover_channel(self):
        """悬停唤出已取消（PATCH 3.3.1）"""
        return False

    @property
    def wheel_enabled(self):
        """按住外滑唤出轮盘（PATCH 3.3.0）"""
        return bool(self._enabled and self._wheel_enabled)

    @property
    def hover_delay_ms(self):
        return int(self._hover_ms)

    @property
    def hold_launch_ms(self):
        return int(self._hold_launch_ms)

    @property
    def move_delay_ms(self):
        return int(self._move_delay_ms)

    @property
    def hold_select(self):
        """按住选环：长按弹出后不松手，滑到扇区松手即执行（PATCH 3.2.0）"""
        return bool(self._hold_select)

    # ── 外部通知 ──────────────────────────────────
    def notify_reveal(self, t):
        """贴边唤出/按压弹出发生（用于抑制悬停展开）"""
        self._t_reveal = t

    def menu_opened(self, t):
        self._menu_open = True

    def menu_closed(self, t):
        self._menu_open = False
        self._t_menu_closed = t

    # ── 裁决 ──────────────────────────────────────
    def hover_open_allowed(self, t):
        """悬停唤出已取消（PATCH 3.3.1）：悬停只做视觉反馈，不再展开菜单。

        菜单唤出方式仅剩「按住立即外滑（轮盘）」；按住不动则为启动进度。
        """
        return False

    # ── 输入事件 ──────────────────────────────────
    def press(self, t):
        """左键按下"""
        self._press_in_menu = self._menu_open
        self._press_moved = 0.0
        self._press_t = t
        if self._state == "idle":
            self._state = "pressed"
        return []

    def move(self, total_delta_px, t):
        """按住移动（total_delta_px = 相对按下点的累计曼哈顿距离）

        PATCH 3.3.1：
        - 中心区（≤14px）内不动 → 继续累计「按住启动」进度
        - 中心区外滑 → 打开轮盘菜单（松手执行）；移动浮窗改由轮盘「移动浮窗」扇区提供
        - 轮盘关闭时回落为直接拖动浮窗（兼容旧行为）
        """
        self._press_moved = float(total_delta_px)
        if self._state != "pressed" or self._press_moved <= CENTER_ZONE_PX:
            return []
        if self._wheel_enabled:
            self._state = "wheel"
            return [Actions.BEGIN_WHEEL]
        self._state = "dragging"
        return [Actions.BEGIN_DRAG]

    def hold_progress(self, t):
        """按住不动进度 0..1（供视图绘制环形进度条）"""
        if self._state != "pressed" or self._press_moved > CENTER_ZONE_PX:
            return 0.0
        return max(0.0, min(1.0, (t - self._press_t) * 1000.0 / self._hold_launch_ms))

    def hold_tick(self, t):
        """按住进度检查（视图定时器调用）；完成时返回 LAUNCH_HOLD"""
        if self._state != "pressed" or self._press_moved > CENTER_ZONE_PX:
            return []
        if (t - self._press_t) * 1000.0 >= self._hold_launch_ms:
            self._state = "launched"
            return [Actions.LAUNCH_HOLD]
        return []

    def release(self, t):
        """左键释放"""
        was = self._state
        self._state = "idle"
        if was == "dragging":
            self._t_drag_end = t
            return [Actions.END_DRAG]
        if was == "pressed":
            if self._press_in_menu:
                # 菜单打开时的按压由菜单自身处理（中心孔点击），不重复启动
                return []
            return [Actions.CLICK]
        return []

    def cancel(self):
        """强制回到待机（关闭菜单 / 取消操作时）"""
        self._state = "idle"

    def hover_enter(self, t):
        return [Actions.HOVER_IN]

    def hover_leave(self, t):
        return [Actions.HOVER_OUT]

    def hover_timer_fired(self, t):
        """悬停计时器到点（视图精确计时，状态机做最终校验）"""
        if not self.hover_open_allowed(t):
            return []
        return [Actions.OPEN_MENU]
