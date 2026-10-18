# -*- coding: utf-8 -*-
"""单窗口桌面壳：用 WebView2 承载现有网页 UI，关闭窗口即退出。

只依赖 pywebview；不参与业务逻辑。webview 在导入时不加载，
这样单元测试和 ``--no-browser`` 开发模式都不需要 WebView2 运行时。
"""
from __future__ import annotations

import ctypes
import traceback

TITLE = "HSLegendArriver"


def focus_existing_window() -> bool:
    """把已经打开的同名窗口切到前台；找不到返回 False。"""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _enum(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if TITLE in buf.value:
            found.append(hwnd)
            return False
        return True

    try:
        user32.EnumWindows(_enum, 0)
    except Exception:
        return False
    if not found:
        return False
    hwnd = found[0]
    try:
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        return False
    return True


def run(url: str, width: int = 1500, height: int = 1100) -> bool:
    """打开唯一的应用窗口并阻塞到用户关闭它。

    成功打开并关闭返回 True；pywebview / WebView2 不可用时返回 False，
    调用方可以退回浏览器模式。
    """
    try:
        import webview
    except Exception as exc:
        print(f"[window] 无法导入 pywebview：{type(exc).__name__}: {exc}")
        return False

    try:
        user32 = ctypes.windll.user32
        width = max(1100, min(width, user32.GetSystemMetrics(0) - 80))
        height = max(720, min(height, user32.GetSystemMetrics(1) - 80))
        webview.create_window(
            TITLE,
            url,
            width=width,
            height=height,
            min_size=(1100, 720),
            background_color="#0d0906",
            confirm_close=False,
        )
        webview.start(debug=False, private_mode=False)
        return True
    except Exception:
        traceback.print_exc()
        return False
