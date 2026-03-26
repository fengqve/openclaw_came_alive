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

python3 - "$HEARTBEAT_FILE" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
block = """## openclaw_came_alive
- 读取 skill: ~/.openclaw/workspace/skills/openclaw_came_alive/SKILL.md
- 用 scripts/manage_state.py 做 state 初始化、precheck、成功/失败记账
- 若 state 允许继续，再定位真实用户会话、读取最近上下文、提取 signal、生成 candidate
- 用 scripts/quality_gate.py 检查 candidate；不过关则不发
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
