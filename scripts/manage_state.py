#!/usr/bin/env python3
import argparse
import json
import math
import random
import re
import time
import uuid
from pathlib import Path

CONFIG = {
    "impulse_threshold": 0.58,
    "cooldown_min": 25,
    "cooldown_max": 110,
    "freshness_hours": 20,
    # Relative recency weighting inside the current trace pool:
    # newer traces are favored, older traces remain possible if association is strong.
    "recency_half_life_hours": 22,
    "recency_weight": 0.24,
    # Cross-context association bonus:
    # if a trace is re-lit by multiple context fragments, it gets a soft bump.
    "association_weight": 0.20,
    "association_min_overlap": 0.14,
}

DEFAULT_STATE = {
    "enabled": False,
    "last_emit_ts": 0,
    "cooldown_until": 0,
    "traces": [],
    "last_sent_message_id": None,
    # Full emission record for the most recently selected proactive message.
    # Stored at choose-trace time (source context + trace metadata) and updated
    # at mark-sent time (final sent sentence). Survives even if send ultimately fails.
    # Fields:
    #   - trace_id, theme, kind, chosen_score, chosen_at_ts  (from choose-trace)
    #   - source_snippets: list of raw context strings that drove the trace selection
    #   - associated_contexts: top linked context fragments with overlap scores
    #   - concrete_topic: human-readable topic/object the message refers to
    #   - why_chosen: short explanation of why this trace beat others at this moment
    #   - sent_text: the final sentence actually sent (filled in at mark-sent time)
    #   - sent_at_ts: timestamp of successful send (filled in at mark-sent time)
    #   - message_id: Telegram message_id of the sent message (filled in at mark-sent time)
    "last_sent_emission": None,
    # Last N sent proactive emissions: each entry has theme + text (not just metadata).
    # Used for anti-repeat / near-duplicate detection before sending a new candidate.
    "recent_emissions": [],
}

# Maximum number of recent emissions to keep for anti-repeat comparison.
MAX_RECENT_EMISSIONS = 5

TRACE_KINDS = {"unfinished", "correction", "extension", "echo"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")


def now_ms() -> int:
    return int(time.time() * 1000)


def _safe_strip(text: str | None, limit: int = 240) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit]


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for tok in _TOKEN_RE.findall((text or "").lower()):
        if not tok:
            continue
        if tok.isascii():
            if len(tok) <= 1:
                continue
            tokens.add(tok)
            continue

        # Chinese chunk: keep short chunk, and also add bigrams for softer overlap.
        # This avoids requiring exact full-phrase matches while remaining lightweight.
        if len(tok) <= 2:
            tokens.add(tok)
            continue
        for i in range(len(tok) - 1):
            tokens.add(tok[i:i + 2])
    return tokens


def _token_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    # Soften denominator so partial thematic overlap can still surface.
    denom = max(1, min(len(a), len(b), 6))
    return min(1.0, inter / denom)


def _relative_recency_weight(trace: dict, newest_touched_ts: int | None) -> float:
    if not newest_touched_ts:
        return 1.0
    touched = int(trace.get("touched_ts", newest_touched_ts))
    gap_hours = max(0.0, (newest_touched_ts - touched) / 3600000)
    half_life = max(1.0, float(CONFIG.get("recency_half_life_hours", 22)))
    # Half-life decay: each half_life hours older halves recency contribution.
    recency = math.exp(-math.log(2) * (gap_hours / half_life))
    return float(max(0.08, min(1.0, recency)))


