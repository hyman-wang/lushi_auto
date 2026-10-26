#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""项目版本号的**唯一来源**：网页控制台、日志浮窗、CLI 都从这里取。

以前 `hsctl.py` 里自己写着 ``HSCTL_VERSION = "1.0.0"``，网页写的是
``server_version = "HSLegendArriver/1.0"``，两边各写一份、很快就对不上。
现在只有本文件能改版本号。

**本分支沿用语义化版本**（``1.3.25``），界面上显示 ``v1.3.25``：

* 与主线（上游用发布日期 ``2026.10.24``）区分开：本分支是 OCR 链路，版本号
  自己走一条线，合并上游功能时递增次版本号；
* 不在版本号后面挂 git 短哈希 —— 一个串就够，对账时不用再解释；
* 上游的 ``update_check`` 同时认这两种口径：同口径才比较，跨口径一律返回
  ``unknown``（不会把「上游日期号」误判成本分支有新版本）。

发版时只改 ``VERSION`` 一处，浮窗、网页、`hsctl --version` 会同时变。
"""

from __future__ import annotations

from pathlib import Path

#: 项目大名，浮窗品牌行、网页标题、HTTP Server 头都用它。
NAME = "HSLegendArriver"

#: 版本号（语义化 ``MAJOR.MINOR.PATCH``）。**每次发版只改这一处。**
VERSION = "1.3.25"

ROOT = Path(__file__).resolve().parent


def version_label() -> str:
    """界面上的版本串，例如 ``v1.3.25``。"""
    return f"v{VERSION}"


#: 兼容旧调用点（`from version import __version__`），值与 VERSION 保持一致。
__version__ = VERSION


def version_info() -> dict:
    """给 HTTP 接口/CLI 用的结构化版本信息。"""
    return {
        "name": NAME,
        "version": VERSION,
        "label": version_label(),
    }
