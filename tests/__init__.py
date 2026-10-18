# -*- coding: utf-8 -*-
"""测试包标记。

有它之后全量回归可以一条命令跑完：

    d:\\miniconda3\\envs\\HTL\\python.exe -m unittest discover -s tests -t .

（本机 HTL 环境没有 pytest，所以用 unittest。）
"""

import os

# 测试里不要真的去启动/重启盒子（hsctl prepare 会尝试自动拉起盒子）。
os.environ.setdefault("HS_NO_BOX_AUTOSTART", "1")
