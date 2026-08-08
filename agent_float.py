"""
AgentFloat — AI Agent 桌面悬浮助手（通用多 Agent 启动器）
- 圆角矩形悬浮窗，iOS 风格毛玻璃质感
- 自由拖拽，始终置顶
- 点击启动主 Agent（默认 Claude Code）
- 悬停 / 长按唤出环绕菜单，切换多 Agent 与扩展功能
- Skills 辅助窗、API 用量监控
- 系统托盘支持、配置持久化
"""
import sys
import io
import os
import json
import subprocess
import shutil
import ctypes
import logging
import copy
from logging.handlers import RotatingFileHandler
from ctypes import wintypes

if sys.platform == 'win32':
    try:
        if sys.stdout and hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if sys.stderr and hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

from PyQt5.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QSpinBox, QGroupBox, QRadioButton, QCheckBox, QLineEdit, QFileDialog, QMessageBox,
    QScrollArea, QComboBox, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import (
    Qt, QPoint, QPointF, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, pyqtProperty, QRect, QRectF, QtMsgType, qInstallMessageHandler,
)
from PyQt5.QtGui import (
    QPainter, QBrush, QColor, QRadialGradient, QLinearGradient, QPen, QFont,
    QPixmap, QIcon, QRegion, QCursor, QFontDatabase, QPainterPath
)

# ── API 用量监控模块 ────────────────────────────
from api_monitor_config import (
    DEFAULTS as API_MONITOR_DEFAULTS, SAMPLE_ENDPOINT, validate_api_monitor_config,
)
from api_balance_badge import ApiBalanceBadge
from api_monitor_worker import ApiMonitorWorker
from api_monitor_settings import ApiMonitorSettingsTab
from updater import UpdateWorker, DownloadWorker, pick_setup_asset

# ── AgentFloat 通用多 Agent 模块 ────────────────────
from agent_registry import (
    default_agents, normalize_agents, get_primary_agent, find_agent,
    resolve_command, build_agent_args, primary_launch_mode,
    DEFAULT_RADIAL_MENU, DEFAULT_SKILLS,
)
from radial_menu import RadialMenu, RadialMenuItem
from skills_scanner import default_skill_roots
from skills_panel import SkillsPanel
from agent_manager import AgentManagerDialog, SkillsSettingsDialog

# ── 路径（兼容 PyInstaller 打包）──────────────────────
import sys as _sys
_IS_FROZEN = getattr(_sys, 'frozen', False)

# Debug 版检测：PyInstaller --console 打包时 sys.stdout 可用
# --windowed 打包时 sys.stdout 为 None（仅 debug 构建启用）
_IS_DEBUG = _IS_FROZEN and sys.stdout is not None

def _resolve_path(*parts):
    """解析资源路径，兼容 PyInstaller 打包和开发模式"""
    if _IS_FROZEN:
        base = _sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SCRIPT_DIR)
ICO_PATH  = _resolve_path("assets", "agent_float_icon.ico")
PNG_PATH  = _resolve_path("assets", "agent_float_icon.png")

# 配置路径：打包后存 %APPDATA%/AgentFloat/，开发时存脚本目录
def _get_config_dir():
    if _IS_FROZEN:
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AgentFloat")
    return SCRIPT_DIR

def _get_config_path():
    d = _get_config_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "config.json")

# 旧配置路径（用于自动迁移）
_OLD_CONFIG_PATH = os.path.join(SCRIPT_DIR, "launcher_config.json")
CONFIG_PATH = _get_config_path()

# ── 日志系统 ──────────────────────────────────────────
_logger = None

