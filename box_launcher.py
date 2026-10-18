# -*- coding: utf-8 -*-
"""盒子（HSAng）启动器：保证它带 ``--remote-debugging-port`` 启动。

推荐、AI 胜率、传说名次三条链路都依赖盒子的 CEF 调试端口；盒子如果是从
快捷方式/自动启动打开的（没有端口），本模块会提示或重启它。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

DEFAULT_PORT = 9222
DEFAULT_EXE = r"D:\炉石传说盒子\HSAng.exe"
ROOT = Path(__file__).resolve().parent


def port_open(port: int = DEFAULT_PORT, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout):
            return True
    except OSError:
        return False


def box_path() -> Path | None:
    """盒子 exe：环境变量 HSA_BOX_EXE → ui_config.json 的 box.exe → 默认安装路径。"""
    env = os.environ.get("HSA_BOX_EXE")
    if env and Path(env).is_file():
        return Path(env)
    try:
        cfg = json.loads((ROOT / "ui_config.json").read_text(encoding="utf-8"))
        configured = (cfg.get("box") or {}).get("exe")
        if configured and Path(configured).is_file():
            return Path(configured)
    except Exception:
        pass
    default = Path(DEFAULT_EXE)
    return default if default.is_file() else None


def _processes() -> list:
    try:
        import psutil
    except Exception:
        return []
    found = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if str(proc.info.get("name") or "").lower() == "hsang.exe":
                found.append(proc.info["pid"])
        except Exception:
            continue
    return found


def _game_running() -> bool:
    try:
        import psutil
    except Exception:
        return False
    for proc in psutil.process_iter(["name"]):
        try:
            if str(proc.info.get("name") or "").lower() == "hearthstone.exe":
                return True
        except Exception:
            continue
    return False


def _terminate(pids) -> tuple[bool, str]:
    try:
        import psutil
    except Exception as exc:
        return False, f"缺少 psutil：{exc}"
    errors = []
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception as exc:
            errors.append(f"{pid}: {exc}")
    return (not errors), "; ".join(errors)


def ensure_box(port: int = DEFAULT_PORT, restart: bool = False,
               wait: float = 15.0) -> dict:
    """确保盒子带调试端口在跑。

    返回 ``{ok, action, message, pid?}``：
      already      —— 端口已开，什么都不用做
      started      —— 盒子没开，已带参数启动
      restarted    —— 盒子开着但没端口，已重启（需要管理员）
      needs_restart—— 盒子开着但没端口，且不允许重启/游戏在跑
      missing      —— 找不到 HSAng.exe
      failed       —— 启动失败（多为权限不足）
    """
    if port_open(port):
        return {"ok": True, "action": "already",
                "message": f"盒子已在 {port} 端口就绪"}

    pids = _processes()
    if pids and not restart:
        return {"ok": False, "action": "needs_restart",
                "message": f"盒子在运行（pid {pids[0]}）但没有调试端口，需要重启盒子"}
    if pids and _game_running():
        return {"ok": False, "action": "needs_restart",
                "message": "炉石正在运行：先打完这一局再重启盒子（带端口）"}

    exe = box_path()
    if exe is None:
        return {"ok": False, "action": "missing",
                "message": f"找不到 HSAng.exe（设 HSA_BOX_EXE 或写 ui_config.json 的 box.exe）"}

    if pids:
        ok, error = _terminate(pids)
        if not ok:
            return {"ok": False, "action": "failed",
                    "message": f"结束旧盒子失败（需要管理员）：{error}"}
        time.sleep(2)

    try:
        proc = subprocess.Popen(
            [str(exe), f"--remote-debugging-port={int(port)}"],
            cwd=str(exe.parent))
    except OSError as exc:
        return {"ok": False, "action": "failed",
                "message": f"启动盒子失败（控制台需要管理员）：{exc}"}

    deadline = time.time() + max(1.0, wait)
    while time.time() < deadline:
        if port_open(port):
            return {"ok": True,
                    "action": "restarted" if pids else "started",
                    "pid": proc.pid,
                    "message": f"盒子已{'重启' if pids else '启动'}"
                               f"（pid {proc.pid}，调试端口 {port}）"}
        if proc.poll() is not None:
            return {"ok": False, "action": "failed",
                    "message": f"盒子进程已退出（code {proc.returncode}）；"
                               f"确认是以管理员权限启动的"}
        time.sleep(0.5)
    return {"ok": False, "action": "failed", "pid": proc.pid,
            "message": f"盒子已启动（pid {proc.pid}）但 {port} 端口没起来，"
                       f"这版 CEF 可能没开放调试端口"}
