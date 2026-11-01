import random

from maidchan.emotion import choose_idle_emotion, detect_response_emotion


def test_response_emotion_detection() -> None:
    assert detect_response_emotion("承知しました。お任せください。") == "happy"
    assert detect_response_emotion("申し訳ありません。見つかりませんでした。") == "sad"
    assert detect_response_emotion("危険なので、注意してください。") == "angry"
    assert detect_response_emotion("なんと、これは驚きました！！") == "surprised"
    assert detect_response_emotion("確認して考えてみます。") == "thinking"
    assert detect_response_emotion("東京タワーは333メートルです。") == "neutral"


def test_idle_emotion_is_reproducible_with_seeded_rng() -> None:
    emotion = choose_idle_emotion(random.Random(7))
    assert emotion in {"happy", "sad", "surprised", "angry", "thinking"}
