from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class VoiceRuntimeResult:
    ready: bool
    message: str
    started_engine: bool = False


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


def apply_voicevox_settings(query: dict, config: AppConfig) -> dict:
    query["speedScale"] = config.voicevox_speed_scale
    query["pitchScale"] = config.voicevox_pitch_scale
    query["intonationScale"] = config.voicevox_intonation_scale
    query["volumeScale"] = config.voicevox_volume_scale
    return query


class VoicevoxRuntime:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._engine_process: subprocess.Popen[bytes] | None = None

    def is_available(self) -> bool:
        endpoint = self.config.voicevox_url.rstrip("/") + "/version"
        try:
            with urllib.request.urlopen(endpoint, timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def ensure_ready(self, progress: ProgressCallback | None = None) -> VoiceRuntimeResult:
        notify = progress or (lambda _message: None)
        if self.is_available():
            return VoiceRuntimeResult(
                True, f"音声準備完了（{self.config.voicevox_credit}）"
            )
        if not self.config.auto_start_voicevox:
            return VoiceRuntimeResult(False, "VOICEVOXの自動起動は無効です。")
        executable = self.find_executable()
        if executable is None:
            return VoiceRuntimeResult(
                False, "VOICEVOX Engineが見つからないため、Windows音声を使用します。"
            )
        notify("VOICEVOX Engineを起動中…")
        try:
            self._engine_process = self._start_engine(executable)
        except OSError as exc:
            return VoiceRuntimeResult(False, f"VOICEVOXを起動できませんでした: {exc}")
        if not self._wait_until_ready():
            self.stop_if_owned()
            return VoiceRuntimeResult(False, "VOICEVOXの起動がタイムアウトしました。")
        return VoiceRuntimeResult(
            True,
            f"音声準備完了（{self.config.voicevox_credit}）",
            started_engine=True,
        )

    def find_executable(self) -> Path | None:
        explicit = os.environ.get("MAIDCHAN_VOICEVOX_ENGINE_PATH")
        candidates: list[Path] = []
        if explicit:
            candidates.append(Path(explicit).expanduser())
        app_data = os.environ.get("APPDATA")
        if app_data:
            engine_root = Path(app_data) / "voicevox" / "vvpp-engines"
            candidates.extend(engine_root.glob("VOICEVOX_Engine*/*run.exe"))
            candidates.extend(engine_root.glob("VOICEVOX_Engine*/run.exe"))
        existing = [path for path in candidates if path.is_file()]
        if not existing:
            return None
        return max(existing, key=lambda path: path.stat().st_mtime)

    def stop_if_owned(self) -> None:
        process = self._engine_process
        self._engine_process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()

    def _start_engine(self, executable: Path) -> subprocess.Popen[bytes]:
        parsed = urllib.parse.urlparse(self.config.voicevox_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 50021
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        return subprocess.Popen(
            [str(executable), "--host", host, "--port", str(port)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

    def _wait_until_ready(self, timeout_seconds: float = 30) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_available():
                return True
            if self._engine_process is not None and self._engine_process.poll() is not None:
                return False
            time.sleep(0.25)
        return False


class SpeechSynthesizer:
    def __init__(self, config: AppConfig, voicevox: VoicevoxRuntime) -> None:
        self.config = config
        self.voicevox = voicevox
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        clean_text = sanitize_for_speech(text)
        if not clean_text:
            return
        if os.name != "nt":
            raise VoiceError("音声合成は現在Windowsにのみ対応しています。")
        with self._lock:
            if self.config.tts_engine == "voicevox":
                try:
                    self._speak_voicevox(clean_text)
                    return
                except VoiceError:
                    pass
            self._speak_sapi(clean_text)

    def _speak_voicevox(self, text: str) -> None:
        result = self.voicevox.ensure_ready()
        if not result.ready:
            raise VoiceError(result.message)
        base_url = self.config.voicevox_url.rstrip("/")
        speaker = self.config.voicevox_speaker
        query_params = urllib.parse.urlencode({"text": text, "speaker": speaker})
        query_request = urllib.request.Request(
            f"{base_url}/audio_query?{query_params}", data=b"", method="POST"
        )
        try:
            with urllib.request.urlopen(query_request, timeout=30) as response:
                query = json.loads(response.read().decode("utf-8"))
            apply_voicevox_settings(query, self.config)
            synthesis_request = urllib.request.Request(
                f"{base_url}/synthesis?speaker={speaker}",
                data=json.dumps(query, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(synthesis_request, timeout=90) as response:
                wave_data = response.read()
            import winsound

            winsound.PlaySound(wave_data, winsound.SND_MEMORY)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise VoiceError(f"VOICEVOXで音声を生成できませんでした: {exc}") from exc

    def _speak_sapi(self, text: str) -> None:
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
            voice.Speak(text)
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
        self.voicevox = VoicevoxRuntime(config)
        self.synthesizer = SpeechSynthesizer(config, self.voicevox)

    def close(self) -> None:
        self.recorder.close()
        self.voicevox.stop_if_owned()
