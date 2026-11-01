from array import array

from maidchan.config import AppConfig
from maidchan.voice import (
    ContinuousMicrophoneListener,
    EnergyVoiceDetector,
    OfflineSpeechRecognizer,
    VoicevoxRuntime,
    amplify_pcm16,
    apply_voicevox_settings,
    correct_voice_transcript,
    pcm16_rms,
    prepare_audio_for_recognition,
    sanitize_for_speech,
)


def test_sanitize_for_speech_removes_markup_and_urls() -> None:
    text = "**結果**は `ok` です。 https://example.com"
    result = sanitize_for_speech(text)
    assert "*" not in result
    assert "`" not in result
    assert "https" not in result
    assert "リンク" in result


def test_voice_transcript_corrects_maidchan_name_at_start() -> None:
    assert correct_voice_transcript("姉 ちゃん 今日 は 何 する") == (
        "メイドちゃん 今日 は 何 する"
    )
    assert correct_voice_transcript("ねえ 姉ちゃん、聞いて") == (
        "ねえ メイドちゃん、聞いて"
    )


def test_voice_transcript_preserves_actual_older_sister_reference() -> None:
    assert correct_voice_transcript("私の姉ちゃんは元気です") == "私の姉ちゃんは元気です"


def test_voice_transcript_normalizes_space_in_correct_name() -> None:
    assert correct_voice_transcript("メイド ちゃん おはよう") == (
        "メイドちゃん おはよう"
    )


def test_whisper_transcription_uses_japanese_and_maidchan_prompt() -> None:
    calls = {}

    class Segment:
        text = " 姉ちゃん、おはよう"

    class FakeModel:
        def transcribe(self, samples, **kwargs):
            calls["sample_count"] = len(samples)
            calls.update(kwargs)
            return iter([Segment()]), object()

    recognizer = OfflineSpeechRecognizer(AppConfig())
    recognizer._model = FakeModel()
    audio = array("h", [1200, -1200] * 1600).tobytes()

    assert recognizer.transcribe(audio, 16000) == "メイドちゃん、おはよう"
    assert calls["sample_count"] == 3200
    assert calls["language"] == "ja"
    assert calls["initial_prompt"] == "メイドちゃん、"


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


def test_energy_detector_accepts_two_consecutive_utterances() -> None:
    config = AppConfig(
        vad_min_rms=400,
        vad_noise_multiplier=2.2,
        vad_block_ms=50,
        vad_min_speech_ms=200,
        vad_silence_ms=200,
        vad_preroll_ms=100,
    )
    detector = EnergyVoiceDetector(16000, config)
    silence = array("h", [20] * 800).tobytes()
    speech = array("h", [2000] * 800).tobytes()
    utterances = []
    for _cycle in range(2):
        for _ in range(6):
            result = detector.accept(speech)
            if result is not None:
                utterances.append(result)
        for _ in range(6):
            result = detector.accept(silence)
            if result is not None:
                utterances.append(result)
    assert len(utterances) == 2


def test_listener_restarts_when_processing_thread_has_stopped(monkeypatch) -> None:
    listener = ContinuousMicrophoneListener(AppConfig())

    class DeadThread:
        def is_alive(self) -> bool:
            return False

    listener._stream = object()  # type: ignore[assignment]
    listener._thread = DeadThread()  # type: ignore[assignment]
    calls: list[str] = []
    monkeypatch.setattr(listener, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(listener, "start", lambda: calls.append("start"))
    listener.resume()
    assert calls == ["stop", "start"]


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
