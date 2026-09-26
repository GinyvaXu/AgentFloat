# -*- coding: utf-8 -*-
"""AgentFloat 启动入口（兼容旧习惯：python agent_float.py）

实际代码位于 src/agentfloat/ 包内（v3 结构）：
- 应用引导：agentfloat.app
- 核心层：core（路径/配置/主题/日志/启动器）
- 界面层：ui（浮球/环菜单/面板）
- 服务层：services（API 监控/快讯/Skills/喝水/更新/dsh）
- Web 壳：webshell（FastAPI + pywebview）
"""
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agentfloat.app import main  # noqa: E402

if __name__ == "__main__":
    # PyInstaller 冻结环境下 multiprocessing 子进程（Web 壳窗口）必须先行 freeze_support
    import multiprocessing as _mp
    _mp.freeze_support()
    main()
