# -*- coding: utf-8 -*-
"""日志体系测试：滚动日志初始化 / 错误收集与汇总导出（会话报告要素）"""
import logging
import os
import sys


def _reset_agentfloat_logger():
    logger = logging.getLogger("AgentFloat")
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass


def test_setup_logger_creates_file(tmp_path, monkeypatch):
    from agentfloat.core import logging_setup as ls
    monkeypatch.setattr(ls, "config_dir", lambda: str(tmp_path))
    _reset_agentfloat_logger()
    ls._logger = None
    lg = ls._setup_logger()
    lg.info("hello-logging-test")
    log_file = tmp_path / "logs" / "AgentFloat.log"
    assert log_file.exists()
    assert "hello-logging-test" in log_file.read_text(encoding="utf-8")
    # 再次调用应复用（幂等）
    assert ls._setup_logger() is lg
    _reset_agentfloat_logger()
    ls._logger = None


def test_error_handler_collect_and_flush(qapp, tmp_path, monkeypatch):
    from agentfloat.core import logging_setup as ls
    monkeypatch.setattr(ls, "config_dir", lambda: str(tmp_path))
    _reset_agentfloat_logger()
    ls._logger = None
    ls._setup_logger()

    old_hook = sys.excepthook
    flush = ls._install_error_handlers()
    try:
        try:
            raise ValueError("boom-xyz-测试")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        path = flush()
        assert path and os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "boom-xyz" in content
        assert "错误汇总报告" in content
    finally:
        sys.excepthook = old_hook
        _reset_agentfloat_logger()
        ls._logger = None


def test_flush_returns_none_without_errors(qapp, tmp_path, monkeypatch):
    from agentfloat.core import logging_setup as ls
    monkeypatch.setattr(ls, "config_dir", lambda: str(tmp_path))
    old_hook = sys.excepthook
    flush = ls._install_error_handlers()
    try:
        assert flush() is None
    finally:
        sys.excepthook = old_hook
