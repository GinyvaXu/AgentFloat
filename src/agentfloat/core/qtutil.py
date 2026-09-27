# -*- coding: utf-8 -*-
"""Qt 线程引用释放工具（PATCH 3.0.2）

PyQt5 中 QThread 的 Python 包装对象一旦被 GC，会连带销毁其 C++ 对象；
若此时线程仍在运行（典型场景：``run()`` 里 emit 结果后还未返回），
Qt 会触发 qFatal「QThread: Destroyed while thread is still running」，
在 Windows 上表现为 0xC0000409 (BEX64) 崩溃、进程直接消失。

因此所有「结果回调里清掉 worker 引用」的写法都必须改为线程真正结束
之后再释放引用。本模块提供统一入口。
"""
from PyQt5.QtCore import QTimer

# 已创建的 worker 线程登记表：id(thread) -> (名称, weakref)（PATCH 3.0.2 诊断用）
_registry = {}


def track(thread, name):
    """登记 worker 线程（仅用于崩溃时定位，不持有强引用）"""
    import weakref
    try:
        _registry[id(thread)] = (name, weakref.ref(thread))
    except TypeError:
        pass


def alive_threads():
    """返回仍在运行的已登记 worker 名称列表（供崩溃诊断输出）"""
    out = []
    for key, (name, ref) in list(_registry.items()):
        t = ref()
        if t is None:
            _registry.pop(key, None)
            continue
        try:
            if t.isRunning():
                out.append(name)
        except RuntimeError:
            _registry.pop(key, None)
    return out


def release_thread_later(thread, release):
    """在线程结束后再执行 ``release()``（延迟到下一轮事件循环）。

    - ``thread`` 为 None：什么都不做；
    - 线程已结束：立即 ``release()``；
    - 线程仍在运行：连接 ``finished``，等线程真正结束（含 ``wait`` 兜底）
      后延迟释放。
    """
    if thread is None:
        return
    if thread.isRunning():
        def _after_finished():
            try:
                thread.wait(1000)       # finished 后线程即将退出，确保完全结束
            except Exception:           # noqa: BLE001
                pass
            QTimer.singleShot(0, release)

        thread.finished.connect(_after_finished)
    else:
        release()
