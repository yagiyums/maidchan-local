from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

from .config import AppConfig, app_data_dir

SPEECH_MODEL_NAME = "vosk-model-small-ja-0.22"
SPEECH_MODEL_URL = (
    "https://alphacephei.com/vosk/models/vosk-model-small-ja-0.22.zip"
)
ProgressCallback = Callable[[str], None]


class VoiceError(RuntimeError):
    """Raised when recording, recognition, or speech synthesis fails."""


class SpeechModelManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir() / "models"
        self.model_path = self.root / SPEECH_MODEL_NAME

    def ensure_model(self, progress: ProgressCallback | None = None) -> Path:
        if self.model_path.is_dir():
            return self.model_path
        notify = progress or (lambda _message: None)
        self.root.mkdir(parents=True, exist_ok=True)
        archive_path = self.root / f"{SPEECH_MODEL_NAME}.zip.part"
        last_percent = -10

        def report(block_count: int, block_size: int, total_size: int) -> None:
            nonlocal last_percent
            if total_size <= 0:
                return
            percent = min(100, int(block_count * block_size * 100 / total_size))
            if percent >= last_percent + 10:
                last_percent = percent
                notify(f"日本語音声認識モデルを準備中… {percent}%")

        notify("日本語音声認識モデルをダウンロード中…")
        try:
            urllib.request.urlretrieve(SPEECH_MODEL_URL, archive_path, report)
            with tempfile.TemporaryDirectory(dir=self.root) as temp_name:
                temp_root = Path(temp_name).resolve()
                with zipfile.ZipFile(archive_path) as archive:
                    for member in archive.infolist():
                        destination = (temp_root / member.filename).resolve()
                        if not destination.is_relative_to(temp_root):
                            raise VoiceError("音声モデルのアーカイブが不正です。")
                    archive.extractall(temp_root)
                extracted = temp_root / SPEECH_MODEL_NAME
                if not extracted.is_dir():
                    raise VoiceError("音声モデルを展開できませんでした。")
                shutil.move(str(extracted), str(self.model_path))
        except (OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
            raise VoiceError(f"音声認識モデルの準備に失敗しました: {exc}") from exc
        finally:
            archive_path.unlink(missing_ok=True)
        return self.model_path


class MicrophoneRecorder:
    def __init__(self, device: str | None = None) -> None:
        self.device = device
        self.sample_rate = 16000
        self._chunks: list[bytes] = []
        self._stream: sd.RawInputStream | None = None

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self.is_recording:
            return
        try:
            device_info = sd.query_devices(self.device, "input")
            self.sample_rate = int(device_info["default_samplerate"])
            self._chunks = []
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=8000,
                device=self.device,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise VoiceError(f"マイクを開始できませんでした: {exc}") from exc

    def stop(self) -> tuple[bytes, int]:
        stream = self._stream
        if stream is None:
            return b"", self.sample_rate
        self._stream = None
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            raise VoiceError(f"マイクを停止できませんでした: {exc}") from exc
        return b"".join(self._chunks), self.sample_rate

    def close(self) -> None:
        if self.is_recording:
            self.stop()

    def _audio_callback(self, indata, _frames, _time, status) -> None:  # type: ignore[no-untyped-def]
        if status:
            return
        self._chunks.append(bytes(indata))


class OfflineSpeechRecognizer:
    def __init__(self, model_manager: SpeechModelManager | None = None) -> None:
        self.model_manager = model_manager or SpeechModelManager()
        self._model: Model | None = None
        self._model_lock = threading.Lock()

    def transcribe(
        self,
        audio: bytes,
        sample_rate: int,
        progress: ProgressCallback | None = None,
    ) -> str:
        if not audio:
            return ""
        model = self._load_model(progress)
        try:
            recognizer = KaldiRecognizer(model, sample_rate)
            for offset in range(0, len(audio), 16000):
                recognizer.AcceptWaveform(audio[offset : offset + 16000])
            result = json.loads(recognizer.FinalResult())
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise VoiceError(f"音声を認識できませんでした: {exc}") from exc
        return str(result.get("text", "")).strip()

    def _load_model(self, progress: ProgressCallback | None = None) -> Model:
        with self._model_lock:
            if self._model is None:
                model_path = self.model_manager.ensure_model(progress)
                SetLogLevel(-1)
                try:
                    self._model = Model(str(model_path))
                except RuntimeError as exc:
                    raise VoiceError(f"音声認識モデルを読み込めませんでした: {exc}") from exc
            return self._model


def sanitize_for_speech(text: str) -> str:
    cleaned = re.sub(r"```.*?```", "コード部分を省略します。", text, flags=re.DOTALL)
    cleaned = re.sub(r"https?://\S+", "リンク", cleaned)
    cleaned = cleaned.replace("`", "")
    cleaned = re.sub(r"[*#_>]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class SpeechSynthesizer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        clean_text = sanitize_for_speech(text)
        if not clean_text:
            return
        if os.name != "nt":
            raise VoiceError("音声合成は現在Windowsにのみ対応しています。")
        with self._lock:
            try:
                import comtypes
                import comtypes.client

                comtypes.CoInitialize()
                voice = comtypes.client.CreateObject("SAPI.SpVoice")
                voices = voice.GetVoices()
                keyword = self.config.tts_voice_keyword.casefold()
                for index in range(voices.Count):
                    candidate = voices.Item(index)
                    if keyword in candidate.GetDescription().casefold():
                        voice.Voice = candidate
                        break
                voice.Rate = max(-10, min(10, self.config.tts_rate))
                voice.Volume = max(0, min(100, self.config.tts_volume))
                voice.Speak(clean_text)
            except Exception as exc:
                raise VoiceError(f"音声を再生できませんでした: {exc}") from exc
            finally:
                try:
                    comtypes.CoUninitialize()
                except (NameError, UnboundLocalError):
                    pass


class VoiceServices:
    def __init__(self, config: AppConfig) -> None:
        self.recorder = MicrophoneRecorder(config.microphone_device)
        self.recognizer = OfflineSpeechRecognizer()
        self.synthesizer = SpeechSynthesizer(config)

    def close(self) -> None:
        self.recorder.close()
