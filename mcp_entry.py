# -*- coding: utf-8 -*-
"""af-mcp 入口：独立控制台程序，通过 stdio 提供 progress 工具。"""
import sys

from agentfloat.mcp_server import main

if __name__ == "__main__":
    sys.exit(main())
