#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box_recommend_cdp.py — 通过 CEF DevTools(CDP) 读取炉石盒子「打法参考A/B」数据。

背景（本次逆向结论）：
  盒子把「推荐打法」面板做成了 CEF 网页：
      https://hs-web-embed.lushi.163.com/client-jipaiqi/ladder
  原生层(HSAng.exe)把推荐数据以 JSON 字符串推给页面：
      window.onUpdateLadderActionRecommend("<json>")
  页面再用 React 渲染成「打法参考A / 打法参考B」两段文字。

  所以只要用 DevTools 连上这个页面，hook 住那个函数，就能拿到结构化 JSON，
  不用再 OCR。

前提：
  1. HSAng.exe 需要管理员权限启动（manifest requireAdministrator）。
  2. 用 --remote-debugging-port=9222 启动盒子，例如（管理员 PowerShell）：
         Start-Process 'D:\\炉石传说盒子\\HSAng.exe' -ArgumentList '--remote-debugging-port=9222' -Verb RunAs
     然后浏览器打开 http://127.0.0.1:9222/json/list 确认能看到页面。
     若列表为空/连不上，说明该 CEF 构建没有开放调试端口（见 REPORT.md 的备选方案）。

用法：
    python box_recommend_cdp.py list                 # 列出所有 CEF 页面
    python box_recommend_cdp.py watch                # 挂 hook，持续打印新推荐
    python box_recommend_cdp.py dom                  # 直接读面板 DOM 文本
    python box_recommend_cdp.py eval "1+1"           # 在页面里执行任意 JS
    python box_recommend_cdp.py self-test            # 自检 WebSocket 实现

