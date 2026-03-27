# delivery.md — openclaw_came_alive trace-generation fix

## What changed

**File:** `skills/openclaw_came_alive/SKILL.md`

**Root cause:** Step 1 of the heartbeat workflow said "若没有 live traces，也可以直接静默退出".
Combined with running `precheck` before reading context, this caused an immediate
deadlock on every first heartbeat after state reset — the pool was empty, so the
skill exited before ever calling `upsert-trace`.

Note: `cmd_precheck` in `manage_state.py` already correctly set `should_consider: True`
when the only reason was `no_live_traces`. The bug was purely in the SKILL.md layer
overriding that and exiting early.

**Fix:** Updated step 1 to remove the "exit on no_live_traces" branch, and added a
two-phase principle note at the top of the workflow. The new flow is:

1. `precheck` — only exit on `disabled` or `cooldown_active`
2. Continue to context read + `upsert-trace` (generate/refresh traces from context)
3. `choose-trace` — consume traces for optional emission
4. Generate + quality gate + send
5. `mark-sent` / `mark-failed`

This preserves the quiet/non-spam design: if context inspection yields no trace-worthy
residue, `upsert-trace` is never called and the skill still exits silently — just
later in the flow, after giving context a chance to generate traces.

## What was NOT changed

- `manage_state.py` (precheck logic was already correct)
- `quality_gate.py`
- `HEARTBEAT.md` (already correctly calls the skill; no change needed)
- Any behavioral parameters (thresholds, cooldowns, etc.)
