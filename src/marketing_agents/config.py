from __future__ import annotations

import json
import os
from datetime import timezone as FixedTimezone
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv



ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
load_dotenv(ROOT / ".env")
ACTION_LOG_PATH = DATA_DIR / "action_log.json"


def timezone():
    configured = os.getenv("TIMEZONE", "Asia/Calcutta")
    for candidate in (configured, "Asia/Kolkata", "UTC"):
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    if configured in {"Asia/Calcutta", "Asia/Kolkata"}:
        return FixedTimezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
    return FixedTimezone.utc


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def append_action(agent: str, action: str, result: str, details: dict[str, Any] | None = None) -> None:
    if ACTION_LOG_PATH.exists():
        log = read_json(ACTION_LOG_PATH)
    else:
        log = []

    from datetime import datetime

    log.append(
        {
            "timestamp": datetime.now(timezone()).isoformat(timespec="seconds"),
            "agent": agent,
            "action": action,
            "result": result,
            "details": details or {},
        }
    )
    write_json(ACTION_LOG_PATH, log)

