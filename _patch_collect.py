# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
path = "agent_float.py"
src = open(path, encoding="utf-8").read()

# ---- 1) 替换 _install_error_handlers 为会话内收集 + 退出时统一导出 ----
start = src.find("# ── 全局报错导出（每次报错 → 时间戳命名错误日志）──────────────────")
end = src.find("# ── 主入口 ──────────────────────────────────────────")
assert start >= 0 and end > start, "handler block anchors not found"

new_handler = '''# ── 全局错误收集（会话内收集，关闭程序时统一导出）────────────────
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
        key = id(exc)
        if key in _seen_exc:
            return
        _seen_exc.add(key)
        import traceback
        tb_text = "".join(traceback.format_exception(exc_type, exc, tb))
        _log().critical("未捕获异常 [%s]: %s\\n%s",
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
                f.write("AgentFloat v%s 错误汇总报告（共 %d 条）\\n" % (VERSION, len(errors)))
                f.write("导出时间: %s\\n" % _dt.now().isoformat())
                f.write("PID: %s | Frozen: %s\\n" % (os.getpid(), _IS_FROZEN))
                f.write("Python: %s\\n" % sys.version)
                f.write("-" * 40 + "\\n\\n")
                for i, e in enumerate(errors, 1):
                    f.write("[%d] %s @ %s\\n" % (i, e["kind"], e["time"]))
                    f.write("    类型: %s\\n" % e["type"])
                    f.write("    信息: %s\\n" % e["message"])
                    tb = e["traceback"].strip()
                    if tb:
                        f.write("    堆栈:\\n")
                        for line in tb.splitlines():
                            f.write("      %s\\n" % line)
                    f.write("-" * 40 + "\\n")
            return path
        except Exception:
            return None

    return flush_error_report


'''
src = src[:start] + new_handler + src[end:]

# ---- 2) main(): 接收 flush 并在正常/崩溃退出时调用 ----
old = "    _install_error_handlers()\n    _session_path = os.path.join(_report_dir, f\"v{VERSION}_{_start_ts}_session.txt\")"
new = "    _flush_error_report = _install_error_handlers()\n    _session_path = os.path.join(_report_dir, f\"v{VERSION}_{_start_ts}_session.txt\")"
assert old in src, "main hook anchor not found"
src = src.replace(old, new, 1)

# 正常退出：写入会话报告后 flush
old = """        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\\n退出时间: {_dt.now().isoformat()}\\n")
                _sf.write("状态: 正常退出\\n")
        except Exception:
            pass
    except Exception:"""
new = """        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\\n退出时间: {_dt.now().isoformat()}\\n")
                _sf.write("状态: 正常退出\\n")
        except Exception:
            pass
        _flush = _flush_error_report()
        if _flush:
            _log().info("错误汇总报告已导出: %s", _flush)
    except Exception:"""
assert old in src, "normal-exit flush anchor not found"
src = src.replace(old, new, 1)

# 崩溃退出：先记录当前异常再 flush，随后 raise（excepthook 去重避免重复）
old = """        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\\n退出时间: {_dt.now().isoformat()}\\n")
                _sf.write(f"状态: 崩溃 ({exc_type})\\n")
                _sf.write(f"详情: {_crash_path}\\n")
        except Exception:
            pass
        raise"""
new = """        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\\n退出时间: {_dt.now().isoformat()}\\n")
                _sf.write(f"状态: 崩溃 ({exc_type})\\n")
                _sf.write(f"详情: {_crash_path}\\n")
        except Exception:
            pass
        try:
            sys.excepthook(*sys.exc_info())
        except Exception:
            pass
        _flush = _flush_error_report()
        if _flush:
            _log().info("错误汇总报告已导出: %s", _flush)
        raise"""
assert old in src, "crash-exit flush anchor not found"
src = src.replace(old, new, 1)

open(path, "w", encoding="utf-8").write(src)
print("PATCH OK: 会话内收集 + 退出统一导出")
