# -*- coding: utf-8 -*-
"""AgentFloat — 设计 token 唯一来源（配色 / 字体 / 浮球度量）

合并原 agent_float.THEMES 与 af_theme.py 两份重复定义；
v2.4.0 起色板对齐 ProjectDock 设计语言（web/css/style.css 同名变量）：

- 强调色统一 #0a84ff（亮/暗）：亮色深按 #0071e3，暗色亮按 #409cff
- 文字三级：亮 #1d1d1f / #6e6e73 / #98989d；暗 #f5f5f7 / #a1a1a6 / #636366
- 语义色：红 #ff3b30（暗 #ff453a）/ 绿 #34c759（暗 #32d74b）/ 橙 #ff9500（暗 #ff9f0a）
"""
THEMES = {
    "light": {
        "GLASS_BG":        (255, 255, 255),   # 毛玻璃白底
        "BORDER":          (255, 255, 255),   # 玻璃边框
        "INPUT_BORDER":    (209, 209, 214),   # 输入框边框 #D1D1D6
        "SHADOW":          (0, 0, 0),         # 柔和阴影
        "ACCENT":          (10, 132, 255),    # 品牌蓝 #0A84FF
        "ACCENT_STRONG":   (0, 113, 227),     # 品牌蓝·深按 #0071E3
        "TEXT":            (29, 29, 31),      # 主文字 #1D1D1F
        "HINT":            (152, 152, 157),   # 辅助灰 #98989D
        "SURFACE":         (242, 242, 247),   # 浅灰底 #F2F2F7
        "SEPARATOR":       (229, 229, 234),   # 分隔线 #E5E5EA
        "TEXT_SECONDARY":  (110, 110, 115),   # 二级文字 #6E6E73
        "WARN_BG":         (255, 229, 229),   # 警告背景浅红 #FFE5E5
        "WARN_FG":         (255, 59, 48),     # 警告红 #FF3B30
        "OK":              (52, 199, 89),     # 成功绿 #34C759
        "WARNING":         (255, 149, 0),     # 提醒橙 #FF9500
    },
    "dark": {
        "GLASS_BG":        (28, 28, 30),      # 暗色毛玻璃 #1C1C1E
        "BORDER":          (72, 72, 74),      # 暗色边框 #48484A
        "INPUT_BORDER":    (90, 90, 95),      # 输入框边框 #5A5A5F
        "SHADOW":          (0, 0, 0),         # 阴影（不变）
        "ACCENT":          (10, 132, 255),    # 品牌蓝 #0A84FF
        "ACCENT_STRONG":   (64, 156, 255),    # 品牌蓝·亮按 #409CFF
        "TEXT":            (245, 245, 247),   # 主文字 #F5F5F7
        "HINT":            (152, 152, 157),   # 辅助灰 #98989D
        "SURFACE":         (44, 44, 46),      # 深灰底 #2C2C2E
        "SEPARATOR":       (56, 56, 58),      # 暗色分隔线 #38383A
        "TEXT_SECONDARY":  (161, 161, 166),   # 二级文字 #A1A1A6
        "WARN_BG":         (61, 31, 31),      # 暗色警告背景 #3D1F1F
        "WARN_FG":         (255, 69, 58),     # 暗色警告红 #FF453A
        "OK":              (50, 215, 75),     # 成功绿 #32D74B
        "WARNING":         (255, 159, 10),    # 提醒橙 #FF9F0A
    },
}


def get_colors(theme="light"):
    """返回当前主题的配色字典"""
    return THEMES.get(theme, THEMES["light"])


# ── 字体 ──────────────────────────────────────────────
FONT_FAMILY = "Microsoft YaHei"


# ── 浮球度量（P2 重绘方案落地后微调）──────────────────
DEFAULT_SIZE  = 52          # 默认边长 px
CORNER_RADIUS = 18          # 圆角半径 (iOS 连续曲线风格)
HOVER_SCALE   = 1.08        # 悬停放大比例
PRESS_SCALE   = 0.94        # 按压缩小比例
