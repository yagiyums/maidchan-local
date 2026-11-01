from array import array

from maidchan.config import AppConfig
from maidchan.voice import (
    EnergyVoiceDetector,
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


def test_energy_detector_emits_after_speech_and_silence() -> None:
    config = AppConfig(
        vad_min_rms=400,
        vad_noise_multiplier=3.0,
        vad_block_ms=50,
        vad_min_speech_ms=300,
        vad_silence_ms=300,
        vad_preroll_ms=100,
    )
    detector = EnergyVoiceDetector(16000, config)
    silence = array("h", [20] * 800).tobytes()
    speech = array("h", [2000] * 800).tobytes()
    for _ in range(5):
        assert detector.accept(silence) is None
    for _ in range(8):
        assert detector.accept(speech) is None
    result = None
    for _ in range(8):
        result = detector.accept(silence)
        if result is not None:
            break
    assert result is not None
    assert len(result) > len(speech)
