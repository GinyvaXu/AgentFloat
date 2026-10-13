# -*- coding: utf-8 -*-
"""AgentFloat — 弹簧动效引擎与动效 token（对齐 ProjectDock web/spring.js 的手感）

设计要点：
- SpringState：纯数值弹簧（无 Qt 依赖，可单测）；数值积分 a = ((goal-v)*k - v*c)/m
- MotionDriver：单一 60fps 定时器驱动所有活动弹簧（避免每个动画各占一个 QTimer）
- 从当前值起步、可随时打断重定向（速度继承）——「跟手」的关键
- reduced-motion 开关（降级为直接跳变）
"""
import math as _math
import time as _time

try:
    from PyQt5.QtCore import QObject, QTimer
except Exception:  # 纯逻辑测试环境（无 Qt）降级
    QObject = object

    class QTimer(object):  # type: ignore
        def __init__(self, *a, **k):
            raise RuntimeError("Qt 不可用")


# ── 动效 token（统一时长/阻尼，供全项目引用）────────────
class Tokens(object):
    TICK_MS = 16                  # 60fps 驱动
    # 弹簧参数（刚度 k / 阻尼 c）——k 越大越快、c 越大越"稳"
    RING_OPEN = (420.0, 28.0)     # 环菜单展开：快而稳（PATCH 3.2.1，约 0.25s）
    RING_CLOSE = (460.0, 34.0)    # 环菜单收拢：干脆不过冲
    SLIDE = (340.0, 34.0)         # 贴边滑入/滑出：快而稳
    PRESS = (480.0, 30.0)         # 按压回弹：快、微过冲
    QUIT = (300.0, 28.0)          # 退出收拢
    SPEED = (300.0, 26.0)         # 通用速度感
    # PATCH 3.3.0：窗口/面板渐入渐出时长（ms）
    PANEL_IN_MS = 200
    PANEL_OUT_MS = 150
    # ── v3.13.0 动效方案（motion-ui-design 守则）新增令牌 ──────────
    # 弹簧统一按 (刚度 k, 阻尼 c)，mass=1 时 k=ω²、c=2ζω：
    UI = (484.0, 33.0)            # ω22 ζ0.75：列表项 / 卡片 / 选中条
    PAGE = (256.0, 27.2)          # ω16 ζ0.85：页面 / 分栏切换
    TAP = (2025.0, 90.0)          # ω45 ζ1.0：按下压入（快、不回弹）
    RELEASE = (121.0, 8.8)        # ω11 ζ0.4：松开回弹（回弹只留给松开）
    POP = (676.0, 23.4)           # ω26 ζ0.45：角标 / 收藏弹入
    UI_COLLAPSE = (484.0, 44.0)   # ω22 ζ1.0：列表项收拢（防"翻出来"）
    # 指数平滑速度（1/s）：跟随类（无过冲）
    FOLLOW_SPEED = 14.0           # 位置跟随（移动模式、光标高亮、涟漪）
    TEXT_SPEED = 16.0             # 进度线 / 滚动偏移 / 文字
    # 时长（ms）
    DUR_TAP_MS = 90               # 按压反馈（与收合对齐）
    DUR_FLASH_MS = 150            # 状态文案淡出
    # 距离（px，桌面端克制在 1~8px；大元素最多 2 倍）
    DIST_TAP = 2
    DIST_OVERPULL = 6
    DIST_OVERPULL_BIG = 10
    DIST_PEEK = 8
    # 波浪 / 级联
    STAGGER_LIST = 0.20
    STAGGER_ROW = 0.15
    CASCADE_LIST = 10
    CASCADE_ROW = 6
    SETTLE_HOLD_S = 0.8           # 滚动条收缩等闲置判定


SNAP_EPS = 0.0015        # 到位判定：值差
SNAP_VEL = 0.02          # 到位判定：速度
SMOOTH_EPS = 0.01        # 平滑值到位判定：值差（像素取整后不可见）
MAX_DT = 1.0 / 30.0      # 积分步长上限（避免卡顿后跳变）
_REDUCED = False
_LEGACY = False          # v3.13.0：动效回退开关（True = 用原始动效实现）


def set_reduced_motion(flag):
    global _REDUCED
    _REDUCED = bool(flag)


def reduced_motion():
    return _REDUCED


def set_legacy_motion(flag):
    """动效回退开关：True 时各调用点走原始（v3.12.x）动效实现

    用途：新版动效若在实机上不稳定，设置里切回经典动效即可，无需回退版本。
    """
    global _LEGACY
    _LEGACY = bool(flag)


def legacy_motion():
    return _LEGACY


