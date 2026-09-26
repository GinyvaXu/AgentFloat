# -*- coding: utf-8 -*-
"""python -m agentfloat 入口（源码运行：需将 src/ 加入 PYTHONPATH）"""
import multiprocessing

from agentfloat.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
