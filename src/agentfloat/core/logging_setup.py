# -*- coding: utf-8 -*-
"""AgentFloat — 日志与崩溃报告（滚动日志 + Debug 会话日志 + 错误汇总）"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from PyQt5.QtCore import QtMsgType, qInstallMessageHandler

from agentfloat.core.paths import _IS_DEBUG, _IS_FROZEN, config_dir
from agentfloat.core.version import VERSION

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
        debug_dir = os.path.join(config_dir(), "debug_logs")
        os.makedirs(debug_dir, exist_ok=True)
        session_name = datetime.now().strftime("session_%Y%m%d_%H%M%S.log")
        fh = logging.FileHandler(os.path.join(debug_dir, session_name), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # 3) 保留滚动日志（方便跨会话排查）
        log_dir = os.path.join(config_dir(), "logs")
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
        log_dir = os.path.join(config_dir(), "logs")
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


def _install_error_handlers():
    """安装全局错误收集：
    - 未捕获 Python 异常（含 Qt 槽函数内）与 Qt 关键消息 → 先收集在内存
    - 程序退出时由 main() 调用返回的 flush() 一次性导出
      logs/reports/v{VERSION}_{时间戳}_errors.txt（汇总会话内全部错误）
    """
    report_dir = os.path.join(config_dir(), "logs", "reports")
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
