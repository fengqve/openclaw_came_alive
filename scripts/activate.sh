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

python3 - "$HEARTBEAT_FILE" "$SKILL_DIR" "$STATE_TOOL" "$SCRIPT_DIR/quality_gate.py" <<'PY'
from pathlib import Path
import sys
heartbeat_path = Path(sys.argv[1])
skill_dir = Path(sys.argv[2]).expanduser().resolve()
state_tool = Path(sys.argv[3]).expanduser().resolve()
quality_gate = Path(sys.argv[4]).expanduser().resolve()
block = f"""## openclaw_came_alive
- 读取 skill: {skill_dir / 'SKILL.md'}
- 用 `{state_tool}` 做 state 初始化、trace 管理与冲动选择
- 用 `{quality_gate}` 只做废话淘汰，不做机械式多层审核
- 按 skill 里的 heartbeat 工作流完整执行：precheck → 定位真实用户会话 → 读取上下文 → 必要时 upsert trace → choose-trace → 生成 candidate → quality gate → 显式发送
- 若只是 quiet hours / no_live_traces / 没有 candidate，不代表可提前跳过整个 came_alive 流程；只有完整跑完后仍无事可发，才返回 `HEARTBEAT_OK`
- 发送时必须显式投递到真实用户会话，不使用 heartbeat 默认回投目标；只有真实发送成功后，才能 mark-sent
"""
if not heartbeat_path.exists():
    heartbeat_path.write_text("# HEARTBEAT.md\n\n---\n\n" + block, encoding='utf-8')
    raise SystemExit(0)
text = heartbeat_path.read_text(encoding='utf-8')
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
heartbeat_path.write_text(text2, encoding='utf-8')
PY

echo "openclaw_came_alive activated"