class SpringState(object):
    """纯数值弹簧。用法：state.to(goal)；每帧 state.step(dt) → 是否仍在运动。"""
    __slots__ = ("value", "velocity", "goal", "stiffness", "damping", "mass")

    def __init__(self, initial=0.0, stiffness=220.0, damping=26.0, mass=1.0):
        self.value = float(initial)
        self.velocity = 0.0
        self.goal = float(initial)
        self.stiffness = float(stiffness)
        self.damping = float(damping)
        self.mass = max(0.01, float(mass))

    def set_params(self, stiffness=None, damping=None, mass=None):
        if stiffness is not None:
            self.stiffness = float(stiffness)
        if damping is not None:
            self.damping = float(damping)
        if mass is not None:
            self.mass = max(0.01, float(mass))
        return self

    def to(self, goal):
        """重定向到目标（从当前值起步、保留速度 → 可打断/速度继承）"""
        self.goal = float(goal)
        return self

    def kick(self, px):
        """给弹簧一记冲量（px 级位移）：甩出 / 落地抖动 / 无路可退的推挤

        impulse = px · ω · e，ω = sqrt(k/m)
        """
        try:
            omega = _math.sqrt(max(1e-6, self.stiffness / self.mass))
            self.velocity += float(px) * omega * _math.e
        except Exception:  # noqa: BLE001
            pass
        return self

    def jump(self, value):
        """立即设值（同时清除速度）"""
        self.value = float(value)
        self.velocity = 0.0
        self.goal = float(value)
        return self

    def step(self, dt):
        """推进一帧；返回是否仍在运动"""
        if _REDUCED:
            self.jump(self.goal)
            return False
        dt = min(max(float(dt), 0.0), MAX_DT) or (1.0 / 60.0)
        acc = ((self.goal - self.value) * self.stiffness
               - self.velocity * self.damping) / self.mass
        self.velocity += acc * dt
        self.value += self.velocity * dt
        if abs(self.goal - self.value) <= SNAP_EPS and abs(self.velocity) <= SNAP_VEL:
            self.jump(self.goal)
            return False
        return True


class SmoothState(object):
    """指数平滑值（跟随类，永不越界/振荡）

        current += (target - current) * (1 - e^(-speed·dt))

    speed 单位 1/s：speed 秒后走完约 63%，3/speed 秒后约 95%。
    适合：位置跟随、滚动偏移、光标移动、进度线、跑马灯。
    与 SpringState 接口一致（to/jump/step/value），可交给同一个 MotionDriver。
    """
    __slots__ = ("value", "goal", "speed")

    def __init__(self, initial=0.0, speed=14.0):
        self.value = float(initial)
        self.goal = float(initial)
        self.speed = max(0.01, float(speed))

    def to(self, goal):
        self.goal = float(goal)
        return self

    def jump(self, value):
        self.value = float(value)
        self.goal = float(value)
        return self

    def step(self, dt):
        """推进一帧；返回是否仍在运动（帧率无关，dt 有上限）"""
        if _REDUCED:
            self.jump(self.goal)
            return False
        dt = min(max(float(dt), 0.0), MAX_DT) or (1.0 / 60.0)
        self.value += (self.goal - self.value) * (1.0 - _math.exp(-self.speed * dt))
        if abs(self.goal - self.value) <= SMOOTH_EPS:
            self.jump(self.goal)
            return False
        return True


class MotionDriver(QObject):
    """全局动效驱动器：单一定时器批量推进所有活动弹簧与平滑值。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []            # [state, on_change, on_done]
        self._last = None
        self._timer = QTimer(self)
        self._timer.setInterval(Tokens.TICK_MS)
        self._timer.timeout.connect(self._tick)

    def animate(self, state, on_change, on_done=None):
        """注册弹簧；返回「取消」函数。on_change(value) 每帧回调。"""
        item = [state, on_change, on_done]
        self._items.append(item)
        self._last = _time.monotonic() - Tokens.TICK_MS / 1000.0
        if not self._timer.isActive():
            self._timer.start()
        return lambda: self._cancel(item)

    def animate_to(self, state, goal, on_change, on_done=None):
        state.to(goal)
        return self.animate(state, on_change, on_done)

    def stop_all(self):
        self._items = []
        self._timer.stop()

    def _cancel(self, item):
        try:
            self._items.remove(item)
        except ValueError:
            pass

    def _tick(self):
        now = _time.monotonic()
        dt = now - (self._last if self._last is not None else now)
        self._last = now
        for item in list(self._items):
            state, on_change, on_done = item
            moving = state.step(dt)
            try:
                on_change(state.value)
            except Exception:  # noqa: BLE001
                pass
            if not moving:
                self._items.remove(item)
                if on_done is not None:
                    try:
                        on_done()
                    except Exception:  # noqa: BLE001
                        pass
        if not self._items:
            self._timer.stop()


_motion = None


def motion():
    """全局 MotionDriver 单例（惰性创建；需 QApplication 已存在）"""
    global _motion
    if _motion is None:
        _motion = MotionDriver()
    return _motion


def spring(initial=0.0, params=None):
    """快捷创建：spring(0.0, Tokens.SPEED)"""
    p = params or (Tokens.SPEED[0], Tokens.SPEED[1])
    return SpringState(initial, p[0], p[1])


def follow(initial=0.0, speed=None):
    """快捷创建指数平滑值：follow(0.0, Tokens.FOLLOW_SPEED)"""
    return SmoothState(initial, speed or Tokens.FOLLOW_SPEED)


def drive(state, on_change, on_done=None):
    """把任意动画值（弹簧或平滑值）交给全局驱动器；返回取消函数"""
    return motion().animate(state, on_change, on_done)


def settle(callback, state):
    """便捷：等动画值静息后回调（等价于 drive 的 on_done）"""
    return motion().animate(state, lambda _v: None, callback)
