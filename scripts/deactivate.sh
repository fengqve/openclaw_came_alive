#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
WORKSPACE_DIR="$(dirname "$(dirname "$SKILL_DIR")")"
STATE_FILE="$WORKSPACE_DIR/memory/openclaw_came_alive_state.json"
HEARTBEAT_FILE="$WORKSPACE_DIR/HEARTBEAT.md"
STATE_TOOL="$SCRIPT_DIR/manage_state.py"

python3 "$STATE_TOOL" init --state "$STATE_FILE" >/dev/null
python3 "$STATE_TOOL" deactivate --state "$STATE_FILE" >/dev/null

python3 - "$HEARTBEAT_FILE" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)
text = path.read_text(encoding='utf-8')
lines = text.splitlines()
out = []
skip = False
for line in lines:
    if line.strip() == '## openclaw_came_alive':
        skip = True
        continue
    if skip:
        if line.startswith('## ') and line.strip() != '## openclaw_came_alive':
            skip = False
            out.append(line)
        elif line.startswith('---'):
            continue
        else:
            continue
    else:
        out.append(line)
path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PY

echo "openclaw_came_alive deactivated"
