from maidchan.config import AppConfig
from maidchan.voice import (
    SpeechModelManager,
    VoicevoxRuntime,
    apply_voicevox_settings,
    sanitize_for_speech,
)


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


def test_voicevox_query_settings_are_applied() -> None:
    config = AppConfig(
        voicevox_speed_scale=1.2,
        voicevox_pitch_scale=0.05,
        voicevox_intonation_scale=1.1,
        voicevox_volume_scale=0.8,
    )
    query = apply_voicevox_settings({}, config)
    assert query == {
        "speedScale": 1.2,
        "pitchScale": 0.05,
        "intonationScale": 1.1,
        "volumeScale": 0.8,
    }


def test_voicevox_runtime_uses_explicit_engine_path(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "run.exe"
    executable.write_bytes(b"test")
    monkeypatch.setenv("MAIDCHAN_VOICEVOX_ENGINE_PATH", str(executable))
    assert VoicevoxRuntime(AppConfig()).find_executable() == executable
