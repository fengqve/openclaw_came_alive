#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
WORKSPACE_DIR="$(dirname "$(dirname "$SKILL_DIR")")"
STATE_FILE="$WORKSPACE_DIR/memory/openclaw_came_alive_state.json"
HEARTBEAT_FILE="$WORKSPACE_DIR/HEARTBEAT.md"
STATE_TOOL="$SCRIPT_DIR/manage_state.py"

python3 "$STATE_TOOL" init --state "$STATE_FILE" >/dev/null
python3 "$STATE_TOOL" activate --state "$STATE_FILE" >/dev/null
python3 "$STATE_TOOL" set-style --state "$STATE_FILE" --profile "闷骚型" >/dev/null

python3 - "$HEARTBEAT_FILE" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
block = """## openclaw_came_alive
- 读取 skill: ~/.openclaw/workspace/skills/openclaw_came_alive/SKILL.md
- 用 scripts/manage_state.py 做 state 初始化、style_profile、trace 管理与冲动选择
- 只有近期上下文里真的有余味，才 upsert trace；没有就安静退出
- 用 scripts/quality_gate.py 只做废话淘汰，不做机械式多层审核
- 发送时必须显式投递到真实用户会话，不使用 heartbeat 默认回投目标
"""
if not path.exists():
    path.write_text("# HEARTBEAT.md\n\n---\n\n" + block, encoding='utf-8')
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
text2 = '\n'.join(out).rstrip() + '\n\n' + block
path.write_text(text2, encoding='utf-8')
PY

echo "openclaw_came_alive activated"
