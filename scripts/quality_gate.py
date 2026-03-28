#!/usr/bin/env python3
import argparse
import json
import re
import sys
import unicodedata

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
    # Internal object leak: raw identifiers from scheduled tasks / search pipelines / filter steps
    # must be translated to user-perspective language before use.
    (re.compile(r'_crons?[\./][\w\-]+'), "meta_internal_scheduled_obj"),
    (re.compile(r'scheduled[_-]?task[_-]?\w*', re.IGNORECASE), "meta_internal_scheduled_obj"),
    (re.compile(r'search[_-]?pipeline[_-]?\w*', re.IGNORECASE), "meta_internal_search_obj"),
    (re.compile(r'filter[_-]?step[_-]?\w*', re.IGNORECASE), "meta_internal_filter_obj"),
    (re.compile(r'_filter[_\d]*\w*', re.IGNORECASE), "meta_internal_filter_obj"),
    (re.compile(r'pipeline[_-]?\w{3,}', re.IGNORECASE), "meta_internal_pipeline"),
    (re.compile(r'__\w+__(id|tag|label|key)', re.IGNORECASE), "meta_internal_dunder"),
]

# Anti-vague-reference guard: reject sentences where the subject/topic reference
# is so unspecified that a normal reader cannot tell what it refers to.
# "刚才你说的那个点还挺有意思的" ← reader has no idea which point.
_VAGUE_PATTERNS = [
    (re.compile(r'^说起来.*还挺有意思的'), "vague_no_topic"),
    (re.compile(r'^说起来.*那个点'), "vague_point"),
    (re.compile(r'^说起来.*这个点'), "vague_point"),
    (re.compile(r'^说起来.*那件事'), "vague_thing"),
    (re.compile(r'^说起来.*这件事'), "vague_thing"),
    (re.compile(r'^刚才.*那个点'), "vague_point"),
    (re.compile(r'^刚才.*这个点'), "vague_point"),
    (re.compile(r'^刚才.*那件事'), "vague_thing"),
    (re.compile(r'^刚才.*这件事'), "vague_thing"),
    (re.compile(r'^那个点'), "vague_standalone"),
    (re.compile(r'^这个点'), "vague_standalone"),
    (re.compile(r'^那件事'), "vague_standalone"),
    (re.compile(r'^这件事'), "vague_standalone"),
    (re.compile(r'^嗯+.*', re.IGNORECASE), "vague_acknowledgement"),
]

# Anti-synthetic / anti-over-polish: catch sentences that feel engineered
# rather than raw. A genuine lingering thought should have some rawness:
# slight incompleteness, asymmetry, or "cut off mid-thought" quality.
# Not every neat sentence is synthetic — but fully symmetric, perfectly
# concluded, structurally over-optimised sentences almost always are.
_SYNTHETIC_PATTERNS = [
    # Fully symmetric 4-char parallel: "A，B，C" or "X和Y和Z"
    # Captures the "1-2-3 list" feel that signals considered composition.
    (re.compile(r'^[\u4e00-\u9fff]{1,4}，[\u4e00-\u9fff]{1,4}，[\u4e00-\u9fff]{1,4}$'), "synthetic_triple_balance"),
    # Perfectly matched "虽然X，但Y" or "虽然X，不过Y" — too deliberate a contrast.
    (re.compile(r'^虽然[\u4e00-\u9fff]+，不过[\u4e00-\u9fff]+'), "synthetic_although_but"),
    (re.compile(r'^虽然[\u4e00-\u9fff]+，但[\u4e00-\u9fff]+'), "synthetic_although_but"),
    # "值得想想/值得研究/值得考虑" — evaluative closure that signals a complete answer
    # rather than an open-ended lingering thought.
    (re.compile(r'值得(想想|研究|考虑|再想想)$'), "synthetic_evaluative_close"),
    # Mid-sentence self-correction markers: signal the sentence was refined/edited.
    # Genuine thoughts don't say "不对，算了" — they trail off or move on.
    (re.compile(r'^不对[,，]'), "synthetic_self_correct"),
    (re.compile(r'^等等[,，]'), "synthetic_self_correct"),
    (re.compile(r'^等等[,，]不对'), "synthetic_self_correct"),
    # "一时.*一时" — repeated "一时" signals rhetorical construction.
    (re.compile(r'一时.+一时'), "synthetic_repeated_temporal"),
    # Sentences ending in a neat conclusion that closes the thought completely:
    # a fully stated conclusion without any "leftover" feel.
    # Patterns: "……的结论" / "……的结果" / "……的判断" ending the sentence.
    (re.compile(r'[\u4e00-\u9fff]+的结论$'), "synthetic_neat_conclusion"),
    (re.compile(r'[\u4e00-\u9fff]+的结果$'), "synthetic_neat_conclusion"),
    (re.compile(r'[\u4e00-\u9fff]+的判断$'), "synthetic_neat_conclusion"),
]

