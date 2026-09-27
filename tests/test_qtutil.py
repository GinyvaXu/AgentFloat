# -*- coding: utf-8 -*-
"""QThread 引用释放时序单测（PATCH 3.0.2）

背景：PyQt5 中在结果回调里直接清掉 QThread 引用，会在线程尚未退出时
销毁 C++ 对象 → Qt qFatal（0xC0000409 崩溃）。release_thread_later
必须保证「运行中不释放、结束后必释放」。
"""
import time

from PyQt5.QtCore import QThread, pyqtSignal


class _EmitThenSleep(QThread):
    """emit 之后仍停留一小段（模拟 run() 尚未返回的真实时序）"""

    done = pyqtSignal()

    def run(self):
        self.done.emit()
        time.sleep(0.4)


def _pump(qapp, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)


def test_release_deferred_until_thread_finished(qapp):
    from agentfloat.core.qtutil import release_thread_later
    w = _EmitThenSleep()
    released = []
    w.done.connect(lambda: release_thread_later(w, lambda: released.append(1)))
    w.start()
    _pump(qapp, 0.15)
    assert released == [], "线程仍在运行（emit 后未返回）时不得释放引用"
    _pump(qapp, 1.2)
    assert released == [1], "线程结束后必须释放引用"
    assert not w.isRunning()


def test_release_immediately_when_not_running(qapp):
    from agentfloat.core.qtutil import release_thread_later
    w = _EmitThenSleep()
    w.start()
    assert w.wait(2000)
    got = []
    release_thread_later(w, lambda: got.append(1))
    qapp.processEvents()
    assert got == [1], "线程已结束时应立即释放"


def test_release_none_is_noop(qapp):
    from agentfloat.core.qtutil import release_thread_later

    def _boom():
        raise AssertionError("thread 为 None 时不应调用 release")

    release_thread_later(None, _boom)
