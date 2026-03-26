#!/usr/bin/env python3
import argparse
import json
import math
import random
import time
import uuid
from pathlib import Path

PROFILES = {
    "惜墨如金型": {
        "threshold": 0.74,
        "cooldown_min": 90,
        "cooldown_max": 240,
        "freshness_hours": 30,
    },
    "闷骚型": {
        "threshold": 0.62,
        "cooldown_min": 45,
        "cooldown_max": 150,
        "freshness_hours": 24,
    },
    "正常人型": {
        "threshold": 0.52,
        "cooldown_min": 20,
        "cooldown_max": 90,
        "freshness_hours": 18,
    },
    "话痨型": {
        "threshold": 0.40,
        "cooldown_min": 8,
        "cooldown_max": 45,
        "freshness_hours": 12,
    },
}

DEFAULT_STATE = {
    "enabled": False,
    "style_profile": "闷骚型",
    "last_emit_ts": 0,
    "cooldown_until": 0,
    "traces": [],
}

TRACE_KINDS = {"unfinished", "correction", "extension", "echo"}


def now_ms() -> int:
    return int(time.time() * 1000)


def load_state(path: Path) -> dict:
    if not path.exists():
        return DEFAULT_STATE.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    state = DEFAULT_STATE.copy()
    if isinstance(data, dict):
        state.update({k: v for k, v in data.items() if k in state})
    if state.get("style_profile") not in PROFILES:
        state["style_profile"] = DEFAULT_STATE["style_profile"]
    if not isinstance(state.get("traces"), list):
        state["traces"] = []
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def prune_and_decay_traces(state: dict, now: int | None = None) -> bool:
    now = now or now_ms()
    changed = False
    kept = []
    for raw in state.get("traces", []):
        if not isinstance(raw, dict):
            changed = True
            continue
        trace = dict(raw)
        if trace.get("spent"):
            changed = True
            continue
        theme = str(trace.get("theme", "")).strip()
        kind = str(trace.get("kind", "echo")).strip()
        if not theme:
            changed = True
            continue
        if kind not in TRACE_KINDS:
            kind = "echo"
            changed = True
        weight = float(trace.get("weight", 0.4) or 0.4)
        created_ts = int(trace.get("created_ts", now))
        touched_ts = int(trace.get("touched_ts", created_ts))
        age_hours = max(0.0, (now - touched_ts) / 3600000)
        decayed = weight * math.exp(-0.085 * age_hours)
        decayed = clamp(decayed, 0.0, 1.0)
        if decayed < 0.14:
            changed = True
            continue
        trace.update(
            {
                "id": trace.get("id") or str(uuid.uuid4())[:8],
                "theme": theme,
                "kind": kind,
                "weight": round(decayed, 4),
                "created_ts": created_ts,
                "touched_ts": touched_ts,
                "spent": False,
            }
        )
        kept.append(trace)
        if abs(decayed - weight) > 1e-6:
            changed = True
    kept.sort(key=lambda x: (x.get("weight", 0), x.get("touched_ts", 0)), reverse=True)
    if len(kept) > 3:
        kept = kept[:3]
        changed = True
    if kept != state.get("traces", []):
        state["traces"] = kept
        changed = True
    return changed


