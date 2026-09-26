# -*- coding: utf-8 -*-
"""AgentFloat — 设计 token 唯一来源（配色 / 字体 / 浮球度量）

合并原 agent_float.THEMES 与 af_theme.py 两份重复定义；
P2 将在此基础上接入 ProjectDock 风格 token（色板/圆角/动效）。
"""

THEMES = {
    "light": {
        "GLASS_BG":        (255, 255, 255),   # 毛玻璃白底
        "BORDER":          (255, 255, 255),   # 玻璃边框
        "INPUT_BORDER":    (209, 209, 214),   # 输入框边框 #D1D1D6
        "SHADOW":          (0, 0, 0),         # 柔和阴影
        "ACCENT":          (0, 122, 255),     # iOS 蓝 #007AFF
        "TEXT":            (28, 28, 30),      # 深色文字 #1C1C1E
        "HINT":            (142, 142, 147),   # 系统灰 #8E8E93
        "SURFACE":         (242, 242, 247),   # 浅灰底 #F2F2F7
        "SEPARATOR":       (229, 229, 234),   # 分隔线 #E5E5EA
        "TEXT_SECONDARY":  (60, 60, 67),      # 二级文字 #3C3C43
        "WARN_BG":         (255, 229, 229),   # 警告背景浅红 #FFE5E5
        "WARN_FG":         (255, 59, 48),     # 警告文字红色 #FF3B30
    },
    "dark": {
        "GLASS_BG":        (28, 28, 30),      # 暗色毛玻璃 #1C1C1E
        "BORDER":          (72, 72, 74),      # 暗色边框 #48484A
        "INPUT_BORDER":    (90, 90, 95),      # 输入框边框 #5A5A5F
        "SHADOW":          (0, 0, 0),         # 阴影（不变）
        "ACCENT":          (10, 132, 255),    # iOS 暗色蓝 #0A84FF
        "TEXT":            (242, 242, 247),   # 浅色文字 #F2F2F7
        "HINT":            (152, 152, 157),   # 暗色灰 #98989D
        "SURFACE":         (44, 44, 46),      # 深灰底 #2C2C2E
        "SEPARATOR":       (56, 56, 58),      # 暗色分隔线 #38383A
        "TEXT_SECONDARY":  (235, 235, 245),   # 二级文字 #EBEBF5
        "WARN_BG":         (61, 31, 31),      # 暗色警告背景 #3D1F1F
        "WARN_FG":         (255, 107, 107),   # 暗色警告文字 #FF6B6B
    },
}

def get_colors(theme="light"):
    """返回当前主题的配色字典"""
    t = THEMES.get(theme, THEMES["light"])
    return t

# 兼容别名：模块加载时使用默认 light 主题
_LIGHT = THEMES["light"]
IOS_GLASS_BG   = _LIGHT["GLASS_BG"]
IOS_BORDER     = _LIGHT["BORDER"]
IOS_SHADOW     = _LIGHT["SHADOW"]
IOS_ACCENT     = _LIGHT["ACCENT"]
IOS_TEXT       = _LIGHT["TEXT"]
IOS_HINT       = _LIGHT["HINT"]
IOS_SURFACE    = _LIGHT["SURFACE"]

FONT_FAMILY = "Microsoft YaHei"

DEFAULT_SIZE  = 52          # 默认边长 px
CORNER_RADIUS = 18          # 圆角半径 (iOS 连续曲线风格)
HOVER_SCALE   = 1.08        # 悬停放大比例
PRESS_SCALE   = 0.94        # 按压缩小比例
