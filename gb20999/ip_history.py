# -*- coding: utf-8 -*-
"""信号机 IP 历史记录。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_MAX_ITEMS = 30


def _history_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "ip_history.json"


def load_ip_history() -> list[str]:
    path = _history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()][: _MAX_ITEMS]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_ip_to_history(ip: str) -> list[str]:
    ip = ip.strip()
    if not ip:
        return load_ip_history()
    items = [ip] + [x for x in load_ip_history() if x != ip]
    items = items[:_MAX_ITEMS]
    try:
        _history_path().write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return items
