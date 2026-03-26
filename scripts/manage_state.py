#!/usr/bin/env python3
import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path

DEFAULT_STATE = {
    "enabled": False,
    "last_emit_ts": 0,
    "cooldown_until": 0,
    "today_emit_count": 0,
    "today_date": "",
}


def today_local() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_state(path: Path) -> dict:
    if not path.exists():
        return DEFAULT_STATE.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    state = DEFAULT_STATE.copy()
    state.update({k: v for k, v in data.items() if k in state})
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reset_day_if_needed(state: dict) -> bool:
    today = today_local()
    changed = False
    if state.get("today_date") != today:
        state["today_date"] = today
        state["today_emit_count"] = 0
        changed = True
    return changed


def cmd_init(path: Path):
    state = load_state(path)
    changed = reset_day_if_needed(state)
    save_state(path, state)
    return {"ok": True, "state": state, "changed": changed}


def cmd_activate(path: Path):
    state = load_state(path)
    reset_day_if_needed(state)
    state["enabled"] = True
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_deactivate(path: Path):
    state = load_state(path)
    reset_day_if_needed(state)
    state["enabled"] = False
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_precheck(path: Path, max_per_day: int):
    state = load_state(path)
    changed = reset_day_if_needed(state)
    now_ms = int(time.time() * 1000)
    reasons = []
    if not state.get("enabled"):
        reasons.append("disabled")
    if state.get("today_emit_count", 0) >= max_per_day:
        reasons.append("daily_limit_reached")
    if now_ms <= int(state.get("cooldown_until", 0) or 0):
        reasons.append("cooldown_active")
    if changed:
        save_state(path, state)
    return {
        "ok": True,
        "should_consider": len(reasons) == 0,
        "reasons": reasons,
        "state": state,
        "now_ms": now_ms,
    }


def cmd_mark_sent(path: Path, min_minutes: int, max_minutes: int):
    state = load_state(path)
    reset_day_if_needed(state)
    now_ms = int(time.time() * 1000)
    cooldown_minutes = random.randint(min_minutes, max_minutes)
    state["last_emit_ts"] = now_ms
    state["cooldown_until"] = now_ms + cooldown_minutes * 60 * 1000
    state["today_emit_count"] = int(state.get("today_emit_count", 0)) + 1
    save_state(path, state)
    return {
        "ok": True,
        "state": state,
        "cooldown_minutes": cooldown_minutes,
    }


def cmd_mark_failed(path: Path):
    state = load_state(path)
    reset_day_if_needed(state)
    save_state(path, state)
    return {"ok": True, "state": state}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "activate", "deactivate", "precheck", "mark-sent", "mark-failed"])
    parser.add_argument("--state", required=True)
    parser.add_argument("--max-per-day", type=int, default=3)
    parser.add_argument("--min-minutes", type=int, default=20)
    parser.add_argument("--max-minutes", type=int, default=90)
    args = parser.parse_args()

    path = Path(args.state).expanduser()

    if args.command == "init":
        result = cmd_init(path)
    elif args.command == "activate":
        result = cmd_activate(path)
    elif args.command == "deactivate":
        result = cmd_deactivate(path)
    elif args.command == "precheck":
        result = cmd_precheck(path, args.max_per_day)
    elif args.command == "mark-sent":
        result = cmd_mark_sent(path, args.min_minutes, args.max_minutes)
    else:
        result = cmd_mark_failed(path)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
