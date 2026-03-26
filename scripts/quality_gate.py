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