def _setup_logger():
    """初始化日志系统。

    Debug 版（--console）：控制台输出 + 独立 debug_logs/ 会话日志 + 滚动日志
    Release 版（--windowed）：仅滚动文件日志
    """
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("AgentFloat")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        _logger = logger
        return logger

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-5s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if _IS_DEBUG:
        # 1) 控制台实时输出
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

        # 2) 独立 debug_logs 文件夹，每次启动新建会话日志
        from datetime import datetime
        debug_dir = os.path.join(_get_config_dir(), "debug_logs")
        os.makedirs(debug_dir, exist_ok=True)
        session_name = datetime.now().strftime("session_%Y%m%d_%H%M%S.log")
        fh = logging.FileHandler(os.path.join(debug_dir, session_name), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # 3) 保留滚动日志（方便跨会话排查）
        log_dir = os.path.join(_get_config_dir(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        rh = RotatingFileHandler(
            os.path.join(log_dir, "AgentFloat.log"),
            maxBytes=1 * 1024 * 1024, backupCount=4, encoding="utf-8"
        )
        rh.setLevel(logging.DEBUG)
        rh.setFormatter(fmt)
        logger.addHandler(rh)
    else:
        # Release 版：仅滚动文件日志
        log_dir = os.path.join(_get_config_dir(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(log_dir, "AgentFloat.log"),
            maxBytes=1 * 1024 * 1024, backupCount=4, encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    _logger = logger
    return logger

def _log():
    """获取 logger 实例（惰性初始化，避免循环依赖）"""
    global _logger
    if _logger is None:
        return _setup_logger()
    return _logger

STARTUP_FOLDER = os.path.join(
    os.environ.get("APPDATA", ""),
    "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
)
STARTUP_LNK_NAME = "AgentFloat.lnk"

def _escape_vbs_path(path):
    """转义路径中的特殊字符以便安全嵌入 VBScript 字符串（双引号 → 双双引号）"""
    return path.replace('"', '""')

# ── iOS 风格配色 ──────────────────────────────────────
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
VERSION = "1.0.3"

# ── 浮窗参数 ──────────────────────────────────────────
DEFAULT_SIZE  = 52          # 默认边长 px
CORNER_RADIUS = 18          # 圆角半径 (iOS 连续曲线风格)
HOVER_SCALE   = 1.08        # 悬停放大比例
PRESS_SCALE   = 0.94        # 按压缩小比例

# ── 配置 ──────────────────────────────────────────────
def _default_api_monitor():
    """内置默认 API 监控配置：含脱敏示例端点，新用户开箱即用（默认不启用）"""
    cfg = copy.deepcopy(API_MONITOR_DEFAULTS)
    cfg.setdefault("endpoints", [])
    if not cfg["endpoints"]:
        cfg["endpoints"] = [copy.deepcopy(SAMPLE_ENDPOINT)]
    return cfg


def load_config():
    defaults = {
        "window_x": -1, "window_y": -1,
        "auto_start": False,
        "launch_mode": "normal",
        "widget_size": DEFAULT_SIZE,
        "opacity": 0.88,
        "working_directory": "",
        "snap_enabled": True,
        "snap_edge": "right",
        "snap_hidden": True,
        "hide_delay_ms": 800,
        "cleanup_on_quit": False,
        "check_updates": True,
        "theme": "light",
        "agents": default_agents(),
        "radial_menu": copy.deepcopy(DEFAULT_RADIAL_MENU),
        "skills": copy.deepcopy(DEFAULT_SKILLS),
        "api_monitor": _default_api_monitor(),
    }
    loaded = {}

    # 尝试从当前配置路径加载
    config_sources = [CONFIG_PATH]
    # 如果旧路径存在且不同于新路径，也尝试加载并迁移
    if os.path.exists(_OLD_CONFIG_PATH) and os.path.abspath(_OLD_CONFIG_PATH) != os.path.abspath(CONFIG_PATH):
        config_sources.insert(0, _OLD_CONFIG_PATH)

    for src in config_sources:
        try:
            with open(src, "r", encoding="utf-8") as f:
                loaded.update(json.load(f))
            _log().debug("配置加载自: %s", os.path.basename(src))
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, IOError):
            _log().warning("配置加载失败: %s", os.path.basename(src))

    defaults.update(loaded)

    # ── 值校验：防止损坏的配置导致不可恢复状态 ──
    defaults["widget_size"] = max(30, min(200, int(defaults.get("widget_size", DEFAULT_SIZE))))
    defaults["opacity"] = max(0.1, min(1.0, float(defaults.get("opacity", 0.88))))
    defaults["launch_mode"] = defaults["launch_mode"] if defaults["launch_mode"] in ("normal", "skip_permissions") else "normal"
    defaults["theme"] = defaults["theme"] if defaults.get("theme") in ("light", "dark") else "light"

    # 首次启动时检测 Windows 系统主题
    if not loaded:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            apps_use_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            if apps_use_light == 0:
                defaults["theme"] = "dark"
                _log().info("检测到 Windows 深色主题，自动设置为暗色模式")
        except Exception:
            pass

        # 首次启动：自动生成默认配置文件（含示例端点），新用户开箱即用
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, ensure_ascii=False, indent=2)
            _log().info("首次启动，已生成默认配置: %s", CONFIG_PATH)
        except (IOError, OSError):
            pass

    # 如果从旧路径加载了数据，迁移到新路径
    if config_sources[0] == _OLD_CONFIG_PATH and loaded:
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, ensure_ascii=False, indent=2)
            os.remove(_OLD_CONFIG_PATH)
            _log().info("配置已迁移: %s → %s", _OLD_CONFIG_PATH, CONFIG_PATH)
        except (IOError, OSError):
            pass

    return defaults

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        _log().debug("配置已保存 (%d 键)", len(config))
    except (IOError, OSError):
        _log().warning("配置保存失败: %s", CONFIG_PATH)

def is_auto_start_enabled():
    return os.path.exists(os.path.join(STARTUP_FOLDER, STARTUP_LNK_NAME))

def toggle_auto_start(enable: bool):
    """启用/禁用开机自启。打包为 exe 时直接指向 exe 自身，无需 VBS。"""
    lnk = os.path.join(STARTUP_FOLDER, STARTUP_LNK_NAME)
    if enable:
        if _IS_FROZEN:
            # 打包模式：快捷方式直接指向 exe 自身，简洁可靠
            target = sys.executable
            workdir = os.path.dirname(sys.executable)
        else:
            # 开发模式：创建 VBS 通过 pythonw.exe 启动脚本
            vbs_path = os.path.join(SCRIPT_DIR, "launcher.vbs")
            script_path = os.path.join(SCRIPT_DIR, "agent_float.py")
            with open(vbs_path, "w", encoding="utf-8") as f:
                f.write('Set ws = CreateObject("WScript.Shell")\n')
                f.write(f'ws.Run """{_escape_vbs_path(sys.executable)}"" ""{_escape_vbs_path(script_path)}""", 0, False\n')
            target = vbs_path
            workdir = SCRIPT_DIR

        # 使用环境变量传参避免 PowerShell 注入
        ps_env = os.environ.copy()
        ps_env["CC_LNK"] = lnk
        ps_env["CC_TARGET"] = target
        ps_env["CC_WORKDIR"] = workdir
        ps = (
            '$ws=New-Object -ComObject WScript.Shell;'
            '$sc=$ws.CreateShortcut($env:CC_LNK);'
            '$sc.TargetPath=$env:CC_TARGET;'
            '$sc.WindowStyle=7;'
            '$sc.WorkingDirectory=$env:CC_WORKDIR;'
            '$sc.Description="AgentFloat 浮窗";'
            '$sc.Save()'
        )
        r = subprocess.run(["powershell","-NoProfile","-Command",ps], env=ps_env, capture_output=True, text=True)
        if r.returncode == 0:
            _log().info("开机自启已启用: %s", lnk)
        else:
            _log().warning("开机自启设置失败: %s", r.stderr.strip() if r.stderr else "unknown")
        return r.returncode == 0
    else:
        for p in [lnk, os.path.join(SCRIPT_DIR, "launcher.vbs")]:
            try:
                os.remove(p)
            except OSError:
                pass
        _log().info("开机自启已禁用")
        return True

# ── 启动 Agent ──────────────────────────────────
def launch_agent(agent, config=None):
    """通用 Agent 启动器：检测命令 → wt 启动 → cmd fallback"""
    if config is None:
        config = load_config()
    if not agent:
        _log().warning("launch_agent: agent 为空")
        return

    name = agent.get("name") or "Agent"
    cmd_path, err = resolve_command(agent)
    if cmd_path is None:
        _log().warning("Agent 不可用: %s (%s)", name, err)
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "未检测到 %s。\n\n%s\n\n请安装对应 CLI，或在「设置 → Agent 管理」中填写完整路径。" % (name, err),
                "AgentFloat — 命令未找到",
                0x00000030  # MB_ICONWARNING | MB_OK
            )
        except Exception:
            pass
        return

    mode = agent.get("launch_mode", "normal")
    args = build_agent_args(agent, mode)
    args[0] = cmd_path  # 使用解析后的真实路径

    working_dir = (agent.get("working_directory") or config.get("working_directory") or "").strip()
    if not working_dir or not os.path.isdir(working_dir):
        working_dir = os.environ.get("USERPROFILE", WORKSPACE_DIR)

    _log().info("启动 Agent [%s] 模式=%s 命令=%s", name, mode, args)
    try:
        subprocess.Popen(
            ["wt", "-d", working_dir, "--"] + args,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception:
        _log().info("wt 不可用，使用 cmd start fallback")
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", name] + args,
                cwd=working_dir, creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            _log().error("启动 Agent [%s] 失败: %s", name, e)


def launch_claude_code(config=None):
    """兼容入口：启动主 Agent（默认 Claude Code）"""
    if config is None:
        config = load_config()
    launch_agent(get_primary_agent(config.get("agents", default_agents())), config)


# ── 中文字体探测 ──────────────────────────────────────
def _get_cjk_font():
    db = QFontDatabase()
    families = set(db.families())
    for n in ["Microsoft YaHei","Microsoft YaHei UI","PingFang SC","SimHei","SimSun"]:
        if n in families: return n
    return FONT_FAMILY

# ── 设置对话框 ────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.result_config = None
        self._cjk = _get_cjk_font()
        self.theme = self.config.get("theme", "light")
        self._c = get_colors(self.theme)
        self._original_theme = self.theme  # 用于取消时还原
        self._theme_widgets = {}  # 存储控件引用用于即时换肤
        self._api_config = self.config.get("api_monitor", API_MONITOR_DEFAULTS).copy()
        self._agents = normalize_agents(self.config.get("agents"))
        self._primary_agent_id = (get_primary_agent(self._agents) or {}).get("id")
        self._radial_cfg = copy.deepcopy(self.config.get("radial_menu") or DEFAULT_RADIAL_MENU)
        self._skills_cfg = copy.deepcopy(self.config.get("skills") or DEFAULT_SKILLS)
        # 拖拽状态 (v1.4.1)
        self._dragging = False
        self._drag_start = QPoint()
        self._window_origin = QPoint()
        self._build_styles()
        self._setup_ui()

    def _build_styles(self):
        """根据当前主题预构建所有 stylesheet 字符串"""
        c = self._c
        # 提取常用颜色为 hex 字符串
        sf = f"#{c['SURFACE'][0]:02X}{c['SURFACE'][1]:02X}{c['SURFACE'][2]:02X}"
        tx = f"#{c['TEXT'][0]:02X}{c['TEXT'][1]:02X}{c['TEXT'][2]:02X}"
        hi = f"#{c['HINT'][0]:02X}{c['HINT'][1]:02X}{c['HINT'][2]:02X}"
        ac = f"#{c['ACCENT'][0]:02X}{c['ACCENT'][1]:02X}{c['ACCENT'][2]:02X}"
        sp = f"#{c['SEPARATOR'][0]:02X}{c['SEPARATOR'][1]:02X}{c['SEPARATOR'][2]:02X}"
        bd = f"#{c['BORDER'][0]:02X}{c['BORDER'][1]:02X}{c['BORDER'][2]:02X}"
        # 二级文字色 — 从 THEMES 读取（不再硬编码）
        ts_r, ts_g, ts_b = c['TEXT_SECONDARY']
        text_secondary = f"#{ts_r:02X}{ts_g:02X}{ts_b:02X}"
        # 警告色 — 从 THEMES 读取（暗色/亮色自适应）
        wb_r, wb_g, wb_b = c['WARN_BG']
        warn_bg = f"#{wb_r:02X}{wb_g:02X}{wb_b:02X}"
        wf_r, wf_g, wf_b = c['WARN_FG']
        warn_fg = f"#{wf_r:02X}{wf_g:02X}{wf_b:02X}"
        is_dark = (self.theme == "dark")
        # 卡片白/暗（暗色下略亮于表面，突出卡片层次）
        card_bg = "#333336" if is_dark else "#FFFFFF"
        accent_hover = "#0066D6"  # 暗色下也保持深蓝变体

        self._s = {
            "container": f"#settingsContainer {{ background: {sf}; border: 1px solid {bd}; border-radius: 16px; }}",
            "group": (
                f"QGroupBox {{ color: {tx}; background: {card_bg}; border: 1px solid {bd};"
                f" border-radius: 10px; margin-top: 10px; padding-top: 12px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 4px; }}"
            ),
            "separator": f"background: {sp};",
            "btn": (
                f"QPushButton {{ background: {card_bg}; color: {ac}; border: 1px solid {bd};"
                f" border-radius: 8px; padding: 8px 16px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {sf}; }}"
            ),
            "save_btn": (
                f"QPushButton {{ background: {ac}; color: #FFF; border: none;"
                f" border-radius: 8px; padding: 8px 20px; font-size: 12px; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {accent_hover}; }}"
            ),
            "radio": (
                f"QRadioButton {{ color: {text_secondary}; spacing: 8px; }}"
                f"QRadioButton::indicator {{ width:20px; height:20px; }}"
                f"QRadioButton::indicator:unchecked {{ border:2px solid {bd}; border-radius:10px; background:{card_bg}; }}"
                f"QRadioButton::indicator:checked {{ border:2px solid {ac}; border-radius:10px; background:{ac}; }}"
            ),
            "checkbox": (
                f"QCheckBox {{ color: {text_secondary}; spacing: 8px; }}"
                f"QCheckBox::indicator {{ width: 20px; height: 20px; }}"
                f"QCheckBox::indicator:unchecked {{ border: 2px solid {bd}; border-radius: 6px; background: {card_bg}; }}"
                f"QCheckBox::indicator:checked {{ border: 2px solid {ac}; border-radius: 6px; background: {ac}; }}"
            ),
            "slider": (
                f"QSlider::groove:horizontal {{ height:4px; background:{sp}; border-radius:2px; }}"
                f"QSlider::handle:horizontal {{ width:20px; height:20px; margin:-8px 0;"
                f" background:{card_bg}; border:2px solid {ac}; border-radius:10px; }}"
                f"QSlider::sub-page:horizontal {{ background:{ac}; border-radius:2px; }}"
            ),
            "combo": (
                f"QComboBox {{ background: {card_bg}; color: {tx}; border: 1px solid {bd};"
                f" border-radius: 8px; padding: 5px 8px; font-size: 12px; }}"
                f"QComboBox::drop-down {{ border: none; width: 20px; }}"
                f"QComboBox QAbstractItemView {{ background: {card_bg}; color: {tx};"
                f" selection-background-color: {ac}; border: 1px solid {bd}; }}"
            ),
            "spin": (
                f"QSpinBox {{ background: {card_bg}; color: {tx}; border: 1px solid {bd};"
                f" border-radius: 8px; padding: 4px 6px; font-size: 12px; }}"
            ),
            "list": (
                f"QListWidget {{ background: {card_bg}; color: {tx}; border: 1px solid {bd};"
                f" border-radius: 8px; font-size: 11px; }}"
                f"QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}"
                f"QListWidget::item:selected {{ background: {ac}; color: #FFF; }}"
            ),
            "lineedit": (
                f"QLineEdit {{ background: {card_bg}; color: {tx}; border: 1px solid {bd};"
                f" border-radius: 6px; padding: 6px 8px; }}"
            ),
            "close_btn": (
                f"QPushButton {{ background: transparent; color: {hi}; border: none; border-radius: 14px; }}"
                f"QPushButton:hover {{ background: {sp}; color: {tx}; }}"
                f"QPushButton:pressed {{ background: {bd}; color: #000; }}"
            ),
            # 安全警告标签 — 主题感知（暗色模式下低饱和背景 + 柔和文字）
            "warn_label": (
                f"QLabel {{ color: {warn_fg}; background: {warn_bg};"
                f" border: 1px solid {warn_fg}; border-radius: 6px; padding: 8px 10px; }}"
            ),
            # 通用颜色快捷方式
            "sf": sf, "tx": tx, "hi": hi, "ac": ac, "sp": sp, "bd": bd,
            "card_bg": card_bg, "text_secondary": text_secondary,
        }

    def _font(self, size=12, bold=False):
        return QFont(self._cjk, size, QFont.Bold if bold else QFont.Normal)

    def _label(self, text, size=12, color=None, bold=False):
        if color is None:
            color = self._s["text_secondary"]
        w = QLabel(text)
        w.setFont(self._font(size, bold=bold))
        w.setStyleSheet(f"color: {color};")
        # 追踪所有 label 以便主题切换时更新颜色
        if not hasattr(self, '_labels'):
            self._labels = []
        self._labels.append(w)
        return w

    def _setup_ui(self):
        s = self._s
        self.setWindowTitle("浮窗设置")
        # 双列布局：窗口加宽，各模块并列放置，降低纵向高度
        self.setMinimumSize(800, 560)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFont(self._font(9))

        # 外层容器（模拟圆角边框）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        container = QWidget()
        container.setObjectName("settingsContainer")
        container.setStyleSheet(s["container"])
        self._container = container

        layout = QVBoxLayout(container)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 10, 20, 14)

        # ── 自定义标题栏 ──
        title_bar = QHBoxLayout()
        title_bar.setSpacing(0)

        # 标题 + 版本
        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        title_text = self._label("AgentFloat 设置", size=16, color=s["tx"])
        title_text.setFont(self._font(16, bold=True))
        title_block.addWidget(title_text)
        ver_text = self._label(f"v{VERSION}", size=9, color=s["hi"])
        title_block.addWidget(ver_text)
        title_bar.addLayout(title_block)

        title_bar.addStretch()

        # ✕ 关闭按钮
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setFont(self._font(14))
        close_btn.setStyleSheet(s["close_btn"])
        close_btn.clicked.connect(self.reject)
        self._close_btn = close_btn
        title_bar.addWidget(close_btn)

        layout.addLayout(title_bar)

        # 分隔线
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(s["separator"])
        self._sep = sep
        layout.addWidget(sep)

        # 通用按钮样式（使用主题缓存）
        btn_css = s["btn"]
        save_css = s["save_btn"]

        # ── 主内容区：左右两列，各模块并列放置 ──
        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # 主 Agent 启动
        box = QGroupBox("主 Agent 启动")
        box.setFont(self._font(13, bold=True))
        box.setStyleSheet(s["group"])
        vl = QVBoxLayout(box)
        vl.setSpacing(6)
        vl.setContentsMargins(14, 14, 14, 10)

        agent_row = QHBoxLayout()
        agent_row.setSpacing(6)
        self.cmb_primary_agent = QComboBox()
        self.cmb_primary_agent.setStyleSheet(s["combo"])
        self.cmb_primary_agent.currentIndexChanged.connect(self._on_primary_agent_changed)
        agent_row.addWidget(self.cmb_primary_agent, 1)
        self.btn_manage_agent = QPushButton("管理…")
        self.btn_manage_agent.setStyleSheet(btn_css)
        self.btn_manage_agent.clicked.connect(self._open_agent_manager)
        agent_row.addWidget(self.btn_manage_agent)
        vl.addLayout(agent_row)

        self.rb_normal = QRadioButton("普通模式", box)
        self.rb_skip  = QRadioButton("跳过权限", box)
        for rb in [self.rb_normal, self.rb_skip]:
            rb.setFont(self._font(11))
            rb.setStyleSheet(s["radio"])

        self.rb_normal.setToolTip(
            "以标准模式启动主 Agent（有敏感操作时弹出权限确认，安全可控）"
        )
        self.rb_skip.setToolTip(
            "跳过权限询问模式（追加该 Agent 配置的跳过权限参数）\n"
            "Agent 可自由执行终端命令、读写文件、访问网络，且不会弹出确认提示\n\n"
            "⚠ 存在数据丢失及安全风险，建议仅在完全受信任的项目中使用"
        )

        # "ℹ" 信息图标 — 悬停显示安全说明
        info_icon = QLabel(" ℹ")
        info_icon.setFont(self._font(11))
        info_icon.setStyleSheet(f"color: {s['ac']}; font-size: 13px;")
        info_icon.setToolTip(
            "「跳过权限」模式下，Agent 可以执行任意终端命令、"
            "读取和修改文件系统中的任何文件、访问网络资源，"
            "且以上操作均不会弹出权限确认提示。\n\n"
            "⚠ 可能导致数据丢失或安全风险，建议仅在完全受信任的项目中使用。"
        )

        mode = primary_launch_mode(self._agents)
        self.rb_normal.setChecked(mode != "skip_permissions")
        self.rb_skip.setChecked(mode == "skip_permissions")
        self._refresh_agent_combo()

        # 跳过权限行：radio + info 图标
        skip_row = QHBoxLayout()
        skip_row.setSpacing(6)
        skip_row.addWidget(self.rb_skip)
        skip_row.addWidget(info_icon)
        skip_row.addStretch()

        vl.addWidget(self.rb_normal)
        vl.addLayout(skip_row)

        # 安全警告标签容器（固定高度，避免显示/隐藏时布局跳动）
        warn_container = QWidget()
        warn_container.setMinimumHeight(40)
        warn_inner = QVBoxLayout(warn_container)
        warn_inner.setContentsMargins(0, 0, 0, 0)
        warn_inner.setSpacing(0)
        self.warn_label = QLabel(
            "⚠ 安全警告：此模式跳过所有权限检查，Agent 可自由\n"
            "执行命令、读写文件、访问网络。建议仅在受信任的项目中使用。"
        )
        self.warn_label.setFont(self._font(9, bold=True))
        self.warn_label.setStyleSheet(s["warn_label"])
        self.warn_label.setWordWrap(True)
        self.warn_label.setVisible(mode == "skip_permissions")
        warn_inner.addWidget(self.warn_label)
        self.rb_skip.toggled.connect(lambda checked: self.warn_label.setVisible(checked))

        vl.addWidget(warn_container)
        left_col.addWidget(box)

        # ── 外观主题 ──
        box_theme = QGroupBox("外观主题")
        box_theme.setFont(self._font(13, bold=True))
        box_theme.setStyleSheet(s["group"])
        vl_theme = QVBoxLayout(box_theme)
        vl_theme.setSpacing(6)
        vl_theme.setContentsMargins(14, 14, 14, 10)

        self.rb_light = QRadioButton("☀  浅色模式")
        self.rb_dark  = QRadioButton("☾  深色模式")
        for rb in [self.rb_light, self.rb_dark]:
            rb.setFont(self._font(11))
            rb.setStyleSheet(s["radio"])

        self.rb_light.setToolTip("亮色 iOS 风格毛玻璃外观，适合日间使用")
        self.rb_dark.setToolTip("暗色 iOS 风格毛玻璃外观，减少眼睛疲劳，适合夜间使用")

        self.rb_light.setChecked(self.theme != "dark")
        self.rb_dark.setChecked(self.theme == "dark")

        # 主题即时切换（仅响应选中，避免 radio group 双次信号）
        self.rb_light.toggled.connect(lambda checked: checked and self._live_switch_theme("light"))
        self.rb_dark.toggled.connect(lambda checked: checked and self._live_switch_theme("dark"))

        vl_theme.addWidget(self.rb_light)
        vl_theme.addWidget(self.rb_dark)
        left_col.addWidget(box_theme)

        # ── 边缘吸附 ──
        box_snap = QGroupBox("边缘吸附")
        box_snap.setFont(self._font(13, bold=True))
        box_snap.setStyleSheet(s["group"])
        vl_snap = QVBoxLayout(box_snap)
        vl_snap.setSpacing(6)
        vl_snap.setContentsMargins(14, 14, 14, 10)

        self.cb_snap_enabled = QCheckBox("启用边缘吸附")
        self.cb_snap_enabled.setFont(self._font(11))
        self.cb_snap_enabled.setStyleSheet(s["checkbox"])
        self.cb_snap_enabled.setChecked(self.config.get("snap_enabled", True))
        self.cb_snap_enabled.setToolTip("拖拽浮窗靠近屏幕边缘时自动吸附贴边，保持桌面整洁")
        vl_snap.addWidget(self.cb_snap_enabled)

        self.cb_snap_hidden = QCheckBox("自动隐藏")
        self.cb_snap_hidden.setFont(self._font(11))
        self.cb_snap_hidden.setStyleSheet(s["checkbox"])
        self.cb_snap_hidden.setChecked(self.config.get("snap_hidden", True))
        self.cb_snap_hidden.setToolTip("鼠标离开后浮窗自动滑出屏幕仅留边缘细条，鼠标靠近时滑回")
        self.cb_snap_hidden.setEnabled(self.cb_snap_enabled.isChecked())
        self.cb_snap_enabled.toggled.connect(lambda v: self.cb_snap_hidden.setEnabled(v))
        vl_snap.addWidget(self.cb_snap_hidden)
        left_col.addWidget(box_snap)

        # ── Skills 辅助 ──
        box_skills = QGroupBox("Skills 辅助")
        box_skills.setFont(self._font(13, bold=True))
        box_skills.setStyleSheet(s["group"])
        vsk = QVBoxLayout(box_skills)
        vsk.setSpacing(6)
        vsk.setContentsMargins(14, 14, 14, 10)

        self.skills_root_list = QListWidget()
        for r in (self._skills_cfg.get("roots") or default_skill_roots()):
            li = QListWidgetItem(os.path.basename(r) or r)
            li.setToolTip(r)
            self.skills_root_list.addItem(li)
        self.skills_root_list.setMaximumHeight(78)
        self.skills_root_list.setStyleSheet(s["list"])
        vsk.addWidget(self.skills_root_list)

        sk_row = QHBoxLayout()
        self.btn_skills_set = QPushButton("目录设置…")
        self.btn_skills_set.setStyleSheet(btn_css)
        self.btn_skills_set.clicked.connect(self._open_skills_settings)
        self.btn_skills_open = QPushButton("打开辅助窗")
        self.btn_skills_open.setStyleSheet(btn_css)
        self.btn_skills_open.clicked.connect(self._open_skills_panel)
        sk_row.addWidget(self.btn_skills_set)
        sk_row.addWidget(self.btn_skills_open)
        vsk.addLayout(sk_row)

        left_col.addWidget(box_skills)
        left_col.addStretch()

        # ── 浮窗大小 ──
        box2 = QGroupBox("浮窗大小")
        box2.setFont(self._font(13, bold=True))
        box2.setStyleSheet(s["group"])
        vl2 = QVBoxLayout(box2)
        vl2.setSpacing(6)
        vl2.setContentsMargins(14, 14, 14, 10)
        row = QHBoxLayout()
        row.addWidget(self._label("边长:", size=9))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(40, 90)
        self.size_slider.setValue(self.config.get("widget_size", DEFAULT_SIZE))
        self.size_slider.setStyleSheet(s["slider"])
        row.addWidget(self.size_slider)
        self.size_label = self._label(f"{self.size_slider.value()} px", bold=True)
        row.addWidget(self.size_label)
        self.size_slider.valueChanged.connect(lambda v: self.size_label.setText(f"{v} px"))
        vl2.addLayout(row)
        right_col.addWidget(box2)

        # ── 透明度 ──
        box3 = QGroupBox("透明度")
        box3.setFont(self._font(13, bold=True))
        box3.setStyleSheet(s["group"])
        vl3 = QVBoxLayout(box3)
        vl3.setSpacing(6)
        vl3.setContentsMargins(14, 14, 14, 10)
        row3 = QHBoxLayout()
        row3.addWidget(self._label("不透明度:", size=9))
        self.op_slider = QSlider(Qt.Horizontal)
        self.op_slider.setRange(40, 100)
        self.op_slider.setValue(int(self.config.get("opacity",0.88)*100))
        self.op_slider.setStyleSheet(s["slider"])
        row3.addWidget(self.op_slider)
        self.op_label = self._label(f"{self.op_slider.value()}%", bold=True)
        row3.addWidget(self.op_label)
        self.op_slider.valueChanged.connect(lambda v: self.op_label.setText(f"{v}%"))
        vl3.addLayout(row3)
        right_col.addWidget(box3)

        # ── 退出行为 ──
        box_cleanup = QGroupBox("退出行为")
        box_cleanup.setFont(self._font(13, bold=True))
        box_cleanup.setStyleSheet(s["group"])
        vl_cleanup = QVBoxLayout(box_cleanup)
        vl_cleanup.setSpacing(6)
        vl_cleanup.setContentsMargins(14, 14, 14, 10)

        self.cb_cleanup = QCheckBox("退出时关闭主 Agent 进程")
        self.cb_cleanup.setFont(self._font(11))
        self.cb_cleanup.setStyleSheet(s["checkbox"])
        self.cb_cleanup.setChecked(self.config.get("cleanup_on_quit", False))
        self.cb_cleanup.setToolTip("启用后，退出浮窗时将自动结束正在运行的主 Agent 进程")
        vl_cleanup.addWidget(self.cb_cleanup)
        right_col.addWidget(box_cleanup)

        # ── 默认启动目录 ──
        box4 = QGroupBox("默认启动目录")
        box4.setFont(self._font(13, bold=True))
        box4.setStyleSheet(s["group"])
        vl4 = QVBoxLayout(box4)
        vl4.setSpacing(8)
        vl4.setContentsMargins(14, 14, 14, 10)

        # 当前目录显示
        self.dir_edit = QLineEdit()
        self.dir_edit.setFont(self._font(10))
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setStyleSheet(s["lineedit"])
        wd = self.config.get("working_directory", "").strip()
        if not wd:
            wd = os.environ.get("USERPROFILE", "")
        self.dir_edit.setText(wd)
        self.dir_edit.setToolTip("Agent 将在此目录下启动。留空则使用用户主目录。")
        vl4.addWidget(self.dir_edit)

        # 浏览 + 重置按钮
        dir_btn_row = QHBoxLayout()
        dir_btn_row.setSpacing(8)

        browse_btn = QPushButton("浏览...")
        browse_btn.setStyleSheet(btn_css)
        browse_btn.clicked.connect(self._browse_folder)
        dir_btn_row.addWidget(browse_btn)

        reset_btn = QPushButton("重置为默认")
        reset_btn.setStyleSheet(btn_css)
        reset_btn.clicked.connect(self._reset_dir)
        dir_btn_row.addWidget(reset_btn)

        dir_btn_row.addStretch()
        vl4.addLayout(dir_btn_row)
        right_col.addWidget(box4)

        # ── 环绕菜单 ──
        box_radial = QGroupBox("环绕菜单")
        box_radial.setFont(self._font(13, bold=True))
        box_radial.setStyleSheet(s["group"])
        vr = QVBoxLayout(box_radial)
        vr.setSpacing(6)
        vr.setContentsMargins(14, 14, 14, 10)

        vr.addWidget(self._label("触发方式", size=11, color=s["text_secondary"]))
        self.cmb_trigger = QComboBox()
        self.cmb_trigger.addItem("悬停", "hover")
        self.cmb_trigger.addItem("长按", "long_press")
        self.cmb_trigger.addItem("双通道（悬停 + 长按）", "both")
        ti = self.cmb_trigger.findData(self._radial_cfg.get("trigger_mode", "both"))
        self.cmb_trigger.setCurrentIndex(max(0, ti))
        self.cmb_trigger.setStyleSheet(s["combo"])
        vr.addWidget(self.cmb_trigger)

        hover_row = QHBoxLayout()
        hover_row.addWidget(self._label("悬停延迟", size=11, color=s["text_secondary"]))
        self.spin_hover = QSpinBox()
        self.spin_hover.setRange(150, 2000)
        self.spin_hover.setSuffix(" ms")
        self.spin_hover.setValue(int(self._radial_cfg.get("hover_delay_ms", 400)))
        self.spin_hover.setStyleSheet(s["spin"])
        hover_row.addWidget(self.spin_hover, 1)
        vr.addLayout(hover_row)

        press_row = QHBoxLayout()
        press_row.addWidget(self._label("长按延迟", size=11, color=s["text_secondary"]))
        self.spin_press = QSpinBox()
        self.spin_press.setRange(200, 2000)
        self.spin_press.setSuffix(" ms")
        self.spin_press.setValue(int(self._radial_cfg.get("long_press_delay_ms", 500)))
        self.spin_press.setStyleSheet(s["spin"])
        press_row.addWidget(self.spin_press, 1)
        vr.addLayout(press_row)

        rad_row = QHBoxLayout()
        rad_row.addWidget(self._label("菜单半径", size=11, color=s["text_secondary"]))
        self.slider_radius = QSlider(Qt.Horizontal)
        self.slider_radius.setRange(90, 170)
        self.slider_radius.setValue(int(self._radial_cfg.get("radius", 120)))
        self.slider_radius.setStyleSheet(s["slider"])
        rad_row.addWidget(self.slider_radius, 1)
        self.lbl_radius = self._label("%dpx" % self.slider_radius.value(), size=9, color=s["hi"])
        rad_row.addWidget(self.lbl_radius)
        self.slider_radius.valueChanged.connect(lambda v: self.lbl_radius.setText("%dpx" % v))
        vr.addLayout(rad_row)

        right_col.addWidget(box_radial)
        right_col.addStretch()

        main_row.addLayout(left_col, 1)
        main_row.addLayout(right_col, 1)
        layout.addLayout(main_row)

        # ── API 用量监控设置 ──
        api_config = self.config.get("api_monitor", API_MONITOR_DEFAULTS)
        self._api_monitor_tab = ApiMonitorSettingsTab(api_config, theme=self.theme)
        self._api_monitor_tab.config_changed.connect(self._on_api_config_changed)
        # 放入滚动区域
        api_scroll = QScrollArea()
        api_scroll.setWidgetResizable(True)
        api_scroll.setWidget(self._api_monitor_tab)
        api_scroll.setMaximumHeight(200)
        self._api_scroll = api_scroll
        api_scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {s['bd']}; border-radius: 10px; background: {s['card_bg']}; }}"
            f"QScrollBar:vertical {{ width: 6px; }}"
        )
        layout.addWidget(api_scroll)

        # 按钮
        bl = QHBoxLayout()
        bl.setSpacing(10)

        preview_btn = QPushButton("应用")
        preview_btn.setStyleSheet(btn_css)
        preview_btn.clicked.connect(self._preview)
        bl.addWidget(preview_btn)

        bl.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(btn_css)
        cancel_btn.clicked.connect(self.reject)
        bl.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(save_css)
        save_btn.clicked.connect(self._save)
        bl.addWidget(save_btn)
        layout.addLayout(bl)

        # 日志文件路径提示
        log_hint = self._label(
            f"日志文件: %APPDATA%\\AgentFloat\\logs\\AgentFloat.log", size=9, color=s["hi"]
        )
        layout.addWidget(log_hint)

        # ── 存储控件引用，用于即时换肤 ──
        self._tw = {
            'container': container,
            'groups': [box, box_theme, box2, box3, box_snap, box4, box_cleanup, box_radial, box_skills],
            'radios': [self.rb_normal, self.rb_skip, self.rb_light, self.rb_dark],
            'checkboxes': [self.cb_snap_enabled, self.cb_snap_hidden, self.cb_cleanup],
            'buttons': [preview_btn, cancel_btn, browse_btn, reset_btn, self.btn_manage_agent, self.btn_skills_set, self.btn_skills_open],
            'save_btn': save_btn,
            'close_btn': close_btn,
            'api_scroll': api_scroll,
            'sliders': [self.size_slider, self.op_slider, self.slider_radius],
            'lineedits': [self.dir_edit],
            'sep': sep,
            'title_text': title_text,
            'ver_text': ver_text,
            'log_hint': log_hint,
            'info_icon': info_icon,
        }

        outer.addWidget(container)

        # ── 窗口尺寸：仅设最小，不设最大，避免与 Windows 布局引擎冲突 ──
        # （无边框窗口用户无法调整大小，不设 setFixedSize 不会导致问题）
        outer.activate()
        content_w = outer.sizeHint().width() + 24
        content_h = outer.sizeHint().height() + 40
        content_h = max(content_h, 620)
        self.resize(max(content_w, 840), content_h)
        _log().debug("[设置] 布局计算: %dx%d (sizeHint=%dx%d)", content_w, content_h,
                     outer.sizeHint().width(), outer.sizeHint().height())

        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - content_h) // 2)

    # ── 无边框窗口拖拽支持 ──
    CLICK_THRESHOLD = 4

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPos()
            self._window_origin = self.pos()
            self._dragging = False
            _log().debug("[设置] mousePress: global=%s window_origin=%s", self._drag_start, self._window_origin)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        delta = (event.globalPos() - self._drag_start).manhattanLength()
        if not self._dragging and delta > self.CLICK_THRESHOLD:
            self._dragging = True
            _log().debug("[设置] drag start: delta=%d", delta)
        if self._dragging:
            new_pos = self._window_origin + (event.globalPos() - self._drag_start)
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_dragging = self._dragging
            self._dragging = False
            _log().debug("[设置] mouseRelease: was_dragging=%s pos=%s", was_dragging, self.pos())

    # ── 即时主题切换 ──
    def _live_switch_theme(self, theme):
        """即时切换对话框及背后浮窗的主题，不关闭对话框"""
        if theme == self.theme:
            return
        self.theme = theme
        self._c = get_colors(theme)
        self._build_styles()
        self._reapply_dialog_styles()

        # 同步 radio 按钮状态（blockSignals 防止 toggled 信号递归触发）
        self.rb_light.blockSignals(True)
        self.rb_dark.blockSignals(True)
        self.rb_light.setChecked(theme == "light")
        self.rb_dark.setChecked(theme == "dark")
        self.rb_light.blockSignals(False)
        self.rb_dark.blockSignals(False)

        # 同步更新背后浮窗
        p = self.parent()
        if p and hasattr(p, 'rebuild_theme'):
            p.rebuild_theme(theme)

    def _reapply_dialog_styles(self):
        """重新应用所有控件样式（主题切换后调用）"""
        s = self._s
        tw = self._tw

        tw['container'].setStyleSheet(s['container'])
        for g in tw['groups']:
            g.setStyleSheet(s['group'])
        for r in tw['radios']:
            r.setStyleSheet(s['radio'])
        for c in tw['checkboxes']:
            c.setStyleSheet(s['checkbox'])
        for b in tw['buttons']:
            b.setStyleSheet(s['btn'])
        tw['save_btn'].setStyleSheet(s['save_btn'])
        tw['close_btn'].setStyleSheet(s['close_btn'])
        for sl in tw['sliders']:
            sl.setStyleSheet(s['slider'])
        for le in tw['lineedits']:
            le.setStyleSheet(s['lineedit'])
        tw['sep'].setStyleSheet(s['separator'])

        # Label 颜色更新 — 所有通过 _label() 创建的标签
        for lbl in getattr(self, '_labels', []):
            lbl.setStyleSheet(f"color: {s['text_secondary']};")
        tw['title_text'].setStyleSheet(f"color: {s['tx']};")
        tw['ver_text'].setStyleSheet(f"color: {s['hi']};")
        tw['log_hint'].setStyleSheet(f"color: {s['hi']};")
        tw['info_icon'].setStyleSheet(f"color: {s['ac']}; font-size: 13px;")

        # warn_label 主题感知样式更新
        if hasattr(self, 'warn_label'):
            self.warn_label.setStyleSheet(s['warn_label'])

        # API 滚动区边框主题同步
        if hasattr(self, '_api_scroll'):
            self._api_scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {s['bd']}; border-radius: 10px;"
                f" background: {s['card_bg']}; }}"
                f"QScrollBar:vertical {{ width: 6px; }}"
            )

        # API 监控页主题同步
        if hasattr(self, '_api_monitor_tab'):
            self._api_monitor_tab.set_theme(self.theme)

        # 新增模块控件主题同步
        if hasattr(self, 'cmb_primary_agent'):
            self.cmb_primary_agent.setStyleSheet(s['combo'])
            self.cmb_trigger.setStyleSheet(s['combo'])
            self.spin_hover.setStyleSheet(s['spin'])
            self.spin_press.setStyleSheet(s['spin'])
            self.slider_radius.setStyleSheet(s['slider'])
            self.skills_root_list.setStyleSheet(s['list'])

    def reject(self):
        """取消时还原原始主题"""
        if self.theme != self._original_theme:
            self._live_switch_theme(self._original_theme)
        super().reject()

    def _collect(self):
        # 主 Agent 启动模式同步到 Agent 记录
        mode = "skip_permissions" if self.rb_skip.isChecked() else "normal"
        for a in self._agents:
            if a.get("id") == self._primary_agent_id:
                a["launch_mode"] = mode
        radial = {
            "enabled": True,
            "trigger_mode": self.cmb_trigger.currentData(),
            "hover_delay_ms": self.spin_hover.value(),
            "long_press_delay_ms": self.spin_press.value(),
            "radius": self.slider_radius.value(),
        }
        return {
            "launch_mode": mode,
            "agents": copy.deepcopy(self._agents),
            "primary_agent_id": self._primary_agent_id,
            "radial_menu": radial,
            "skills": copy.deepcopy(self._skills_cfg),
            "widget_size": self.size_slider.value(),
            "opacity": self.op_slider.value() / 100.0,
            "working_directory": self.dir_edit.text().strip(),
            "snap_enabled": self.cb_snap_enabled.isChecked(),
            "snap_hidden": self.cb_snap_hidden.isChecked(),
            "theme": "dark" if self.rb_dark.isChecked() else "light",
            "cleanup_on_quit": self.cb_cleanup.isChecked(),
            "api_monitor": getattr(self, "_api_config", self.config.get("api_monitor", API_MONITOR_DEFAULTS)),
        }
    def _on_api_config_changed(self, config):
        """API 监控配置实时变更回调"""
        self._api_config = config

    def _refresh_agent_combo(self):
        self.cmb_primary_agent.blockSignals(True)
        self.cmb_primary_agent.clear()
        for a in self._agents:
            self.cmb_primary_agent.addItem(a.get("name"), a.get("id"))
        idx = self.cmb_primary_agent.findData(self._primary_agent_id)
        self.cmb_primary_agent.setCurrentIndex(max(0, idx))
        self.cmb_primary_agent.blockSignals(False)
        self._on_primary_agent_changed()

    def _on_primary_agent_changed(self):
        aid = self.cmb_primary_agent.currentData()
        if aid:
            self._primary_agent_id = aid
        mode = primary_launch_mode(self._agents)
        self.rb_normal.setChecked(mode != "skip_permissions")
        self.rb_skip.setChecked(mode == "skip_permissions")

    def _open_agent_manager(self):
        dlg = AgentManagerDialog(self._agents, theme=self.theme, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._agents = dlg.agents
            self._primary_agent_id = (get_primary_agent(self._agents) or {}).get("id")
            self._refresh_agent_combo()

    def _open_skills_settings(self):
        dlg = SkillsSettingsDialog(self._skills_cfg, theme=self.theme, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._skills_cfg = dlg.config
            self.skills_root_list.clear()
            for r in (self._skills_cfg.get("roots") or default_skill_roots()):
                li = QListWidgetItem(os.path.basename(r) or r)
                li.setToolTip(r)
                self.skills_root_list.addItem(li)

    def _open_skills_panel(self):
        dlg = SkillsPanel(self._skills_cfg, theme=self.theme, parent=self)
        dlg.exec_()

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择默认工作目录",
            self.dir_edit.text() or os.environ.get("USERPROFILE", ""),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if folder:
            self.dir_edit.setText(folder)
    def _reset_dir(self):
        self.dir_edit.setText(os.environ.get("USERPROFILE", ""))
    def _preview(self):
        self.result_config = self._collect()
        self.result_config["_preview"] = True
        self.accept()
    def _save(self):
        # 如果选中跳过权限模式，弹出安全确认
        if self.rb_skip.isChecked():
            reply = QMessageBox.warning(
                self, "安全确认 — 跳过权限模式",
                "您正在启用「跳过权限」模式。\n\n"
                "在此模式下，Agent 可以：\n"
                "• 执行任意终端命令\n"
                "• 读取和修改文件系统中的任何文件\n"
                "• 访问网络资源\n"
                "• 以上操作均不会弹出权限确认提示\n\n"
                "这可能导致数据丢失或安全风险。\n"
                "建议仅在完全受信任的项目中使用。\n\n"
                "确定要启用此模式吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self.result_config = self._collect()
        self.result_config["_preview"] = False
        self.accept()

# ── 浮窗主体 ──────────────────────────────────────────
class FloatingWidget(QWidget):
    launch_requested  = pyqtSignal()
    quit_requested    = pyqtSignal()
    settings_requested = pyqtSignal()
    theme_changed     = pyqtSignal(str)

    CLICK_THRESHOLD = 4

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.theme = self.config.get("theme", "light")
        _log().info("浮窗初始化: size=%s, opacity=%.2f, theme=%s",
                     self.config.get("widget_size", DEFAULT_SIZE),
                     self.config.get("opacity", 0.88),
                     self.theme)
        self.is_hovered = False
        self.is_pressed = False
        self.base_size = self.config.get("widget_size", DEFAULT_SIZE)
        self.current_size = self.base_size
        self.icon_pixmap = None

        # ── 多 Agent / 环绕菜单 ──
        self._agents = normalize_agents(self.config.get("agents"))
        self._radial_cfg = copy.deepcopy(self.config.get("radial_menu") or DEFAULT_RADIAL_MENU)
        self._skills_cfg = copy.deepcopy(self.config.get("skills") or DEFAULT_SKILLS)
        self._radial_menu = None
        self._long_press_fired = False
        self._api_last_results = []

        # 拖拽状态
        self._drag_active = False
        self._drag_origin = QPoint()
        self._window_origin = QPoint()

        # 按压缩放 (0.0 ~ 1.0，1.0 = 正常)
        self._press_scale = 1.0
        # 涟漪 (0.0 ~ 1.0)
        self._ripple_progress = 0.0
        self._ripple_pos = QPoint()
        self._ripple_timer = QTimer(self)
        self._ripple_timer.setInterval(16)
        self._ripple_timer.timeout.connect(self._tick_ripple)

        # 吸附状态
        self._snapped = False
        self._snap_edge = ""
        self._visible_offset = 0  # 完全显示时的屏幕坐标
        self._hidden_offset = 0   # 隐藏时的偏移
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._auto_hide)
        # 边缘检测条（透明窗口，用于检测鼠标靠近屏幕边缘）
        self._edge_detector = None

        # Claude 进程检测（绿色指示灯）
        self._claude_running = False
        self._proc_timer = QTimer(self)
        self._proc_timer.setInterval(3000)  # 每 3 秒检测一次
        self._proc_timer.timeout.connect(self._check_claude_process)
        self._proc_timer.start()

        # API 余额角标（极简独立小窗，跟随浮窗）
        self._api_badge = None
        self._api_worker = None
        self._init_api_monitor()

        # 预缓存绘制资源
        self._cache = {}

        self._load_icon()
        self._setup_ui()
        self._apply_opacity()
        self._restore_position()
        self._build_paint_cache()

    def _load_icon(self):
        for p in (PNG_PATH, ICO_PATH):
            pix = QPixmap(p)
            if not pix.isNull():
                self.icon_pixmap = pix
                return
        self.icon_pixmap = None

    def _build_paint_cache(self, theme=None):
        """预构建所有渐变和路径对象（避免每帧重复创建）"""
        if theme is None:
            theme = self.theme
        c = get_colors(theme)
        gb = c["GLASS_BG"]
        bd = c["BORDER"]

        s = self.current_size
        r = CORNER_RADIUS
        cx, cy = s / 2, s / 2

        # 基底路径
        base = QPainterPath()
        base.addRoundedRect(QRectF(0, 0, s, s), r, r)
        self._cache["base"] = base

        # 7 个渐变 — 亮色/暗色共享结构，仅颜色值不同
        is_dark = (theme == "dark")

        radial = QRadialGradient(cx, cy, s * 0.7)
        radial.setColorAt(0.0, QColor(255, 255, 255, 10 if is_dark else 18))
        radial.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._cache["radial"] = radial

        diag = QLinearGradient(0, 0, s, s)
        if is_dark:
            diag.setColorAt(0.0, QColor(*gb, 220))
            diag.setColorAt(0.35, QColor(*gb, 210))
            diag.setColorAt(0.65, QColor(gb[0]+4, gb[1]+4, gb[2]+6, 200))
            diag.setColorAt(1.0, QColor(gb[0]-2, gb[1]-2, gb[2]+0, 190))
        else:
            diag.setColorAt(0.0, QColor(*gb, 240))
            diag.setColorAt(0.35, QColor(*gb, 228))
            diag.setColorAt(0.65, QColor(245, 244, 249, 218))
            diag.setColorAt(1.0, QColor(238, 237, 242, 205))
        self._cache["diag"] = diag

        # 玻璃边框渐变（垂直）
        border = QLinearGradient(0, 0, 0, s)
        border.setColorAt(0.0, QColor(*bd, 190))
        border.setColorAt(0.45, QColor(*bd, 110))
        border.setColorAt(1.0, QColor(*bd, 55))
        self._cache["border"] = border

        # 顶面柔光渐变 — 暗色下降低 alpha
        hl_alpha_top = 60 if is_dark else 125
        hl_alpha_mid = 20 if is_dark else 45
        hl = QLinearGradient(0, 0, 0, s * 0.58)
        hl.setColorAt(0.0, QColor(255, 255, 255, hl_alpha_top))
        hl.setColorAt(0.45, QColor(255, 255, 255, hl_alpha_mid))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._cache["hl"] = hl

        # 内阴影渐变
        inner = QRadialGradient(cx + s * 0.15, cy + s * 0.15, s * 0.75)
        inner.setColorAt(0.0, QColor(0, 0, 0, 0))
        inner.setColorAt(0.6, QColor(0, 0, 0, 0))
        inner.setColorAt(0.9, QColor(0, 0, 0, 12 if is_dark else 8))
        inner.setColorAt(1.0, QColor(0, 0, 0, 30 if is_dark else 20))
        self._cache["inner"] = inner

        # 镜面反光渐变 — 暗色下降低 alpha
        spec_alpha_0 = 55 if is_dark else 100
        spec_alpha_1 = 30 if is_dark else 55
        spec_alpha_2 = 5 if is_dark else 10
        spec_r = s * 0.18
        spec = QRadialGradient(s * 0.28, s * 0.25, spec_r * 1.5)
        spec.setColorAt(0.0, QColor(255, 255, 255, spec_alpha_0))
        spec.setColorAt(0.25, QColor(255, 255, 255, spec_alpha_1))
        spec.setColorAt(0.6, QColor(255, 255, 255, spec_alpha_2))
        spec.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._cache["spec"] = spec

        # 图标缓存
        icon_frac = 0.52
        icon_size = int(s * icon_frac)
        if self.icon_pixmap and not self.icon_pixmap.isNull():
            self._cache["icon"] = self.icon_pixmap.scaled(
                icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._cache["icon_x"] = int((s - icon_size) / 2)
            self._cache["icon_y"] = int((s - icon_size) / 2)
        else:
            self._cache["icon"] = None

    def _check_claude_process(self):
        """检测主 Agent 进程是否在运行，更新指示灯状态"""
        try:
            primary = get_primary_agent(self._agents)
            cmd = (primary or {}).get("command", "")
            base = os.path.basename(cmd) if cmd else ""
            if not base:
                self._claude_running = False
                return
            if not base.lower().endswith(".exe"):
                base += ".exe"
            result = subprocess.run(
                ["tasklist", "/fi", "imagename eq %s" % base, "/nh"],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            was_running = self._claude_running
            self._claude_running = base.lower() in result.stdout.lower()
            if was_running != self._claude_running:
                _log().debug("Agent 进程状态变化: running=%s", self._claude_running)
                self.update()  # 状态变化时重绘
        except Exception:
            self._claude_running = False

    # ── API 用量监控 ─────────────────────────────
    def _init_api_monitor(self):
        """初始化余额角标和轮询线程（先建角标再连信号，避免竞态）"""
        am_config = self.config.get("api_monitor", API_MONITOR_DEFAULTS)
        if not am_config.get("enabled") or not am_config.get("endpoints"):
            return

        self._api_badge = ApiBalanceBadge(parent_float=self)
        self._api_badge.set_theme(self.theme)
        self._api_badge.set_warn_threshold(am_config.get("low_balance_warn", 5.0))
        self._api_badge.update_balance("…")
        if self.isVisible():
            self._api_badge.show()

        self._api_worker = ApiMonitorWorker(
            endpoints=am_config.get("endpoints", []),
            interval_seconds=am_config.get("poll_interval_seconds", 60),
        )
        self._api_worker.data_ready.connect(self._on_api_data_ready)
        self._api_worker.start()
        _log().info("API 用量监控已启动: %d 端点", len(am_config.get("endpoints", [])))

    def _stop_api_monitor(self):
        """停止 API 用量监控"""
        if self._api_worker and self._api_worker.isRunning():
            self._api_worker.stop()
            self._api_worker.wait(2000)
        if self._api_badge:
            self._api_badge.hide()
            self._api_badge.deleteLater()
            self._api_badge = None
        self._api_worker = None
        _log().info("API 用量监控已停止")

    def _restart_api_monitor(self):
        """重启 API 用量监控（配置变更后调用）"""
        self._stop_api_monitor()
        self._init_api_monitor()

    def _on_api_data_ready(self, results):
        """轮询数据就绪，更新余额角标（只显示剩余额度）"""
        self._api_last_results = results or []
        if not results or not self._api_badge:
            return
        r = results[0]
        if not r.fields:
            return

        # worker 请求失败时产生错误伪字段
        first = r.fields[0]
        if first.get("label") == "错误":
            self._api_badge.update_balance("查询失败", is_error=True)
            return

        # 优先按标签匹配剩余额度，否则取第一个字段
        field = next((f for f in r.fields if f.get("label") == "剩余额度"), first)
        val, unit = field.get("value"), field.get("unit", "")
        if val is None:
            _log().warning("[API] 字段 ""%s"" 返回 None，原始响应前200字符: %s",
                           field.get("label", "?"), r.raw_response[:200])
            self._api_badge.update_balance("N/A", is_error=True)
            return
        try:
            num = float(val)
            text = f"{num:.2f}{unit}"
        except (TypeError, ValueError):
            _log().warning("[API] 字段 ""%s"" 值无法转为数字: %s", field.get("label", "?"), val)
            self._api_badge.update_balance(str(val)[:20] + (unit if unit else ""), num=None)
            return
        self._api_badge.update_balance(text, num)

    def _sync_api_panel_position(self):
        """同步余额角标位置"""
        if self._api_badge:
            self._api_badge.sync_position()

    def _setup_ui(self):
        s = self.current_size
        self.setFixedSize(s, s)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._update_mask()

        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(100)
        self._hover_timer.timeout.connect(self._check_hover)
        self._hover_timer.start()

        # 环绕菜单触发定时器（悬停 / 长按双通道）
        self._hover_open_timer = QTimer(self)
        self._hover_open_timer.setSingleShot(True)
        self._hover_open_timer.timeout.connect(lambda: self._open_radial_menu("hover"))
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(lambda: self._open_radial_menu("long_press"))

        # 尺寸动画
        self._size_anim = QPropertyAnimation(self, b"widget_size_prop")
        self._size_anim.setDuration(200)
        self._size_anim.setEasingCurve(QEasingCurve.OutCubic)

        # 按压动画
        self._press_anim = QPropertyAnimation(self, b"press_scale")
        self._press_anim.setDuration(100)
        self._press_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._press_anim.finished.connect(self._on_press_anim_done)

        # 全局快捷键
        self._hotkey_id = 1
        self._hotkey_registered = False
        self._register_hotkey()

    # ── 全局快捷键 ────────────────────────────────
    def _register_hotkey(self):
        """注册 Ctrl+Alt+C 全局快捷键"""
        if self._hotkey_registered:
            return
        try:
            MOD_ALT = 0x0001
            MOD_CONTROL = 0x0002
            VK_C = 0x43
            result = ctypes.windll.user32.RegisterHotKey(
                int(self.winId()), self._hotkey_id, MOD_CONTROL | MOD_ALT, VK_C
            )
            self._hotkey_registered = (result != 0)
            if self._hotkey_registered:
                _log().debug("全局快捷键 Ctrl+Alt+C 注册成功")
            else:
                _log().warning("全局快捷键注册失败（可能被其他程序占用）")
        except Exception:
            self._hotkey_registered = False
            _log().warning("全局快捷键注册异常")

    def _unregister_hotkey(self):
        """注销全局快捷键"""
        if self._hotkey_registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), self._hotkey_id)
            except Exception:
                pass
            self._hotkey_registered = False

    def nativeEvent(self, eventType, message):
        """处理 Windows 原生消息（WM_HOTKEY）"""
        WM_HOTKEY = 0x0312
        if eventType == "windows_generic_MSG":
            # message 是 sip.voidptr，需要用 ctypes 解析 MSG 结构体
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt", POINT),
                ]
            msg = MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                if self.isVisible():
                    self.hide()
                else:
                    self.show()
                return True, 0
        return super().nativeEvent(eventType, message)

    def showEvent(self, event):
        """显示时启动 hover 检测"""
        super().showEvent(event)
        _log().debug("浮窗显示")
        if not self._hover_timer.isActive():
            self._hover_timer.start()
        # 同步余额角标
        self._sync_api_panel_position()
        if self._api_badge:
            self._api_badge.show()

    def moveEvent(self, event):
        """移动时同步余额角标位置"""
        super().moveEvent(event)
        self._sync_api_panel_position()

    def hideEvent(self, event):
        """隐藏时停止 hover 检测以节省 CPU"""
        super().hideEvent(event)
        _log().debug("浮窗隐藏")
        self._hover_timer.stop()
        self._hover_open_timer.stop()
        self._long_press_timer.stop()
        self._close_radial_menu()
        # 重置 hover 状态
        if self.is_hovered:
            self.is_hovered = False
            self._animate_size(self.base_size)
        if self._api_badge:
            self._api_badge.hide()

    # ── 按压 + 涟漪属性 ────────────────────────────
    def _tick_ripple(self):
        self._ripple_progress += 0.04
        if self._ripple_progress >= 1.0:
            self._ripple_progress = 0.0
            self._ripple_timer.stop()
        self.update()

    @pyqtProperty(float)
    def press_scale(self):
        return self._press_scale

    @press_scale.setter
    def press_scale(self, v):
        self._press_scale = v
        self.update()

    def _on_press_anim_done(self):
        self._press_anim.stop()
        self._press_anim.setDuration(300)
        self._press_anim.setEasingCurve(QEasingCurve.OutBack)
        self._press_anim.setStartValue(self._press_scale)
        self._press_anim.setEndValue(1.0)
        self._press_anim.start()

    def _apply_opacity(self):
        self.setWindowOpacity(max(0.3, min(1.0, self.config.get("opacity", 0.88))))

    def rebuild_theme(self, theme):
        """切换主题：更新配色缓存 → 重建绘制资源 → 重绘"""
        self.theme = theme
        self.config["theme"] = theme
        self._build_paint_cache(theme=theme)
        self.update()
        self.theme_changed.emit(theme)
        # 同步余额角标主题
        if self._api_badge:
            self._api_badge.set_theme(theme)
        _log().info("主题切换为: %s", theme)

    def _update_mask(self):
        s = self.current_size
        r = CORNER_RADIUS
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, s, s), r, r)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

    def _animate_size(self, target):
        if self.current_size == target: return
        self._size_anim.stop()
        self._size_anim.setStartValue(self.current_size)
        self._size_anim.setEndValue(target)
        self._size_anim.start()

    @pyqtProperty(int)
    def widget_size_prop(self):
        return self.current_size

    @widget_size_prop.setter
    def widget_size_prop(self, v):
        if v == self.current_size:
            return
        self.current_size = v
        c = self.geometry().center()
        self.setFixedSize(v, v)
        self._update_mask()
        self._build_paint_cache()
        ng = self.frameGeometry()
        ng.moveCenter(c)
        self.move(ng.topLeft())

    def _restore_position(self):
        x, y = self.config.get("window_x", -1), self.config.get("window_y", -1)
        if x < 0 or y < 0:
            screen = QApplication.primaryScreen()
            if screen:
                g = screen.availableGeometry()
                x = g.right() - 80
                y = (g.top() + g.bottom()) // 2 - self.current_size // 2

        edge = self.config.get("snap_edge", "right")
        # 如果启用了吸附，调整到正确位置
        if self.config.get("snap_enabled", True):
            screen = self._screen_geometry()
            if edge == "right":
                x = screen.right() - self.current_size - 2
            elif edge == "left":
                x = screen.left() + 2
            elif edge == "top":
                y = screen.top() + 2
            elif edge == "bottom":
                y = screen.bottom() - self.current_size - 2

        self.move(x, y)
        self._visible_offset = self.pos().x() if edge in ("left", "right") else self.pos().y()

        # 如果吸附 + 自动隐藏，初始化隐藏状态
        if self.config.get("snap_enabled", True) and self.config.get("snap_hidden", True):
            self._snapped = True
            self._snap_edge = edge
            self._setup_edge_detector()
            self._do_hide()

    # ── 边缘吸附系统 ────────────────────────────────
    def _screen_geometry(self):
        """获取当前屏幕的工作区域"""
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen:
            return screen.availableGeometry()
        return QRect(0, 0, 1920, 1080)

    def _check_snap(self):
        """检测拖拽后是否应吸附到屏幕边缘"""
        if not self.config.get("snap_enabled", True):
            return

        SNAP_THRESHOLD = 25
        g = self._screen_geometry()
        cx = self.pos().x() + self.current_size // 2
        cy = self.pos().y() + self.current_size // 2

        # 检测距离每个边缘的距离
        dist_left = cx - g.left()
        dist_right = g.right() - cx
        dist_top = cy - g.top()
        dist_bottom = g.bottom() - cy

        nearest = min(
            (dist_left, "left"), (dist_right, "right"),
            (dist_top, "top"), (dist_bottom, "bottom"), key=lambda d: d[0]
        )

        if nearest[0] < SNAP_THRESHOLD + self.current_size // 2:
            edge = nearest[1]
            self._snapped = True
            self._snap_edge = edge
            self.config["snap_edge"] = edge

            # 吸附到边缘
            if edge == "left":
                new_x = g.left() + 2
                new_y = max(g.top(), min(g.bottom() - self.current_size, self.pos().y()))
            elif edge == "right":
                new_x = g.right() - self.current_size - 2
                new_y = max(g.top(), min(g.bottom() - self.current_size, self.pos().y()))
            elif edge == "top":
                new_x = max(g.left(), min(g.right() - self.current_size, self.pos().x()))
                new_y = g.top() + 2
            else:  # bottom
                new_x = max(g.left(), min(g.right() - self.current_size, self.pos().x()))
                new_y = g.bottom() - self.current_size - 2

            self.move(new_x, new_y)
            self._visible_offset = new_x if edge in ("left", "right") else new_y
            save_config(self.config)

            # 自动隐藏
            if self.config.get("snap_hidden", True):
                self._setup_edge_detector()
                self._hide_timer.start(600)
        else:
            self._snapped = False
            self._snap_edge = ""
            self._remove_edge_detector()
            self.config["snap_edge"] = ""
            _log().debug("脱离吸附")
            save_config(self.config)

    def _setup_edge_detector(self):
        """创建屏幕边缘的透明检测窗口"""
        self._remove_edge_detector()
        g = self._screen_geometry()
        edge = self._snap_edge
        sz = self.current_size

        # 必须子类化才能正确重写 C++ 虚函数 enterEvent
        parent_widget = self

        class HoverDetector(QWidget):
            def enterEvent(self_2, event):
                parent_widget._on_edge_detected()

        detector = HoverDetector()
        detector.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        detector.setAttribute(Qt.WA_TranslucentBackground)
        detector.setAttribute(Qt.WA_ShowWithoutActivating)
        detector.setStyleSheet("background: transparent;")
        detector.setMouseTracking(True)

        # 检测条：沿屏幕边缘 3px 宽的细条
        if edge == "right":
            detector.setGeometry(g.right() - 3, self.pos().y() - 5, 3, sz + 10)
        elif edge == "left":
            detector.setGeometry(g.left(), self.pos().y() - 5, 3, sz + 10)
        elif edge == "top":
            detector.setGeometry(self.pos().x() - 5, g.top(), sz + 10, 3)
        else:  # bottom
            detector.setGeometry(self.pos().x() - 5, g.bottom() - 3, sz + 10, 3)

        detector.show()
        self._edge_detector = detector

    def _remove_edge_detector(self):
        if self._edge_detector:
            try:
                self._edge_detector.close()
                self._edge_detector.deleteLater()
            except Exception:
                pass
            self._edge_detector = None

    def _on_edge_detected(self):
        """鼠标靠近隐藏的吸附边缘，滑出显示"""
        self._hide_timer.stop()
        if self._snapped:
            self._show_full()

    def _do_hide(self):
        """将 widget 滑出屏幕（仅留一小部分可见）"""
        if not self._snapped:
            return
        g = self._screen_geometry()
        s = self.current_size
        edge = self._snap_edge
        visible_tab = 6  # 留在屏幕内的像素

        if edge == "right":
            target = g.right() - visible_tab
        elif edge == "left":
            target = g.left() - s + visible_tab
        elif edge == "top":
            target = g.top() - s + visible_tab
        else:  # bottom
            target = g.bottom() - visible_tab

        self._hidden_offset = target
        self._animate_slide(target, edge)
        if self._api_badge:
            self._api_badge.hide()

    def _show_full(self):
        """将 widget 完全滑入屏幕"""
        if not self._snapped:
            return
        g = self._screen_geometry()
        s = self.current_size
        edge = self._snap_edge

        if edge == "right":
            target = g.right() - s - 2
        elif edge == "left":
            target = g.left() + 2
        elif edge == "top":
            target = g.top() + 2
        else:
            target = g.bottom() - s - 2

        self._animate_slide(target, edge)
        if self._api_badge:
            self._api_badge.show()
        # 设置延迟重新隐藏
        self._hide_timer.start(self.config.get("hide_delay_ms", 800))

    def _auto_hide(self):
        """计时器触发：自动隐藏"""
        if self._snapped and not self.is_hovered:
            self._do_hide()

    def _animate_slide(self, target, edge):
        """滑动动画"""
        anim = QPropertyAnimation(self, b"slide_pos")
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.setStartValue(self.pos().x() if edge in ("left", "right") else self.pos().y())
        anim.setEndValue(target)
        anim.start()
        # 保持引用防止被垃圾回收
        self._slide_anim = anim

    @pyqtProperty(int)
    def slide_pos(self):
        return self.pos().x() if self._snap_edge in ("left", "right") else self.pos().y()

    @slide_pos.setter
    def slide_pos(self, v):
        if self._snap_edge == "left" or self._snap_edge == "right":
            self.move(int(v), self.pos().y())
        elif self._snap_edge in ("top", "bottom"):
            self.move(self.pos().x(), int(v))

    def _check_hover(self):
        # 用 mapFromGlobal 替代 frameGeometry().contains() —
        # WA_ShowWithoutActivating 下 frameGeometry 坐标可能偏移
        local_pos = self.mapFromGlobal(QCursor.pos())
        was = self.is_hovered
        self.is_hovered = self.rect().contains(local_pos)

        # 吸附模式下自动管理显示/隐藏
        if self._snapped and self.config.get("snap_hidden", True):
            if self.is_hovered and not was:
                self._show_full()
            elif not self.is_hovered and was:
                self._hide_timer.start(self.config.get("hide_delay_ms", 800))

        hover_size = int(self.base_size * HOVER_SCALE)
        if self.is_hovered and not was:
            self._animate_size(hover_size)
            self._maybe_start_hover_open()
        elif not self.is_hovered and was:
            self._animate_size(self.base_size)
            self._hover_open_timer.stop()
            self._close_radial_menu()

    # ── 环绕菜单（悬停 / 长按双通道）──────────────────
    def _maybe_start_hover_open(self):
        if not self._radial_cfg.get("enabled", True):
            return
        mode = self._radial_cfg.get("trigger_mode", "both")
        if mode in ("hover", "both"):
            self._hover_open_timer.start(int(self._radial_cfg.get("hover_delay_ms", 400)))

    def _open_radial_menu(self, source):
        self._hover_open_timer.stop()
        self._long_press_timer.stop()
        if not self._radial_cfg.get("enabled", True):
            return
        if source == "long_press":
            self._long_press_fired = True
        items = []
        for a in self._agents:
            items.append(RadialMenuItem(
                "agent:%s" % a.get("id"), a.get("name"),
                a.get("command", ""), a.get("icon_color", "#5B8DEF"),
                a.get("icon_char", "A")))
        items.append(RadialMenuItem("skills", "Skills", "辅助窗", "#8E44AD", "S"))
        items.append(RadialMenuItem("api", "API 用量", "余额监控", "#16A085", "¥"))
        items.append(RadialMenuItem("settings", "设置", "偏好", "#5B8DEF", "⚙"))
        items.append(RadialMenuItem("quit", "退出", "AgentFloat", "#E74C3C", "✕"))
        if self._radial_menu is None:
            self._radial_menu = RadialMenu()
            self._radial_menu.action_triggered.connect(self._on_radial_action)
        self._radial_menu.set_theme(self.theme)
        self._radial_menu.set_items(items, radius=int(self._radial_cfg.get("radius", 120)))
        center = self.geometry().center()
        self._radial_menu.open_at(self.mapToGlobal(center), anchor_rect=self.frameGeometry())

    def _close_radial_menu(self):
        if self._radial_menu is not None:
            self._radial_menu.close_menu()

    def _on_radial_action(self, action_id):
        if action_id.startswith("agent:"):
            agent = find_agent(self._agents, action_id[6:])
            if agent:
                launch_agent(agent, self.config)
        elif action_id == "skills":
            self._open_skills_panel()
        elif action_id == "api":
            self._show_api_summary()
        elif action_id == "settings":
            self.settings_requested.emit()
        elif action_id == "quit":
            self.quit_requested.emit()

    def _open_skills_panel(self):
        dlg = SkillsPanel(self._skills_cfg, theme=self.theme, parent=self)
        dlg.exec_()

    def _show_api_summary(self):
        results = getattr(self, "_api_last_results", [])
        if not results:
            QMessageBox.information(
                None, "API 用量",
                "暂无用量数据。\n\n请先在「设置 → API 用量监控」中启用监控并等待轮询。")
            return
        lines = ["各 API 用量情况：", ""]
        for r in results:
            name = getattr(r, "endpoint_name", None) or "?"
            fields = getattr(r, "fields", None) or []
            if fields and fields[0].get("label") == "错误":
                lines.append("• %s：查询失败（%s）" % (name, fields[0].get("value", "")))
                continue
            parts = []
            for f in fields:
                v = f.get("value")
                if v is None:
                    continue
                try:
                    vtxt = "%.2f%s" % (float(v), f.get("unit", ""))
                except (TypeError, ValueError):
                    vtxt = "%s%s" % (v, f.get("unit", ""))
                parts.append("%s %s" % (f.get("label", ""), vtxt))
            lines.append("• %s：%s" % (name, "，".join(parts) or "无字段"))
        QMessageBox.information(None, "API 用量", "\n".join(lines))

    # ── 绘制（7 层玻璃 + 涟漪 + 指示灯）─────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 获取当前主题配色
        tc = get_colors(self.theme)
        shadow = tc["SHADOW"]
        border = tc["BORDER"]
        accent = tc["ACCENT"]
        text = tc["TEXT"]

        scale = self._press_scale
        s = self.current_size
        r = CORNER_RADIUS
        cx, cy = s / 2, s / 2

        if scale != 1.0:
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        shadow_boost = 1.0 + (0.8 if self.is_hovered else 0)
        is_dark = (self.theme == "dark")
        hover_alpha = 20 if (self.is_hovered and is_dark) else (30 if self.is_hovered else 0)

        # 使用预缓存的绘制资源
        c = self._cache
        base_path = c["base"]

        # ── Layer 0: 阴影 ──
        painter.setPen(Qt.NoPen)
        h_offset = 1 if self.is_hovered else 0
        for offset, base_alpha in [(0, 18), (2, 10), (4, 5)]:
            a = min(255, int(base_alpha * shadow_boost))
            so = offset + h_offset
            sr = QRectF(2 + so, 3 + so, s, s)
            sp = QPainterPath()
            sp.addRoundedRect(sr, r, r)
            painter.setBrush(QColor(*shadow, a))
            painter.drawPath(sp)

        # ── Layer 1: 玻璃基底 ──
        painter.setBrush(QBrush(c["diag"]))
        painter.setPen(Qt.NoPen)
        painter.drawPath(base_path)
        painter.setBrush(QBrush(c["radial"]))
        painter.drawPath(base_path)

        # ── Layer 2: 玻璃边框 ──
        if self.is_hovered:
            border_grad = QLinearGradient(0, 0, 0, s)
            border_grad.setColorAt(0.0, QColor(*border, int(190 * 1.3)))
            border_grad.setColorAt(0.45, QColor(*border, int(110 * 1.3)))
            border_grad.setColorAt(1.0, QColor(*border, int(55 * 1.3)))
            pen = QPen(QBrush(border_grad), 1.0)
        else:
            pen = QPen(QBrush(c["border"]), 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRect(0, 0, s - 1, s - 1), r, r)

        # ── Layer 3-5: 柔光 + 内阴影 + 镜面反光 ──
        hl_path = base_path
        painter.setBrush(QBrush(c["hl"]))
        painter.setPen(Qt.NoPen)
        painter.drawPath(hl_path)
        painter.setBrush(QBrush(c["inner"]))
        painter.drawPath(hl_path)
        painter.setBrush(QBrush(c["spec"]))
        painter.drawPath(hl_path)

        # ── Layer 6: 悬停蓝色微染 ──
        if hover_alpha > 0:
            painter.setBrush(QColor(*accent, hover_alpha))
            painter.setPen(Qt.NoPen)
            painter.drawPath(hl_path)

        # ── Layer 7: 图标 ──
        if c.get("icon"):
            painter.drawPixmap(c["icon_x"], c["icon_y"], c["icon"])
        else:
            font = QFont(FONT_FAMILY, int(s * 0.40), QFont.Bold)
            painter.setFont(font)
            painter.setPen(QColor(*text, 200))
            painter.drawText(QRect(0, 0, s, s), Qt.AlignCenter, "CC")

        # ── 涟漪 ──
        if self._ripple_progress > 0 and not self._ripple_pos.isNull():
            rp = self._ripple_progress
            max_rad = s * 0.8
            rad = max_rad * rp
            alpha = int(60 * (1.0 - rp))
            ripple_grad = QRadialGradient(self._ripple_pos, rad)
            ripple_grad.setColorAt(0.0, QColor(*accent, alpha))
            ripple_grad.setColorAt(1.0, QColor(*accent, 0))
            painter.setBrush(QBrush(ripple_grad))
            painter.setPen(Qt.NoPen)
            painter.drawPath(hl_path)

        # ── 安全模式指示器：skip-permissions 时右上角红色圆点 ──
        if self.config.get("launch_mode") == "skip_permissions":
            dot_r = max(4, s * 0.08)
            dot_margin = s * 0.18
            dot_cx = s - dot_margin
            dot_cy = dot_margin
            painter.setBrush(QColor(255, 59, 48, 220))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(dot_cx, dot_cy), dot_r, dot_r)

        # ── Claude 运行中指示器：左下角绿色圆点 ──
        if self._claude_running:
            dot_r = max(4, s * 0.07)
            dot_margin = s * 0.18
            dot_cx = dot_margin
            dot_cy = s - dot_margin
            painter.setBrush(QColor(52, 199, 89, 220))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(dot_cx, dot_cy), dot_r, dot_r)

        painter.end()

    # ── 鼠标事件（拖拽修复）─────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPos()
            self._window_origin = self.pos()
            self._drag_active = False
            # 按压反馈
            self.is_pressed = True
            self._press_anim.stop()
            self._press_anim.setDuration(100)
            self._press_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._press_anim.setStartValue(self._press_scale)
            self._press_anim.setEndValue(PRESS_SCALE)
            self._press_anim.start()
        elif event.button() == Qt.RightButton:
            self._context_menu()
            return

        # 长按唤醒环绕菜单（双通道，可在设置中调整）
        mode = self._radial_cfg.get("trigger_mode", "both")
        if self._radial_cfg.get("enabled", True) and mode in ("long_press", "both"):
            self._long_press_timer.start(int(self._radial_cfg.get("long_press_delay_ms", 500)))

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        delta = (event.globalPos() - self._drag_origin).manhattanLength()
        if not self._drag_active and delta > self.CLICK_THRESHOLD:
            self._drag_active = True
            self._long_press_timer.stop()
        if self._drag_active:
            new_pos = self._window_origin + (event.globalPos() - self._drag_origin)
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._drag_active:
                if self._long_press_fired:
                    # 长按已触发环绕菜单，本次释放不再启动
                    self._long_press_fired = False
                else:
                    # 点击 → 涟漪 + 启动主 Agent
                    self._start_ripple(event.pos())
                    self.launch_requested.emit()
            else:
                # 拖拽结束 → 保存位置 + 检测吸附
                self.config["window_x"] = self.pos().x()
                self.config["window_y"] = self.pos().y()
                self._check_snap()
                # 无论是否吸附都保存位置
                self.config["window_x"] = self.pos().x()
                self.config["window_y"] = self.pos().y()
                save_config(self.config)
            self._drag_active = False
            # 同步 API 面板位置
            self._sync_api_panel_position()
        self.is_pressed = False

    def _start_ripple(self, pos):
        self._ripple_pos = pos
        self._ripple_progress = 0.01
        self._ripple_timer.start()

    def _context_menu(self):
        tc = get_colors(self.theme)
        sfc = tc["SURFACE"]
        txt = tc["TEXT"]
        acc = tc["ACCENT"]
        sep = tc["SEPARATOR"]
        menu_css = (
            f"QMenu {{ background: rgba({sfc[0]},{sfc[1]},{sfc[2]},0.95);"
            f" border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 7px 32px 7px 16px; font-size: 12px;"
            f" color: #{txt[0]:02X}{txt[1]:02X}{txt[2]:02X}; }}"
            f"QMenu::item:selected {{ background: #{acc[0]:02X}{acc[1]:02X}{acc[2]:02X};"
            f" color: #FFF; border-radius: 4px; margin: 1px 6px; }}"
            f"QMenu::separator {{ height: 1px;"
            f" background: #{sep[0]:02X}{sep[1]:02X}{sep[2]:02X}; margin: 4px 8px; }}"
        )
        menu = QMenu(self)
        menu.setStyleSheet(menu_css)

        primary = get_primary_agent(self._agents)
        pname = primary.get("name", "主 Agent") if primary else "主 Agent"
        menu.addAction("启动 %s" % pname, self.launch_requested.emit)
        if len(self._agents) > 1:
            sub = menu.addMenu("启动其他 Agent")
            for a in self._agents:
                if a.get("id") == (primary or {}).get("id"):
                    continue
                sub.addAction(a.get("name"), lambda a=a: launch_agent(a, self.config))
        menu.addAction("Skills 辅助窗", self._open_skills_panel)
        menu.addSeparator()
        menu.addAction("设置...", self.settings_requested.emit)
        menu.addSeparator()

        auto = menu.addAction("开机自启")
        auto.setCheckable(True)
        auto.setChecked(is_auto_start_enabled())
        auto.triggered.connect(lambda checked: toggle_auto_start(checked))

        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)

        menu.exec_(QCursor.pos())

    def closeEvent(self, event):
        self._unregister_hotkey()
        self._close_radial_menu()
        if self._api_badge:
            self._api_badge.close()
        pos = self.pos()
        self.config["window_x"] = pos.x()
        self.config["window_y"] = pos.y()
        save_config(self.config)
        super().closeEvent(event)

    # ── 应用设置 ────────────────────────────────────
    def apply_settings(self, new_cfg, preview_only=False):
        changed = False
        ns = new_cfg.get("widget_size", self.base_size)
        if ns != self.base_size:
            self.base_size = ns
            self.set_widget_size_prop(ns)
            changed = True

        self.config["opacity"] = new_cfg.get("opacity", 0.88)
        self._apply_opacity()
        self.config["launch_mode"] = new_cfg.get("launch_mode", "normal")
        self.config["working_directory"] = new_cfg.get("working_directory", "")
        self.config["cleanup_on_quit"] = new_cfg.get("cleanup_on_quit", False)
        if new_cfg.get("agents") is not None:
            self._agents = normalize_agents(new_cfg["agents"])
            self.config["agents"] = self._agents
        if new_cfg.get("radial_menu") is not None:
            self._radial_cfg = copy.deepcopy(new_cfg["radial_menu"])
            self.config["radial_menu"] = self._radial_cfg
        if new_cfg.get("skills") is not None:
            self._skills_cfg = copy.deepcopy(new_cfg["skills"])
            self.config["skills"] = self._skills_cfg

        # 主题切换
        new_theme = new_cfg.get("theme", "light")
        if new_theme != self.theme:
            self.rebuild_theme(new_theme)
            changed = True

        _log().info("应用设置 (preview=%s): size=%s, opacity=%.2f, mode=%s, theme=%s",
                     preview_only, ns, self.config["opacity"], self.config["launch_mode"], self.theme)

        # 吸附设置
        old_snap = self.config.get("snap_enabled", True)
        old_hidden = self.config.get("snap_hidden", True)
        self.config["snap_enabled"] = new_cfg.get("snap_enabled", True)
        self.config["snap_hidden"] = new_cfg.get("snap_hidden", True)

        if not preview_only:
            self.config["widget_size"] = ns
            self.config["window_x"] = self.pos().x()
            self.config["window_y"] = self.pos().y()

            # API 用量监控配置变更
            new_api_config = new_cfg.get("api_monitor")
            if new_api_config is not None:
                old_api_config = self.config.get("api_monitor", API_MONITOR_DEFAULTS)
                self.config["api_monitor"] = new_api_config
                if new_api_config != old_api_config:
                    _log().info("API 监控配置已变更，重启监控")
                    self._restart_api_monitor()

            save_config(self.config)

            # 吸附设置变更后重新应用
            if self.config["snap_enabled"] != old_snap or self.config["snap_hidden"] != old_hidden:
                if not self.config["snap_enabled"]:
                    self._snapped = False
                    self._remove_edge_detector()
                elif self.config["snap_hidden"] and self._snapped:
                    self._do_hide()
                else:
                    self._show_full()
        if changed:
            self.update()