def _association_score(trace: dict, context_fragments: list[str]) -> tuple[float, list[dict]]:
    """
    Return (association_strength, associated_contexts).
    association_strength favors:
    - stronger lexical overlap with trace theme
    - overlap appearing in multiple fragments (cross-context re-lighting)
    """
    theme = _safe_strip(str(trace.get("theme", "")), limit=300)
    theme_tokens = _tokenize(theme)
    if not theme_tokens or not context_fragments:
        return 0.0, []

    hits: list[dict] = []
    for frag in context_fragments:
        clean = _safe_strip(frag, limit=300)
        if not clean:
            continue
        overlap = _token_overlap(theme_tokens, _tokenize(clean))
        hits.append({
            "snippet": clean,
            "overlap": round(overlap, 4),
        })

    if not hits:
        return 0.0, []

    hits.sort(key=lambda x: x["overlap"], reverse=True)
    top = hits[:3]
    max_overlap = top[0]["overlap"]
    avg_overlap = sum(x["overlap"] for x in top) / len(top)

    linked_count = len([h for h in hits if h["overlap"] >= CONFIG["association_min_overlap"]])
    # Bonus when one trace is linked by multiple context fragments.
    # Keeps it soft: 0.0 ~ 0.12
    cross_context_bonus = 0.06 * max(0, min(2, linked_count - 1))

    strength = 0.68 * max_overlap + 0.32 * avg_overlap + cross_context_bonus
    strength = float(max(0.0, min(1.0, strength)))

    associated = [
        {"snippet": h["snippet"], "overlap": h["overlap"]}
        for h in top
        if h["overlap"] >= CONFIG["association_min_overlap"]
    ]
    return strength, associated


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
    if not isinstance(state.get("traces"), list):
        state["traces"] = []
    if not isinstance(state.get("recent_emissions"), list):
        state["recent_emissions"] = []
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
        "config": CONFIG,
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


def impulse_score(trace: dict, quietness: float = 1.0) -> float:
    now = now_ms()
    age_hours = max(0.0, (now - int(trace.get("touched_ts", now))) / 3600000)
    freshness = math.exp(-age_hours / max(CONFIG["freshness_hours"], 1))
    stochasticity = random.uniform(0.82, 1.18)
    base = float(trace.get("weight", 0.2)) * freshness * clamp(quietness, 0.4, 1.2)
    return base * stochasticity