def cmd_init(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_activate(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    state["enabled"] = True
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_deactivate(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    state["enabled"] = False
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_set_style(path: Path, profile: str):
    state = load_state(path)
    prune_and_decay_traces(state)
    if profile not in PROFILES:
        return {"ok": False, "error": "unknown_profile", "allowed": list(PROFILES.keys())}
    state["style_profile"] = profile
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_precheck(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    now = now_ms()
    reasons = []
    if not state.get("enabled"):
        reasons.append("disabled")
    if now <= int(state.get("cooldown_until", 0) or 0):
        reasons.append("cooldown_active")
    if not state.get("traces"):
        reasons.append("no_live_traces")
    save_state(path, state)
    return {
        "ok": True,
        "should_consider": len([r for r in reasons if r not in {"no_live_traces"}]) == 0,
        "reasons": reasons,
        "state": state,
        "profiles": list(PROFILES.keys()),
    }


def cmd_upsert_trace(path: Path, theme: str, kind: str, weight: float):
    state = load_state(path)
    prune_and_decay_traces(state)
    theme = (theme or "").strip()
    if not theme:
        return {"ok": False, "error": "empty_theme"}
    kind = kind if kind in TRACE_KINDS else "echo"
    weight = clamp(float(weight), 0.18, 0.95)
    now = now_ms()
    merged = False
    traces = []
    for trace in state.get("traces", []):
        if trace.get("theme") == theme and trace.get("kind") == kind and not merged:
            trace = dict(trace)
            trace["weight"] = round(max(float(trace.get("weight", 0.2)), weight), 4)
            trace["touched_ts"] = now
            merged = True
        traces.append(trace)
    if not merged:
        traces.append(
            {
                "id": str(uuid.uuid4())[:8],
                "theme": theme,
                "kind": kind,
                "weight": round(weight, 4),
                "created_ts": now,
                "touched_ts": now,
                "spent": False,
            }
        )
    state["traces"] = traces
    prune_and_decay_traces(state, now)
    save_state(path, state)
    return {"ok": True, "state": state}


def impulse_score(trace: dict, profile: dict, quietness: float = 1.0) -> float:
    now = now_ms()
    age_hours = max(0.0, (now - int(trace.get("touched_ts", now))) / 3600000)
    freshness = math.exp(-age_hours / max(profile["freshness_hours"], 1))
    stochasticity = random.uniform(0.82, 1.18)
    base = float(trace.get("weight", 0.2)) * freshness * clamp(quietness, 0.4, 1.2)
    return base * stochasticity


def cmd_choose_trace(path: Path, quietness: float):
    state = load_state(path)
    prune_and_decay_traces(state)
    profile_name = state.get("style_profile", DEFAULT_STATE["style_profile"])
    profile = PROFILES[profile_name]
    threshold = profile["threshold"]
    scored = []
    for trace in state.get("traces", []):
        score = impulse_score(trace, profile, quietness=quietness)
        scored.append({"trace": trace, "score": round(score, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    chosen = scored[0] if scored and scored[0]["score"] >= threshold else None
    save_state(path, state)
    return {
        "ok": True,
        "style_profile": profile_name,
        "threshold": threshold,
        "quietness": quietness,
        "chosen": chosen,
        "scored": scored[:3],
        "state": state,
    }


def cmd_mark_sent(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    profile = PROFILES[state.get("style_profile", DEFAULT_STATE["style_profile"])]
    now = now_ms()
    cooldown_minutes = random.randint(profile["cooldown_min"], profile["cooldown_max"])
    state["last_emit_ts"] = now
    state["cooldown_until"] = now + cooldown_minutes * 60 * 1000
    traces = state.get("traces", [])
    if traces:
        # soften the top trace rather than deleting everything
        top = dict(traces[0])
        top["weight"] = round(max(0.0, float(top.get("weight", 0.3)) * 0.42), 4)
        top["touched_ts"] = now
        if top["weight"] < 0.16:
            top["spent"] = True
        traces[0] = top
        state["traces"] = traces
    prune_and_decay_traces(state, now)
    save_state(path, state)
    return {"ok": True, "state": state, "cooldown_minutes": cooldown_minutes}


def cmd_mark_failed(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_inspect(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    save_state(path, state)
    return {"ok": True, "state": state, "profiles": PROFILES}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "init",
            "activate",
            "deactivate",
            "set-style",
            "precheck",
            "upsert-trace",
            "choose-trace",
            "mark-sent",
            "mark-failed",
            "inspect",
        ],
    )
    parser.add_argument("--state", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--theme")
    parser.add_argument("--kind")
    parser.add_argument("--weight", type=float, default=0.46)
    parser.add_argument("--quietness", type=float, default=1.0)
    args = parser.parse_args()

    path = Path(args.state).expanduser()

    if args.command == "init":
        result = cmd_init(path)
    elif args.command == "activate":
        result = cmd_activate(path)
    elif args.command == "deactivate":
        result = cmd_deactivate(path)
    elif args.command == "set-style":
        result = cmd_set_style(path, args.profile or DEFAULT_STATE["style_profile"])
    elif args.command == "precheck":
        result = cmd_precheck(path)
    elif args.command == "upsert-trace":
        result = cmd_upsert_trace(path, args.theme or "", args.kind or "echo", args.weight)
    elif args.command == "choose-trace":
        result = cmd_choose_trace(path, args.quietness)
    elif args.command == "mark-sent":
        result = cmd_mark_sent(path)
    elif args.command == "mark-failed":
        result = cmd_mark_failed(path)
    else:
        result = cmd_inspect(path)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
