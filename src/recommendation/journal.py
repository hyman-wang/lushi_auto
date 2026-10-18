# -*- coding: utf-8 -*-
"""Append-only recommendation/execution journal.

Every distinct box recommendation read by CdpRecommendationSource is written
to ``log/recommendation_journal.jsonl``; the latest snapshot is mirrored to
``log/recommendation_latest.json``.  Execution outcomes are appended by the
flow layer so a later diagnosis can answer "was this recommendation executed,
and in which turn?" without relying on the in-memory page state.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "log"
JOURNAL_PATH = LOG_DIR / "recommendation_journal.jsonl"
LATEST_PATH = LOG_DIR / "recommendation_latest.json"

_LOCK = threading.Lock()
_SEEN: set = set()
_MAX_JOURNAL_BYTES = 2 * 1024 * 1024
_MAX_LINES = 2000


def _trim_if_needed() -> None:
    try:
        if JOURNAL_PATH.stat().st_size <= _MAX_JOURNAL_BYTES:
            return
        lines = JOURNAL_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        JOURNAL_PATH.write_text(
            "\n".join(lines[-_MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _append(event: dict) -> None:
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with _LOCK:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(JOURNAL_PATH, "a", encoding="utf-8") as fh:
                fh.write(line)
            _trim_if_needed()
            if event.get("event") == "recommendation":
                LATEST_PATH.write_text(
                    json.dumps(event, ensure_ascii=False, indent=1),
                    encoding="utf-8")
        except Exception:
            pass


def record_snapshot(snapshot, scope: str = "cdp") -> None:
    """Record a new recommendation version once (thread-safe)."""
    version = getattr(snapshot, "version", None)
    if version is None:
        return
    key = int(version)
    with _LOCK:
        if key in _SEEN:
            return
        if len(_SEEN) > 5000:
            _SEEN.clear()
        _SEEN.add(key)
    payload = getattr(snapshot, "payload", {}) or {}
    _append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": "recommendation",
        "scope": scope,
        "version": version,
        "turn": getattr(snapshot, "turn_number", None),
        "option_id": payload.get("optionId"),
        "action_name": (payload.get("data") or [{}])[0].get("actionName")
        if isinstance(payload.get("data"), list) and payload.get("data") else None,
        "payload": payload,
    })


def record_execution(scope: str, version, instruction: str, status: str,
                     detail: str = "") -> None:
    """Record what the automation actually did with a recommendation."""
    _append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": "execution",
        "scope": scope,
        "version": version,
        "instruction": instruction,
        "status": status,
        "detail": detail,
    })
