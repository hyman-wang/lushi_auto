"""CEF DevTools (CDP) 数据源：直接读盒子推给「打法参考A/B」面板的 JSON。

背景（2026-10 实测）：
  盒子把对局面板做成了 CEF 页面
  ``https://hs-web-embed.lushi.163.com/client-jipaiqi/ladder-opp``，
  原生层每算完一次推荐就调用页面里的
  ``window.onUpdateLadderActionRecommend("<json>")``。

  所以只要盒子带 ``--remote-debugging-port=9222`` 启动，本模块就能：
    1. 通过 /json/list 找到 ladder-opp 页面；
    2. 用 CDP ``Runtime.evaluate`` 把那个函数包一层，记下最后一次 payload；
    3. 轮询 ``window.__boxRec``，把结构化推荐交给上层。

  纯标准库实现（socket + urllib），不引入 websocket 依赖。
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9222

# 页面优先级：游戏内真正出推荐的是 ladder-opp；ladder 只在盒子自己的窗口里用。
TARGET_HINTS = ("ladder-opp", "client-jipaiqi", "hs-web-embed")

# 在页面里把推荐入口包一层。用 defineProperty 的 setter 兜住“页面晚于我们挂载”
# 的情况：React 挂载时给 window.onUpdateLadderActionRecommend 赋值会被我们拦下。
HOOK_JS = r"""
(() => {
  if (window.__boxHooked) {
    return 'already:' + ((window.__boxRec && window.__boxRec.ts) || 0);
  }
  window.__boxHooked = true;
  window.__boxRec = { ts: 0, raw: null, parsed: null, err: null };
  const norm = (s) => String(s)
      .replaceAll('opp-target-hero', 'oppTargetHero')
      .replaceAll('opp-target', 'oppTarget')
      .replaceAll('target-hero', 'targetHero');
  const wrap = (fn) => function (s) {
    try {
      window.__boxRec.ts = Date.now();
      window.__boxRec.raw = s;
      window.__boxRec.parsed = JSON.parse(norm(s));
    } catch (e) {
      window.__boxRec.err = String(e);
    }
    return fn.apply(this, arguments);
  };
  let cur = window.onUpdateLadderActionRecommend;
  if (typeof cur === 'function') cur = wrap(cur);
  try {
    Object.defineProperty(window, 'onUpdateLadderActionRecommend', {
      configurable: true,
      get() { return cur; },
      set(fn) { cur = (typeof fn === 'function') ? wrap(fn) : fn; },
    });
  } catch (e) {
    window.__boxRec.err = 'defineProperty failed: ' + e;
    window.onUpdateLadderActionRecommend = wrap(function () {});
  }
  return 'ok';
})()
"""

_READ_JS = (
    "JSON.stringify({"
    "v: (window.__boxRec && window.__boxRec.ts) || 0,"
    "p: (window.__boxRec && window.__boxRec.parsed) || null"
    "})"
)


class CdpError(RuntimeError):
    """CDP 连接/读取失败。"""


@dataclass(frozen=True)
class RecommendationSnapshot:
    """一次推荐快照。version 是盒子推过来的毫秒时间戳，用来判断“有没有新推荐”。"""

    version: int
    payload: dict
    received_at: float

    @property
    def turn_number(self) -> Optional[int]:
        try:
            return int(self.payload.get("turnNum"))
        except (TypeError, ValueError):
            return None

    @property
    def actions(self) -> list:
        data = self.payload.get("data")
        return list(data) if isinstance(data, list) else []


class _WebSocket:
    """极简 RFC6455 客户端（只够 CDP 用：文本帧 + 掩码 + ping/pong）。"""

    def __init__(self, url: str, timeout: float = 2.0):
        if not url.startswith("ws://"):
            raise CdpError(f"unsupported ws url: {url}")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        host = host or DEFAULT_HOST
        port = int(port or 80)
        path = "/" + path
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n" % (path, host, port, key)
        )
        self.sock.sendall(request.encode("ascii"))
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("websocket handshake closed")
            buffer += chunk
        head, _, self._buffer = buffer.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b"101" not in status:
            raise CdpError(f"websocket handshake failed: {status!r}")
        self._fragment = b""
        self._fragment_opcode = None

    # -- send -----------------------------------------------------------
    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        size = len(payload)
        if size < 126:
            header.append(0x80 | size)
        elif size < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", size)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", size)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    # -- receive --------------------------------------------------------
    def _recv_exact(self, count: int) -> bytes:
        out = b""
        while len(out) < count:
            if self._buffer:
                take = self._buffer[: count - len(out)]
                self._buffer = self._buffer[len(take):]
                out += take
                continue
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CdpError("websocket closed")
            self._buffer = chunk
        return out

    def recv_text(self) -> str:
        while True:
            first, second = self._recv_exact(2)
            fin = first & 0x80
            opcode = first & 0x0F
            masked = second & 0x80
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._recv_exact(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._recv_exact(8))[0]
            if masked:
                mask = self._recv_exact(4)
                payload = bytes(
                    byte ^ mask[i % 4]
                    for i, byte in enumerate(self._recv_exact(size)))
            else:
                payload = self._recv_exact(size)

            if opcode == 0x8:
                raise CdpError("websocket close frame")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x0:
                self._fragment += payload
                if fin:
                    data, self._fragment = self._fragment, b""
                    if self._fragment_opcode == 0x1:
                        return data.decode("utf-8", "replace")
                continue
            if opcode == 0x1:
                if fin:
                    return payload.decode("utf-8", "replace")
                self._fragment = payload
                self._fragment_opcode = 0x1
                continue

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


class _Cdp:
    def __init__(self, ws_url: str, timeout: float = 2.0):
        self.ws = _WebSocket(ws_url, timeout=timeout)
        self._next_id = 0

    def call(self, method: str, params: Optional[dict] = None,
             timeout: float = 2.0) -> dict:
        self._next_id += 1
        message_id = self._next_id
        self.ws.send_text(json.dumps(
            {"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = json.loads(self.ws.recv_text())
            if message.get("id") == message_id:
                if "error" in message:
                    raise CdpError(f"{method}: {message['error']}")
                return message.get("result", {})
        raise CdpError(f"CDP timeout: {method}")

    def evaluate(self, expression: str, timeout: float = 2.0) -> Any:
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": False,
        }, timeout=timeout)
        if "exceptionDetails" in result:
            raise CdpError(
                "evaluate failed: "
                + json.dumps(result["exceptionDetails"], ensure_ascii=False)[:400])
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self.ws.close()


class CdpRecommendationSource:
    """从盒子 CEF 页面读取推荐快照；断线自动重连。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 2.0, retry_interval: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retry_interval = retry_interval
        self.last_error: Optional[str] = None
        self._cdp: Optional[_Cdp] = None
        self._target_url: Optional[str] = None
        self._next_retry_at = 0.0

    # -- public ---------------------------------------------------------
    def snapshot(self) -> Optional[RecommendationSnapshot]:
        if time.time() < self._next_retry_at:
            return None
        for attempt in range(2):
            try:
                if self._cdp is None:
                    self._connect()
                raw = self._cdp.evaluate(_READ_JS, timeout=self.timeout)
                data = json.loads(raw) if raw else {}
                version = int(data.get("v") or 0)
                payload = data.get("p")
                if version <= 0 or not isinstance(payload, dict):
                    return None
                self.last_error = None
                return RecommendationSnapshot(
                    version=version, payload=payload, received_at=time.time())
            except Exception as exc:  # 断线/页面跳转：重连一次
                self.last_error = f"{type(exc).__name__}: {exc}"
                self._reset()
                if attempt == 0:
                    continue
        self._next_retry_at = time.time() + self.retry_interval
        return None

    @property
    def target_url(self) -> Optional[str]:
        return self._target_url

    def close(self) -> None:
        self._reset()

    # -- internals ------------------------------------------------------
    def _reset(self) -> None:
        if self._cdp is not None:
            try:
                self._cdp.close()
            except Exception:
                pass
        self._cdp = None
        self._target_url = None

    def _targets(self) -> list:
        url = f"http://{self.host}:{self.port}/json/list"
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _pick_target(self, targets: list) -> dict:
        pages = [t for t in targets
                 if t.get("webSocketDebuggerUrl")
                 and (t.get("url") or "").startswith("http")]
        for hint in TARGET_HINTS:
            matched = [t for t in pages if hint in (t.get("url") or "")]
            if matched:
                return matched[0]
        if pages:
            return pages[0]
        raise CdpError("no CEF page target")

    def _connect(self) -> None:
        target = self._pick_target(self._targets())
        cdp = _Cdp(target["webSocketDebuggerUrl"], timeout=self.timeout)
        try:
            cdp.call("Runtime.enable", timeout=self.timeout)
            cdp.evaluate(HOOK_JS, timeout=self.timeout)
        except Exception:
            cdp.close()
            raise
        self._cdp = cdp
        self._target_url = target.get("url")