# Hard-banned prefixes — any sentence starting with these is rejected regardless
# of tail length. These lead-ins are tell-tale canned/thought-skipping markers.
BANNED_PREFIXES_HARD = ["对了", "突然想到"]
# Soft-banned prefixes — rejected only when the remaining tail is too short
# to form a substantive thought on its own.
BANNED_PREFIXES_SOFT = ["算了", "话说回来"]
ELLIPSIS_RE = re.compile(r'^[\.。…\s]+$')
PUNCT_ONLY_RE = re.compile(r'^[\s\.,!?，。！？…:：;；\-—~`]+$')
QUESTION_RE = re.compile(r'[?？]')

# Language/read-time-aware length budget.
MAX_CHINESE_CHARS = 390
MAX_ENGLISH_WORDS = 208
MAX_OTHER_READ_SECONDS = 47.0
ZH_CHARS_PER_SECOND = MAX_CHINESE_CHARS / MAX_OTHER_READ_SECONDS
EN_WORDS_PER_SECOND = MAX_ENGLISH_WORDS / MAX_OTHER_READ_SECONDS

CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
KANA_HANGUL_RE = re.compile(r'[\u3040-\u30ff\uac00-\ud7af\u1100-\u11ff]')
EN_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)?")
LATIN_LETTER_RE = re.compile(r'[A-Za-z]')
UNICODE_WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)

OLD_CANNED_FLAVOR = [
    "刚才那个问题有点意思",
    "想到个事儿",
    "想起来一个点",
]


def _count_readable_chars(text: str) -> int:
    """
    Count readable units for length estimation:
    keep letters/numbers, drop whitespace and punctuation/symbol noise.
    """
    count = 0
    for ch in text:
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("S"):
            continue
        count += 1
    return count


def _estimate_other_read_seconds(text: str, readable_chars: int) -> float:
    """
    Heuristic for non-Chinese/non-English scripts:
    - space-delimited writing systems: estimate by word rate
    - non-space-delimited scripts: estimate by readable chars
    """
    unicode_words = len(UNICODE_WORD_RE.findall(text))
    has_space = bool(re.search(r'\s', text))
    if has_space and unicode_words > 0:
        return unicode_words / EN_WORDS_PER_SECOND
    return readable_chars / ZH_CHARS_PER_SECOND


def _is_too_long(text: str) -> bool:
    """
    Length gate policy:
    - Chinese-dominant text: <= 390 CJK chars
    - English-dominant text: <= 208 English words
    - Other scripts: estimated read time <= ~47 seconds

    Keep detection simple/explainable (ratio-based, no heavy language model).
    """
    readable_chars = _count_readable_chars(text)
    if readable_chars == 0:
        return False

    zh_chars = len(CJK_RE.findall(text))
    kana_hangul_chars = len(KANA_HANGUL_RE.findall(text))
    en_words = len(EN_WORD_RE.findall(text))
    latin_letters = len(LATIN_LETTER_RE.findall(text))

    zh_ratio = zh_chars / readable_chars
    latin_ratio = latin_letters / readable_chars

    is_chinese_dominant = (
        zh_chars > 0
        and kana_hangul_chars == 0
        and zh_ratio >= 0.55
    )
    if is_chinese_dominant:
        return zh_chars > MAX_CHINESE_CHARS

    is_english_dominant = (
        en_words > 0
        and zh_chars == 0
        and kana_hangul_chars == 0
        and latin_ratio >= 0.55
    )
    if is_english_dominant:
        return en_words > MAX_ENGLISH_WORDS

    read_seconds = _estimate_other_read_seconds(text, readable_chars)
    return read_seconds > MAX_OTHER_READ_SECONDS


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
    if _is_too_long(text):
        reasons.append("too_long")

    for prefix in BANNED_PREFIXES_HARD:
        if text.startswith(prefix):
            reasons.append("banned_prefix")
            break
    if "banned_prefix" not in reasons:
        for prefix in BANNED_PREFIXES_SOFT:
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

    # Vague-reference gate — reject sentences where the reader cannot determine
    # what is being referenced. Allows slightly ambiguous but not unresolvably vague.
    for pattern, label in _VAGUE_PATTERNS:
        if pattern.search(text):
            reasons.append(label)
            break

    # Anti-synthetic / anti-over-polish gate — reject sentences that feel
    # engineered rather than raw. Catch: over-symmetry, over-conclusion,
    # deliberate self-correction, triple-balance lists.
    for pattern, label in _SYNTHETIC_PATTERNS:
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