# ── 全局错误收集（会话内收集，关闭程序时统一导出）────────────────
def _install_error_handlers():
    """安装全局错误收集：
    - 未捕获 Python 异常（含 Qt 槽函数内）与 Qt 关键消息 → 先收集在内存
    - 程序退出时由 main() 调用返回的 flush() 一次性导出
      logs/reports/v{VERSION}_{时间戳}_errors.txt（汇总会话内全部错误）
    """
    report_dir = os.path.join(_get_config_dir(), "logs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    errors = []
    _seen_exc = set()

    def _record(kind, exc_type, exc, tb_text):
        from datetime import datetime as _dt
        errors.append({
            "time": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            "type": exc_type or "-",
            "message": (str(exc) if exc is not None else "-"),
            "traceback": tb_text or "",
        })

    def _on_unhandled_exception(exc_type, exc, tb):
        if exc in _seen_exc:
            return
        _seen_exc.add(exc)
        import traceback
        tb_text = "".join(traceback.format_exception(exc_type, exc, tb))
        _log().critical("未捕获异常 [%s]: %s\n%s",
                        getattr(exc_type, "__name__", str(exc_type)), exc, tb_text)
        _record("error", getattr(exc_type, "__name__", str(exc_type)), exc, tb_text)

    sys.excepthook = _on_unhandled_exception

    def _qt_message_handler(msg_type, context, message):
        msg = str(message)
        # 已知无害噪音降级到 debug，避免刷屏
        if "UpdateLayeredWindowIndirect failed" in msg:
            _log().debug("Qt: %s", msg)
            return
        if msg_type == QtMsgType.QtDebugMsg:
            _log().debug("Qt: %s", msg)
        elif msg_type == QtMsgType.QtWarningMsg:
            _log().warning("Qt: %s", msg)
        elif msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            _log().error("Qt: %s", msg)
            _record("qterror", "QtCritical", None, msg)

    try:
        qInstallMessageHandler(_qt_message_handler)
    except Exception as e:
        _log().debug("Qt 消息处理器安装失败: %s", e)

    def flush_error_report():
        """关闭程序时调用：将本会话收集到的所有错误一次性导出"""
        if not errors:
            return None
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(report_dir, "v%s_%s_errors.txt" % (VERSION, ts))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("AgentFloat v%s 错误汇总报告（共 %d 条）\n" % (VERSION, len(errors)))
                f.write("导出时间: %s\n" % _dt.now().isoformat())
                f.write("PID: %s | Frozen: %s\n" % (os.getpid(), _IS_FROZEN))
                f.write("Python: %s\n" % sys.version)
                f.write("-" * 40 + "\n\n")
                for i, e in enumerate(errors, 1):
                    f.write("[%d] %s @ %s\n" % (i, e["kind"], e["time"]))
                    f.write("    类型: %s\n" % e["type"])
                    f.write("    信息: %s\n" % e["message"])
                    tb = e["traceback"].strip()
                    if tb:
                        f.write("    堆栈:\n")
                        for line in tb.splitlines():
                            f.write("      %s\n" % line)
                    f.write("-" * 40 + "\n")
            return path
        except Exception:
            return None

    return flush_error_report


# ── 主入口 ──────────────────────────────────────────
def main():
    # ── 启动日志 ──
    _setup_logger()
    _log().info("=" * 50)
    _log().info("AgentFloat v%s 启动 | Frozen=%s | PID=%s", VERSION, _IS_FROZEN, os.getpid())

    from datetime import datetime as _dt
    _start_ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    _report_dir = os.path.join(_get_config_dir(), "logs", "reports")
    os.makedirs(_report_dir, exist_ok=True)
    _flush_error_report = _install_error_handlers()
    _session_path = os.path.join(_report_dir, f"v{VERSION}_{_start_ts}_session.txt")

    # 写入会话报告开头
    try:
        with open(_session_path, "w", encoding="utf-8") as _sf:
            _sf.write(f"AgentFloat v{VERSION} 会话报告\n")
            _sf.write(f"启动时间: {_dt.now().isoformat()}\n")
            _sf.write("打包模式: " + ("Frozen" if _IS_FROZEN else "Dev") + "\n")
            _sf.write(f"进程 PID: {os.getpid()}\n")
            _sf.write(f"Python: {sys.version}\n")
            _sf.write("-" * 40 + "\n")
    except Exception:
        pass

    try:
        _main()
        _log().info("AgentFloat 正常退出")
        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\n退出时间: {_dt.now().isoformat()}\n")
                _sf.write("状态: 正常退出\n")
        except Exception:
            pass
        _flush = _flush_error_report()
        if _flush:
            _log().info("错误汇总报告已导出: %s", _flush)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        exc_type = type(sys.exc_info()[1]).__name__ if sys.exc_info()[1] else "Unknown"
        _log().critical("未处理异常导致崩溃 [%s]:\n%s", exc_type, tb)

        _crash_path = os.path.join(_report_dir, f"v{VERSION}_{_start_ts}_{exc_type}.txt")
        try:
            with open(_crash_path, "w", encoding="utf-8") as _cf:
                _cf.write(f"AgentFloat v{VERSION} 崩溃报告\n")
                _cf.write(f"启动时间: {_start_ts}\n")
                _cf.write(f"崩溃时间: {_dt.now().isoformat()}\n")
                _cf.write(f"异常类型: {exc_type}\n")
                _cf.write("打包模式: " + ("Frozen" if _IS_FROZEN else "Dev") + "\n")
                _cf.write(f"Python: {sys.version}\n")
                _cf.write("-" * 40 + "\n\n")
                _cf.write(tb)
            _log().info("崩溃报告已写入: %s", _crash_path)
        except Exception:
            pass

        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\n退出时间: {_dt.now().isoformat()}\n")
                _sf.write(f"状态: 崩溃 ({exc_type})\n")
                _sf.write(f"详情: {_crash_path}\n")
        except Exception:
            pass
        try:
            sys.excepthook(*sys.exc_info())
        except Exception:
            pass
        _flush = _flush_error_report()
        if _flush:
            _log().info("错误汇总报告已导出: %s", _flush)
        raise


def _main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("agentfloat.launcher")
    except Exception: pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AgentFloat")
    app.setFont(QFont(FONT_FAMILY, 9))

    config = load_config()

    # 退出时清理孤儿 Claude 进程（可配置，默认不清理）
    def _cleanup_on_quit():
        if config.get("cleanup_on_quit", False):
            primary = get_primary_agent(config.get("agents", default_agents()))
            cmd = (primary or {}).get("command", "")
            if cmd:
                base = os.path.basename(cmd)
                if not base.lower().endswith(".exe"):
                    base += ".exe"
                _log().info("退出清理: taskkill /f /im %s", base)
                subprocess.run(["taskkill", "/f", "/im", base],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    app.aboutToQuit.connect(_cleanup_on_quit)

    widget = FloatingWidget()

    # ── 设置对话框 ──
    def open_settings():
        _log().debug("打开设置对话框")
        dlg = SettingsDialog(widget.config, parent=widget)
        if dlg.exec_() == QDialog.Accepted and dlg.result_config:
            preview = dlg.result_config.pop("_preview", False)
            widget.apply_settings(dlg.result_config, preview_only=preview)

    def do_launch():
        launch_agent(get_primary_agent(widget.config.get("agents", default_agents())), widget.config)

    # ── 自动更新 ──
    update_worker_ref = {}
    download_worker_ref = {}

    def _download_latest(info):
        """后台下载最新安装包，完成后询问是否运行"""
        asset = pick_setup_asset(info.get("assets") or [])
        if asset is None:
            QMessageBox.information(
                None, "更新",
                "最新版本没有可下载的安装包，\n请前往 GitHub Releases 页面手动下载。")
            return
        dest_dir = os.path.join(_get_config_dir(), "updates")

        def _on_done(path):
            download_worker_ref.pop("worker", None)
            _log().info("更新包下载完成: %s", path)
            ret = QMessageBox.question(
                None, "下载完成",
                f"新版本 {info['version']} 安装包已下载：\n{path}\n\n"
                "是否立即运行安装程序？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ret == QMessageBox.Yes:
                try:
                    os.startfile(path)
                except Exception as e:
                    QMessageBox.warning(None, "启动失败", f"无法启动安装程序:\n{e}")

        def _on_failed(msg):
            download_worker_ref.pop("worker", None)
            QMessageBox.warning(None, "下载失败", f"下载更新失败:\n{msg}")

        worker = DownloadWorker(asset, dest_dir)
        worker.done.connect(_on_done)
        worker.failed.connect(_on_failed)
        download_worker_ref["worker"] = worker
        worker.start()
        _log().info("开始下载更新: %s (%s bytes)", asset.get("name", "?"), asset.get("size", "?"))

    def _on_update_result(info, manual):
        update_worker_ref.pop("worker", None)
        if info is None:
            if manual:
                QMessageBox.information(None, "检查更新", f"当前已是最新版本 v{VERSION}。")
            return
        body = (info.get("body") or "").strip()
        detail = body[:400] if body else "前往 GitHub Releases 查看更新说明。"
        ret = QMessageBox.question(
            None, "发现新版本",
            f"发现新版本 {info['version']}（当前 v{VERSION}）。\n\n更新内容:\n{detail}\n\n"
            "是否立即下载安装包？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ret == QMessageBox.Yes:
            _download_latest(info)

    def _on_check_failed(msg, manual):
        update_worker_ref.pop("worker", None)
        if manual:
            QMessageBox.warning(None, "检查更新失败", f"无法连接 GitHub：\n{msg}")

    def _check_update(manual=False):
        if update_worker_ref.get("worker"):
            return  # 正在检查中
        worker = UpdateWorker(VERSION)
        worker.result_ready.connect(lambda info: _on_update_result(info, manual))
        worker.check_failed.connect(lambda msg: _on_check_failed(msg, manual))
        update_worker_ref["worker"] = worker
        worker.start()
        _log().info("检查更新 (手动=%s, 当前 v%s)", manual, VERSION)

    # ── 系统托盘 ──
    def _build_menu_stylesheet(theme):
        tc = get_colors(theme)
        sfc = tc["SURFACE"]
        txt = tc["TEXT"]
        acc = tc["ACCENT"]
        sep = tc["SEPARATOR"]
        return (
            f"QMenu {{ background: rgba({sfc[0]},{sfc[1]},{sfc[2]},0.95);"
            f" border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 7px 32px 7px 16px; font-size: 12px;"
            f" color: #{txt[0]:02X}{txt[1]:02X}{txt[2]:02X}; }}"
            f"QMenu::item:selected {{ background: #{acc[0]:02X}{acc[1]:02X}{acc[2]:02X};"
            f" color: #FFF; border-radius: 4px; margin: 1px 6px; }}"
            f"QMenu::separator {{ height: 1px;"
            f" background: #{sep[0]:02X}{sep[1]:02X}{sep[2]:02X}; margin: 4px 8px; }}"
        )

    tray_menu = QMenu()
    tray_menu.setStyleSheet(_build_menu_stylesheet(widget.theme))

    tray_menu.addAction("显示浮窗", widget.show)
    tray_menu.addSeparator()
    tray_primary = get_primary_agent(widget.config.get("agents", default_agents()))
    tray_pname = tray_primary.get("name", "主 Agent") if tray_primary else "主 Agent"
    tray_menu.addAction("启动 %s" % tray_pname, do_launch)
    if len(widget.config.get("agents", [])) > 1:
        tray_sub = tray_menu.addMenu("启动其他 Agent")
        for a in widget.config.get("agents", []):
            if a.get("id") == (tray_primary or {}).get("id"):
                continue
            tray_sub.addAction(a.get("name"), lambda a=a: launch_agent(a, widget.config))
    tray_menu.addAction("Skills 辅助窗", widget._open_skills_panel)
    tray_menu.addSeparator()
    tray_menu.addAction("设置...", open_settings)
    tray_menu.addSeparator()

    tray_auto = tray_menu.addAction("开机自启")
    tray_auto.setCheckable(True)
    tray_auto.setChecked(is_auto_start_enabled())
    tray_auto.triggered.connect(lambda c: toggle_auto_start(c))

    tray_menu.addSeparator()
    tray_menu.addAction("检查更新...", lambda: _check_update(manual=True))
    tray_menu.addSeparator()
    tray_menu.addAction("退出", app.quit)

    tray_icon = QSystemTrayIcon()
    if os.path.exists(ICO_PATH):
        tray_icon.setIcon(QIcon(ICO_PATH))
    else:
        pix = QPixmap(32, 32)
        tc = get_colors(widget.theme)
        pix.fill(QColor(*tc["ACCENT"]))
        tray_icon.setIcon(QIcon(pix))

    tray_icon.setToolTip("AgentFloat — AI Agent 浮窗助手 | 点击启动主 Agent | 悬停/长按环绕菜单 | Ctrl+Alt+C")
    tray_icon.setContextMenu(tray_menu)
    tray_icon.activated.connect(lambda r: widget.show() if r == QSystemTrayIcon.DoubleClick else None)
    tray_icon.show()
    tray_icon.showMessage("AgentFloat", "AI Agent 浮窗助手已启动", QSystemTrayIcon.Information, 2000)

    widget.launch_requested.connect(do_launch)
    widget.quit_requested.connect(app.quit)
    widget.settings_requested.connect(open_settings)
    # 主题切换时同步更新托盘菜单样式
    widget.theme_changed.connect(lambda t: tray_menu.setStyleSheet(_build_menu_stylesheet(t)))
    widget.show()

    if config.get("auto_start") and not is_auto_start_enabled():
        toggle_auto_start(True)

    # 启动后延迟自动检查更新（不阻塞启动）
    if config.get("check_updates", True):
        QTimer.singleShot(3000, lambda: _check_update(manual=False))

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
