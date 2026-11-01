from array import array

from maidchan.config import AppConfig
from maidchan.voice import (
    EnergyVoiceDetector,
    SpeechModelManager,
    VoicevoxRuntime,
    amplify_pcm16,
    apply_voicevox_settings,
    pcm16_rms,
    prepare_audio_for_recognition,
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


def test_pcm_gain_amplifies_quiet_audio() -> None:
    quiet = array("h", [100, -100] * 800).tobytes()
    amplified = amplify_pcm16(quiet, 3.0)
    assert 295 <= pcm16_rms(amplified) <= 305


def test_recognition_audio_is_resampled_and_normalized() -> None:
    quiet = array("h", [200, -200] * 4410).tobytes()
    prepared, sample_rate = prepare_audio_for_recognition(
        quiet,
        44100,
        target_rms=4000,
        max_gain=8.0,
    )
    assert sample_rate == 16000
    assert 6000 <= len(prepared) <= 7000
    assert pcm16_rms(prepared) > pcm16_rms(quiet)
