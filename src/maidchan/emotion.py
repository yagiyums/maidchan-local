from __future__ import annotations

import random
import re

EMOTIONS = ("neutral", "happy", "sad", "surprised", "angry", "thinking")
IDLE_EMOTIONS = ("happy", "thinking", "surprised", "sad", "angry")
IDLE_WEIGHTS = (5, 5, 2, 1, 1)

EMOTION_PATTERNS = (
    (
        "angry",
        re.compile(r"(?:危険|禁止|警告|注意して|やめて|だめ|許せない|怒)"),
    ),
    (
        "sad",
        re.compile(r"(?:申し訳|ごめん|残念|悲し|寂し|できません|見つかりません|失敗|エラー)"),
    ),
    (
        "surprised",
        re.compile(r"(?:びっくり|驚|まさか|なんと|すごい|本当ですか|[！!]{2,})"),
    ),
    (
        "happy",
        re.compile(
            r"(?:うれし|嬉し|よかった|おめでとう|ありがとう|楽しい|できます|"
            r"できました|承知|お任せ|おかえり|どういたしまして)"
        ),
    ),
    (
        "thinking",
        re.compile(r"(?:確認|調べ|考え|可能性|わかりません|不明|推測|資料によると)"),
    ),
)


def detect_response_emotion(text: str) -> str:
    for emotion, pattern in EMOTION_PATTERNS:
        if pattern.search(text):
            return emotion
    return "neutral"


def choose_idle_emotion(rng: random.Random | None = None) -> str:
    generator = rng or random
    return generator.choices(IDLE_EMOTIONS, weights=IDLE_WEIGHTS, k=1)[0]
