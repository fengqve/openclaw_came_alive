#!/usr/bin/env python3
import argparse
import json
import re
import sys

BANNED_EXACT = {
    "哎", "哎。", "嗯", "嗯。", "喔", "喔。", "哦", "哦。",
    "对了", "对了。", "算了", "算了。", "没什么", "没什么。",
    "......", "……", "……。", "突然想到", "突然想到。", "突然想到……",
    "算了不说了", "算了不说了。",
    # explicit regression blocklist from old canned outputs
    "刚才那个问题有点意思。",
    "想到个事儿，但算了。",
    "想起来一个点。",
    "刚才那个方案，细节上可以再想想。",
    "刚才说的那个，我回去翻了翻。",
}

# Anti-meta guard: reject messages that sound like internal tool status reports
# rather than natural human-readable thoughts.
# Pattern: describe_flag(pattern, label)
_META_PATTERNS = [
    (re.compile(r'delivery\s*guard', re.IGNORECASE), "meta_delivery_guard"),
    (re.compile(r'mark[- ]?sent', re.IGNORECASE), "meta_mark_sent"),
    (re.compile(r'verify|verification|verified', re.IGNORECASE), "meta_verify"),
    (re.compile(r'发之前|发送前|发送时|发送后'), "meta_send_timing"),
    (re.compile(r'(这次|刚才|刚刚)(改|改动|修改|调整|更新|改动)'), "meta_change_summary"),
    (re.compile(r'(刚才|刚刚)?(技术|实现|机制|原理|架构)'), "meta_technical"),
    (re.compile(r'trace|impulse|cooldown|weight|freshness', re.IGNORECASE), "meta_skill_internal"),
    (re.compile(r'heartbeat|came_alive|活人感'), "meta_skill_name"),
    (re.compile(r'验证|校验|检查了一遍|确认'), "meta_verify_cn"),
    (re.compile(r'(功能|特性)改得值'), "meta_value_claim"),
    # Sentences that are clearly about internal process rather than a natural thought
    (re.compile(r'^.*(guard|mark[- ]?sent|delivery|发送|发送前|发送后).*$'), "meta_contains_tooling"),
    (re.compile(r'这次.+.改得值'), "meta_change_summary_short"),
]

BANNED_PREFIXES = ["对了", "算了", "突然想到", "话说回来"]
ELLIPSIS_RE = re.compile(r'^[\.。…\s]+$')
PUNCT_ONLY_RE = re.compile(r'^[\s\.,!?，。！？…:：;；\-—~`]+$')
QUESTION_RE = re.compile(r'[?？]')
OLD_CANNED_FLAVOR = [
    "刚才那个问题有点意思",
    "想到个事儿",
    "想起来一个点",
]


def analyze(text: str):
    original = text
    text = (text or "").strip()
    reasons = []

    if not text:
        reasons.append("empty")
    if text in BANNED_EXACT:
        reasons.append("banned_exact")
    if ELLIPSIS_RE.fullmatch(text or ""):
        reasons.append("ellipsis_only")
    if PUNCT_ONLY_RE.fullmatch(text or ""):
        reasons.append("punctuation_only")
    if QUESTION_RE.search(text):
        reasons.append("asks_question")
    if len(text) <= 2 and not re.search(r'[A-Za-z0-9\u4e00-\u9fff]{2,}', text):
        reasons.append("too_thin")
    if len(text) > 60:
        reasons.append("too_long")

    for prefix in BANNED_PREFIXES:
        if text.startswith(prefix):
            tail = text[len(prefix):].strip(" 。.!！?？…，,：:")
            if len(tail) < 4:
                reasons.append("dangling_prefix")
                break

    tokens = re.findall(r'[A-Za-z]+|[\u4e00-\u9fff]+', text)
    if len(tokens) == 1 and len(tokens[0]) <= 2 and len(text) <= 4:
        reasons.append("interjection_like")

    lowered = text.replace("。", "").replace("！", "").replace("？", "")
    if any(s in lowered for s in OLD_CANNED_FLAVOR):
        reasons.append("old_canned_flavor")

    # Meta/tooling language gate — reject internal status reports
    for pattern, label in _META_PATTERNS:
        if pattern.search(text):
            reasons.append(label)
            break

    ok = len(set(reasons)) == 0
    return {
        "ok": ok,
        "text": original,
        "normalized": text,
        "reasons": sorted(set(reasons)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="?")
    args = parser.parse_args()
    text = args.text if args.text is not None else sys.stdin.read()
    print(json.dumps(analyze(text), ensure_ascii=False))


if __name__ == "__main__":
    main()