def cmd_choose_trace(path: Path, quietness: float,
                     source_snippets: list[str] | None = None,
                     association_snippets: list[str] | None = None,
                     concrete_topic: str | None = None,
                     why_chosen: str | None = None):
    state = load_state(path)
    prune_and_decay_traces(state)
    threshold = CONFIG["impulse_threshold"]

    context_pool: list[str] = []
    if association_snippets:
        context_pool.extend([s for s in association_snippets if (s or "").strip()])
    if source_snippets:
        context_pool.extend([s for s in source_snippets if (s or "").strip()])
    if concrete_topic:
        context_pool.append(concrete_topic)

    traces = state.get("traces", [])
    newest_touched = max([int(t.get("touched_ts", 0) or 0) for t in traces], default=0)

    scored = []
    for trace in traces:
        base = impulse_score(trace, quietness=quietness)
        recency_bias = _relative_recency_weight(trace, newest_touched)
        assoc_strength, associated_contexts = _association_score(trace, context_pool)

        score = (
            base * ((1 - CONFIG["recency_weight"]) + CONFIG["recency_weight"] * recency_bias)
            + CONFIG["association_weight"] * assoc_strength
        )
        score = clamp(score, 0.0, 1.4)

        scored.append(
            {
                "trace": trace,
                "score": round(score, 4),
                "base_score": round(base, 4),
                "recency_bias": round(recency_bias, 4),
                "association_strength": round(assoc_strength, 4),
                "associated_contexts": associated_contexts,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    chosen = scored[0] if scored and scored[0]["score"] >= threshold else None

    # Persist the full emission context immediately when a trace is chosen,
    # so the source is recoverable even if the actual send fails/crashes.
    # sent_text / sent_at_ts / message_id are filled in later at mark-sent time.
    if chosen:
        state["last_sent_emission"] = {
            "trace_id": chosen["trace"].get("id"),
            "theme": chosen["trace"].get("theme"),
            "kind": chosen["trace"].get("kind"),
            "chosen_score": chosen["score"],
            "chosen_at_ts": now_ms(),
            "base_score": chosen.get("base_score"),
            "recency_bias": chosen.get("recency_bias"),
            "association_strength": chosen.get("association_strength"),
            "associated_contexts": chosen.get("associated_contexts", []),
            # Rich context: what triggered this trace, why it won, and what it refers to
            "source_snippets": source_snippets or [],
            "concrete_topic": (concrete_topic or "").strip(),
            "why_chosen": (why_chosen or "").strip(),
            # Filled in at mark-sent time
            "sent_text": None,
            "sent_at_ts": None,
            "message_id": None,
        }

    save_state(path, state)
    return {
        "ok": True,
        "threshold": threshold,
        "quietness": quietness,
        "context_pool_size": len(context_pool),
        "chosen": chosen,
        "scored": scored[:3],
        "state": state,
        "config": CONFIG,
    }


def _add_recent_emission(state: dict, theme: str, text: str, now: int) -> None:
    """Append a sent emission to recent_emissions; trim to MAX_RECENT_EMISSIONS."""
    emissions = list(state.get("recent_emissions", []))
    emissions.append({
        "theme": theme or "",
        "text": text or "",
        "sent_at_ts": now,
    })
    # Keep only the last MAX_RECENT_EMISSIONS
    state["recent_emissions"] = emissions[-MAX_RECENT_EMISSIONS:]


def cmd_mark_sent(path: Path, message_id: int | None = None,
                  emission_text: str | None = None, emission_theme: str | None = None):
    state = load_state(path)
    prune_and_decay_traces(state)
    now = now_ms()
    cooldown_minutes = random.randint(CONFIG["cooldown_min"], CONFIG["cooldown_max"])
    state["last_emit_ts"] = now
    state["cooldown_until"] = now + cooldown_minutes * 60 * 1000
    state["last_sent_message_id"] = message_id
    # Record text + theme for anti-repeat if provided
    if emission_text:
        _add_recent_emission(state, emission_theme or "", emission_text, now)
    # Update last_sent_emission with the final sent sentence and timestamp.
    # This completes the record started at choose-trace time.
    if emission_text and isinstance(state.get("last_sent_emission"), dict):
        state["last_sent_emission"]["sent_text"] = emission_text
        state["last_sent_emission"]["sent_at_ts"] = now
    if message_id and isinstance(state.get("last_sent_emission"), dict):
        state["last_sent_emission"]["message_id"] = message_id
    traces = state.get("traces", [])
    if traces:
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


def cmd_check_repeat(path: Path, candidate_text: str, candidate_theme: str | None = None):
    """
    Compare a candidate message against recent_emissions.
    Rejects if:
      - Same theme AND text overlap >= 60% (candidate <= 15 chars uses 40% threshold)
      - Same theme AND identical text (any length)
    Returns: {ok, repeat, reason, scored_recent}
    """
    state = load_state(path)
    prune_and_decay_traces(state)
    save_state(path, state)

    candidate_text = (candidate_text or "").strip()
    candidate_theme = (candidate_theme or "").strip()
    recent = state.get("recent_emissions", [])

    if not recent:
        return {
            "ok": True,
            "repeat": False,
            "reason": None,
            "candidate_text": candidate_text,
            "candidate_theme": candidate_theme,
            "scored_recent": [],
        }

    def char_overlap(a: str, b: str) -> float:
        """Return Jaccard-like overlap ratio: |A ∩ B| / min(|A|, |B|)."""
        if not a or not b:
            return 0.0
        set_a = set(a)
        set_b = set(b)
        intersection = len(set_a & set_b)
        denominator = min(len(set_a), len(set_b))
        return intersection / denominator if denominator > 0 else 0.0

    scored = []
    for em in recent:
        overlap = char_overlap(candidate_text, em.get("text", ""))
        theme_match = (
            candidate_theme == em.get("theme", "") and
            candidate_theme != ""
        )
        scored.append({
            "theme": em.get("theme"),
            "text_preview": (em.get("text") or "")[:30],
            "overlap": round(overlap, 3),
            "theme_match": theme_match,
        })

        # Threshold for overlap when theme matches: 60% (40% for very short candidates)
        overlap_threshold = 0.40 if len(candidate_text) <= 15 else 0.60
        if theme_match:
            if candidate_text == em.get("text", "").strip():
                return {
                    "ok": True,
                    "repeat": True,
                    "reason": "identical_text_same_theme",
                    "scored_recent": scored,
                }
            if overlap >= overlap_threshold:
                return {
                    "ok": True,
                    "repeat": True,
                    "reason": f"theme_match_overlap_{int(overlap*100)}",
                    "scored_recent": scored,
                }

    return {
        "ok": True,
        "repeat": False,
        "reason": None,
        "candidate_text": candidate_text,
        "candidate_theme": candidate_theme,
        "scored_recent": scored,
    }


def cmd_mark_failed(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    save_state(path, state)
    return {"ok": True, "state": state}


def cmd_inspect(path: Path):
    state = load_state(path)
    prune_and_decay_traces(state)
    save_state(path, state)
    return {"ok": True, "state": state, "config": CONFIG}


def cmd_get_emission(path: Path):
    """Return the last_sent_emission context without modifying state."""
    state = load_state(path)
    prune_and_decay_traces(state)
    emission = state.get("last_sent_emission")
    if not emission:
        return {"ok": True, "emission": None, "state": state}
    return {"ok": True, "emission": emission, "state": state}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "init",
            "activate",
            "deactivate",
            "precheck",
            "upsert-trace",
            "choose-trace",
            "mark-sent",
            "mark-failed",
            "inspect",
            "get-emission",
            "check-repeat",
        ],
    )
    parser.add_argument("--state", required=True)
    parser.add_argument("--theme")
    parser.add_argument("--kind")
    parser.add_argument("--weight", type=float, default=0.46)
    parser.add_argument("--quietness", type=float, default=1.0)
    parser.add_argument("--message-id", type=int, default=None)
    # Used by mark-sent to record emission text+theme for anti-repeat
    parser.add_argument("--text")
    # Used by check-repeat and mark-sent for theme-level comparison
    parser.add_argument("--candidate-text", dest="candidate_text")
    # Used by choose-trace to record richer emission context
    parser.add_argument("--source-snippet", dest="source_snippets", action="append", default=None)
    parser.add_argument("--association-snippet", dest="association_snippets", action="append", default=None)
    parser.add_argument("--concrete-topic", dest="concrete_topic", default=None)
    parser.add_argument("--why-chosen", dest="why_chosen", default=None)
    args = parser.parse_args()

    path = Path(args.state).expanduser()

    if args.command == "init":
        result = cmd_init(path)
    elif args.command == "activate":
        result = cmd_activate(path)
    elif args.command == "deactivate":
        result = cmd_deactivate(path)
    elif args.command == "precheck":
        result = cmd_precheck(path)
    elif args.command == "upsert-trace":
        result = cmd_upsert_trace(path, args.theme or "", args.kind or "echo", args.weight)
    elif args.command == "choose-trace":
        result = cmd_choose_trace(
            path, args.quietness,
            source_snippets=args.source_snippets,
            association_snippets=args.association_snippets,
            concrete_topic=args.concrete_topic,
            why_chosen=args.why_chosen,
        )
    elif args.command == "mark-sent":
        result = cmd_mark_sent(path, args.message_id,
                               emission_text=args.text,
                               emission_theme=args.theme)
    elif args.command == "mark-failed":
        result = cmd_mark_failed(path)
    elif args.command == "get-emission":
        result = cmd_get_emission(path)
    elif args.command == "check-repeat":
        result = cmd_check_repeat(path,
                                  candidate_text=args.candidate_text or "",
                                  candidate_theme=args.theme or "")
    else:
        result = cmd_inspect(path)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
