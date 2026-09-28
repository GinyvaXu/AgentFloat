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

CLICK_MOVE_PX = 4.0          # 位移超过该值判定为拖拽（同时长按失效）
# PATCH 3.2.0（菜单手感）：冷却窗口整体缩短，弹过的浮球更快恢复悬停响应
REVEAL_SUPPRESS_S = 0.35     # ① 贴边唤出后：悬停展开抑制窗口
DRAG_SUPPRESS_S = 0.25       # ② 拖拽结束后：悬停展开抑制窗口
MENU_SUPPRESS_S = 0.30       # ③ 菜单关闭后：悬停展开抑制窗口


class Actions(object):
    """视图层需要执行的动作（字符串常量）"""
    HOVER_IN = "hover_in"
    HOVER_OUT = "hover_out"
    BEGIN_DRAG = "begin_drag"
    END_DRAG = "end_drag"
    CLICK = "click"
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
        return self

    def configure(self, radial_cfg=None):
        cfg = radial_cfg or {}
        self._enabled = bool(cfg.get("enabled", True))
        self._hover_ms = float(cfg.get("hover_delay_ms", 180))
        self._long_press_ms = float(cfg.get("long_press_delay_ms", 300))
        mode = cfg.get("trigger_mode", "both")
        self._trigger_mode = mode if mode in ("hover", "long_press", "both") else "both"
        self._hold_select = bool(cfg.get("hold_select", True))
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
        return self._enabled and self._trigger_mode in ("hover", "both")

    @property
    def long_press_channel(self):
        return self._enabled and self._trigger_mode in ("long_press", "both")

    @property
    def hover_delay_ms(self):
        return int(self._hover_ms)

    @property
    def long_press_delay_ms(self):
        return int(self._long_press_ms)

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
        """此刻是否允许启动悬停展开计时"""
        if not self.hover_channel:
            return False
        if self._menu_open or self._state != "idle":
            return False
        return not (t < self._t_reveal + REVEAL_SUPPRESS_S
                    or t < self._t_drag_end + DRAG_SUPPRESS_S
                    or t < self._t_menu_closed + MENU_SUPPRESS_S)

    def should_arm_long_press(self):
        return self.long_press_channel and self._state == "pressed"

    # ── 输入事件 ──────────────────────────────────
    def press(self, t):
        """左键按下"""
        self._press_in_menu = self._menu_open
        self._press_moved = 0.0
        if self._state == "idle":
            self._state = "pressed"
        return []

    def move(self, total_delta_px, t):
        """按住移动（total_delta_px = 相对按下点的累计曼哈顿距离）"""
        self._press_moved = float(total_delta_px)
        if self._state == "pressed" and self._press_moved > CLICK_MOVE_PX:
            self._state = "dragging"
            return [Actions.BEGIN_DRAG]
        return []

    def long_press_fired(self, t):
        """长按计时器到点（视图精确计时，状态机校验有效性）"""
        if not self.should_arm_long_press():
            return []
        if self._press_moved > CLICK_MOVE_PX:
            return []
        self._state = "menu_held"
        return [Actions.OPEN_MENU]

    def hover_enter(self, t):
        return [Actions.HOVER_IN]

    def hover_leave(self, t):
        return [Actions.HOVER_OUT]

    def hover_timer_fired(self, t):
        """悬停计时器到点（视图精确计时，状态机做最终校验）"""
        if not self.hover_open_allowed(t):
            return []
        return [Actions.OPEN_MENU]

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