仅用标准库，无第三方依赖。
"""

import argparse
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request

DEFAULT_PORT = 9222
TARGET_HINT = "hs-web-embed"
LADDER_HINT = "client-jipaiqi"


# --------------------------------------------------------------------------
# 极简 WebSocket 客户端（RFC6455，客户端掩码，够 CDP 用）
# --------------------------------------------------------------------------
class WebSocket:
    def __init__(self, url, timeout=10.0):
        assert url.startswith("ws://"), url
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        host = host or "127.0.0.1"
        port = int(port or 80)
        path = "/" + path
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n" % (path, host, port, key)
        )
        self.sock.sendall(req.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("握手失败：连接被关闭")
            buf += chunk
        head, _, self.buf = buf.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b"101" not in status:
            raise ConnectionError("握手失败：%r" % status)
        self._frag = b""
        self._frag_op = None

    # -- 发送 -----------------------------------------------------------
    def send_text(self, text):
        self._send_frame(0x1, text.encode("utf-8"))

    def _send_frame(self, opcode, payload):
        header = bytearray()
        header.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    # -- 接收 -----------------------------------------------------------
    def _recv_exact(self, n):
        out = b""
        while len(out) < n:
            if self.buf:
                take = self.buf[:n - len(out)]
                self.buf = self.buf[len(take):]
                out += take
                continue
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("连接已关闭")
            self.buf = chunk
        return out

    def recv_text(self):
        while True:
            b1, b2 = self._recv_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            if masked:
                mask = self._recv_exact(4)
                payload = bytes(
                    b ^ mask[i % 4] for i, b in enumerate(self._recv_exact(n)))
            else:
                payload = self._recv_exact(n)

            if opcode == 0x8:          # close
                raise ConnectionError("对端关闭连接")
            if opcode == 0x9:          # ping
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:          # pong
                continue
            if opcode == 0x0:          # continuation
                self._frag += payload
                if fin:
                    data, self._frag = self._frag, b""
                    if self._frag_op == 0x1:
                        return data.decode("utf-8", "replace")
                continue
            if opcode == 0x1:          # text
                if fin:
                    return payload.decode("utf-8", "replace")
                self._frag = payload
                self._frag_op = 0x1
                continue
            # 其它（binary 等）忽略

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# CDP 封装
# --------------------------------------------------------------------------
class CDP:
    def __init__(self, ws_url):
        self.ws = WebSocket(ws_url)
        self.next_id = 0

    def call(self, method, params=None, timeout=15.0):
        self.next_id += 1
        mid = self.next_id
        self.ws.send_text(json.dumps(
            {"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv_text())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, msg["error"]))
                return msg.get("result", {})
            # 其它事件（Runtime.consoleAPICalled 等）先丢弃
        raise TimeoutError("CDP 调用超时: %s" % method)

    def evaluate(self, expression, await_promise=False):
        res = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
            "userGesture": False,
        })
        if "exceptionDetails" in res:
            raise RuntimeError(json.dumps(
                res["exceptionDetails"], ensure_ascii=False)[:800])
        return res.get("result", {}).get("value")

    def close(self):
        self.ws.close()


def list_targets(port):
    url = "http://127.0.0.1:%d/json/list" % port
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise SystemExit(
            "连不上 127.0.0.1:%d 的 DevTools（%s）。\n"
            "  · 盒子是否用 --remote-debugging-port=%d 启动了？\n"
            "  · 这个 CEF 构建可能没有开放调试端口，见 REPORT.md 的备选方案。"
            % (port, e, port))


def pick_target(targets, needle=LADDER_HINT):
    pages = [t for t in targets if t.get("type") == "page"
             and t.get("webSocketDebuggerUrl")]
    if not pages:
        pages = [t for t in targets if t.get("webSocketDebuggerUrl")]
    preferred = [t for t in pages if needle in (t.get("url") or "")]
    if not preferred:
        preferred = [t for t in pages if TARGET_HINT in (t.get("url") or "")]
    return (preferred or pages or [None])[0]


# --------------------------------------------------------------------------
# 注入到页面里的脚本
# --------------------------------------------------------------------------
HOOK_JS = r"""
(() => {
  if (window.__boxHooked) {
    return 'already:' + (window.__boxRec && window.__boxRec.ts || 0);
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

DOM_JS = r"""
(() => {
  const out = [];
  document.querySelectorAll('.recommend-playstyle-action').forEach((el) => {
    const title = el.querySelector('.recommend-playstyle-action-title');
    out.push({
      title: title ? title.innerText.trim() : '',
      text: el.innerText.trim(),
    });
  });
  return JSON.stringify(out);
})()
"""


# actionName -> 盒子面板上的中文（与 JS 里 ke() 的渲染逻辑一致，实测校正）
ACTION_LABELS = {
    "end_turn": "结束回合",
    "play_minion": "打出{n}号位随从",
    "play_special": "打出{n}号位法术",
    "play_weapon": "打出{n}号位武器",
    "play_hero": "打出{n}号位英雄",
    "play_location": "打出{n}号位地标",
    "forge": "锻造{n}号位卡牌",
    "trade": "交易{n}号位卡牌",
    "prepare": "预备{n}号位卡牌",
    "hero_attack": "操作我方英雄攻击",
    "minion_attack": "操作{n}号位随从攻击",
    "hero_skill": "使用英雄技能",
    "titan_power": "操作{n}号位泰坦",
    "location_power": "操作{n}号位地标",
    "launch_starship": "发射{n}号位星舰",
    "common_action": "操作{n}号位卡牌",
    "choice": "选择{side}{n}号位卡牌",
    "replace": "替换{n}号位卡牌",
    "discard": "舍弃卡牌",
    "choose": "选择卡牌",
}


def _pos(obj):
    if not isinstance(obj, dict):
        return ""
    return obj.get("ZONE_POSITION", obj.get("position", ""))


def summarize(parsed):
    """把 JSON 转成给人看的一行行文本（便于和 OCR 结果对照）。"""
    lines = []
    data = (parsed or {}).get("data") or []
    for i, item in enumerate(data):
        letter = chr(ord("A") + i) if i < 26 else str(i)
        name = item.get("actionName")
        card = item.get("card")
        cards = card if isinstance(card, list) else ([card] if card else [])
        target = item.get("target") or item.get("oppTarget")
        # 位置：优先取目标/卡牌的 ZONE_POSITION，其次 item.position
        pos = ""
        if name == "choice":
            pos = _pos(target)
        elif cards:
            pos = _pos(cards[0])
        if not pos:
            pos = item.get("position", "")

        if name == "replace":
            names = "、".join(
                "%s号位%s" % (_pos(c), c.get("cardName") or c.get("cardId") or "?")
                for c in cards)
            lines.append("%s. 替换 %s" % (letter, names or "（无）"))
            continue

        label = ACTION_LABELS.get(name, name)
        line = str(label).format(n=pos, side="我方")

        extra = []
        if item.get("targetHero") or item.get("oppTargetHero"):
            side = "对方" if item.get("oppTargetHero") else "我方"
            extra.append("目标是%s英雄" % side)
        elif target:
            side = "对方" if item.get("oppTarget") else "我方"
            extra.append("目标是%s%s号位" % (side, _pos(target) or "?"))
        if item.get("subOption"):
            sub = item["subOption"]
            extra.append("选择卡牌 %s" % (sub.get("cardName") or sub.get("cardId")))
        # 渲染逻辑里只有 play_minion 会画「放置于…号位」那一行
        if name == "play_minion":
            where = "对手" if item.get("using_disguised") == 1 else "我方"
            extra.append("放置于%s%s号位" % (where, item.get("position", "")))
        card_name = cards[0].get("cardName") if cards else None
        if card_name:
            extra.insert(0, card_name)
        lines.append("%s. %s%s" % (
            letter, line, ("（%s）" % "，".join(extra)) if extra else ""))
    return lines


def cmd_list(port):
    targets = list_targets(port)
    for t in targets:
        print("%-9s %-45s %s" % (t.get("type"), (t.get("url") or "")[:45],
                                 t.get("title", "")[:40]))
        print("          ws=%s" % t.get("webSocketDebuggerUrl"))
    if not targets:
        print("没有页面。盒子是否用 --remote-debugging-port=%d 启动？" % port)


def cmd_eval(port, expr):
    target = pick_target(list_targets(port))
    if not target:
        print("没找到目标页面")
        return 2
    cdp = CDP(target["webSocketDebuggerUrl"])
    try:
        print(json.dumps(cdp.evaluate(expr), ensure_ascii=False, indent=2))
    finally:
        cdp.close()
    return 0


def cmd_dom(port):
    target = pick_target(list_targets(port))
    if not target:
        print("没找到目标页面")
        return 2
    cdp = CDP(target["webSocketDebuggerUrl"])
    try:
        raw = cdp.evaluate(DOM_JS)
        for item in json.loads(raw or "[]"):
            print("== %s ==" % item["title"])
            print(item["text"])
    finally:
        cdp.close()
    return 0


def cmd_watch(port, raw_json=False, interval=0.5):
    targets = list_targets(port)
    target = pick_target(targets)
    if not target:
        print("没找到目标页面。先确认盒子以 --remote-debugging-port 启动，"
              "并且已经进入对局/打开了面板。")
        return 2
    print("attach: %s\n          %s" % (target.get("url"), target["webSocketDebuggerUrl"]))
    cdp = CDP(target["webSocketDebuggerUrl"])
    try:
        cdp.call("Runtime.enable")
        print("hook:", cdp.evaluate(HOOK_JS))
        last_ts = 0
        print("等待推荐数据…（Ctrl+C 退出）")
        while True:
            try:
                cur = cdp.evaluate(
                    "(window.__boxRec && window.__boxRec.ts) || 0")
            except Exception as e:
                print("读取失败，重连中: %s" % e)
                time.sleep(2)
                continue
            if isinstance(cur, (int, float)) and cur > last_ts:
                last_ts = cur
                payload = cdp.evaluate(
                    "JSON.stringify(window.__boxRec.parsed)")
                parsed = json.loads(payload) if payload else {}
                stamp = time.strftime("%H:%M:%S")
                print("\n[%s] 收到推荐 #%d  status=%s" % (
                    stamp, int(cur), parsed.get("status")))
                if raw_json:
                    print(json.dumps(parsed, ensure_ascii=False, indent=2))
                else:
                    for line in summarize(parsed):
                        print("   ", line)
                    if not summarize(parsed):
                        print("    (data 为空)")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        cdp.close()
    return 0


# --------------------------------------------------------------------------
# 自检：本地起一个假 WebSocket 服务端，验证握手/掩码/分片基础路径
# --------------------------------------------------------------------------
def self_test():
    import hashlib
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def server():
        conn, _ = srv.accept()
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(4096)
        head = data.split(b"\r\n\r\n")[0].decode()
        key = ""
        for line in head.split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        conn.sendall((
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
        # 读一帧（客户端掩码）
        b1, b2 = conn.recv(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", conn.recv(2))[0]
        mask = conn.recv(4)
        payload = b""
        while len(payload) < n:
            payload += conn.recv(n - len(payload))
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        # 回一帧（服务端不掩码）
        out = b"\x81" + (bytes([len(payload)]) if len(payload) < 126
                         else b"\x7e" + struct.pack(">H", len(payload))) + payload
        conn.sendall(out)
        conn.close()

    th = threading.Thread(target=server, daemon=True)
    th.start()
    ws = WebSocket("ws://127.0.0.1:%d/devtools/page/TEST" % port)
    ws.send_text("hello-cdp")
    got = ws.recv_text()
    ws.close()
    srv.close()
    ok = got == "hello-cdp"
    print("self-test:", "PASS" if ok else "FAIL (%r)" % got)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("dom")
    p_watch = sub.add_parser("watch")
    p_watch.add_argument("--raw", action="store_true", help="打印完整 JSON")
    p_watch.add_argument("--interval", type=float, default=0.5)
    p_eval = sub.add_parser("eval")
    p_eval.add_argument("expr")
    sub.add_parser("self-test")

    args = ap.parse_args()
    if args.cmd == "list":
        cmd_list(args.port)
        return 0
    if args.cmd == "dom":
        return cmd_dom(args.port)
    if args.cmd == "watch":
        return cmd_watch(args.port, args.raw, args.interval)
    if args.cmd == "eval":
        return cmd_eval(args.port, args.expr)
    if args.cmd == "self-test":
        return self_test()
    return 1


if __name__ == "__main__":
    sys.exit(main())
