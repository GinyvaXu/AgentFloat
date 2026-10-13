"""
API 用量监控 — QThread 轮询工作线程
"""
import logging
from PyQt5.QtCore import QThread, pyqtSignal

from agentfloat.services.api_monitor.fetcher import fetch_endpoint, FetchError

_logger = logging.getLogger("AgentFloat")


class ApiMonitorWorker(QThread):
    """后台线程：定时轮询所有 API 端点"""

    # 数据就绪信号：list[FetchResult]
    data_ready = pyqtSignal(list)
    # 错误信号：str
    fetch_error = pyqtSignal(str)

    def __init__(self, endpoints: list, interval_seconds: int = 60, verify_ssl: bool = True):
        super().__init__()
        self._endpoints = endpoints
        self._interval_ms = interval_seconds * 1000
        self._verify_ssl = verify_ssl
        self._running = False
        self._refresh_now = False     # PATCH 3.5.2：手动立即拉取标记

    def request_refresh(self):
        """PATCH 3.5.2：请求立即轮询一次（唤醒分段睡眠）"""
        self._refresh_now = True
        _logger.info("API 监控：收到手动立即拉取请求")

    def update_config(self, endpoints: list, interval_seconds: int = None, verify_ssl: bool = True):
        """运行时更新配置"""
        self._endpoints = endpoints
        if interval_seconds is not None:
            self._interval_ms = interval_seconds * 1000
        self._verify_ssl = verify_ssl

    def run(self):
        self._running = True
        _logger.info("API 监控线程启动: %d 端点, 间隔 %ds",
                      len(self._endpoints), self._interval_ms // 1000)

        import time
        backoff = 1.0                      # v3.12.1：连续失败时退避倍数
        while self._running:
            results = []
            ok_count = 0
            for ep in self._endpoints:
                try:
                    result = fetch_endpoint(ep, verify_ssl=self._verify_ssl)
                    results.append(result)
                    ok_count += 1
                    _logger.debug("API 端点 [%s] 获取成功: %d 字段",
                                  ep.get("name", "?"), len(result.fields))
                except FetchError as e:
                    # 将错误信息作为伪字段
                    from agentfloat.services.api_monitor.fetcher import FetchResult
                    err_result = FetchResult(
                        endpoint_name=ep.get("name", "?"),
                        fields=[{"label": "错误", "value": str(e)[:100], "unit": "", "display": "text"}],
                    )
                    results.append(err_result)
                    _logger.warning("API 端点 [%s] 请求失败: %s",
                                    ep.get("name", "?"), str(e)[:200])

            self.data_ready.emit(results)

            # 全部失败 → 逐步退避（1x → 2x → 4x → 8x，上限 10 分钟），恢复后回到正常间隔
            if results and ok_count == 0:
                backoff = min(backoff * 2.0, 10.0)
                wait_ms = int(self._interval_ms * backoff)
                _logger.info("API 监控：全部端点失败，退避到 %ds 后重试", wait_ms // 1000)
            else:
                backoff = 1.0
                wait_ms = self._interval_ms

            # 分段睡眠，以便能及时响应 stop / 手动立即拉取
            slept = 0
            while self._running and slept < wait_ms and not self._refresh_now:
                time.sleep(0.5)
                slept += 500
            self._refresh_now = False

        _logger.info("API 监控线程已停止")

    def stop(self):
        self._running = False
