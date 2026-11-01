from maidchan.voice import SpeechModelManager, sanitize_for_speech


def test_existing_speech_model_is_reused(tmp_path) -> None:
    manager = SpeechModelManager(tmp_path)
    manager.model_path.mkdir(parents=True)
    assert manager.ensure_model() == manager.model_path


def test_sanitize_for_speech_removes_markup_and_urls() -> None:
    text = "**結果**は `ok` です。 https://example.com"
    result = sanitize_for_speech(text)
    assert "*" not in result
    assert "`" not in result
    assert "https" not in result
    assert "リンク" in result
