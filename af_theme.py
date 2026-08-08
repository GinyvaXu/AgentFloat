# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 共享主题配色（供主程序 / 环绕菜单 / Skills 面板 / 管理对话框使用）"""
THEMES = {
    "light": {
        "GLASS_BG":        (255, 255, 255),   # 毛玻璃白底
        "BORDER":          (255, 255, 255),   # 玻璃边框
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
    return THEMES.get(theme, THEMES["light"])
