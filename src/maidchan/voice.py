from __future__ import annotations

import audioop
import json
import math
import os
import queue
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
from collections import deque
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


def pcm16_rms(audio: bytes) -> float:
    if len(audio) < 2:
        return 0.0
    samples = memoryview(audio[: len(audio) // 2 * 2]).cast("h")
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def amplify_pcm16(audio: bytes, gain: float) -> bytes:
    if not audio:
        return b""
    return audioop.mul(audio, 2, max(0.0, min(8.0, gain)))


def pcm16_level_percent(audio: bytes) -> int:
    rms = pcm16_rms(audio)
    if rms <= 0:
        return 0
    decibels = 20 * math.log10(rms / 32768)
    return max(0, min(100, round((decibels + 60) * 100 / 54)))


def prepare_audio_for_recognition(
    audio: bytes,
    sample_rate: int,
    *,
    target_rate: int = 16000,
    target_rms: int = 4000,
    max_gain: float = 8.0,
) -> tuple[bytes, int]:
    if not audio or sample_rate <= 0:
        return audio, sample_rate

    even_audio = audio[: len(audio) // 2 * 2]
    centered = audioop.bias(even_audio, 2, -audioop.avg(even_audio, 2))
    if sample_rate != target_rate:
        centered, _state = audioop.ratecv(centered, 2, 1, sample_rate, target_rate, None)

    block_bytes = max(2, target_rate // 50 * 2)
    levels = [
        audioop.rms(centered[offset : offset + block_bytes], 2)
        for offset in range(0, len(centered), block_bytes)
        if len(centered[offset : offset + block_bytes]) >= 2
    ]
    nonzero_levels = sorted(level for level in levels if level > 20)
    if not nonzero_levels:
        return centered, target_rate
    top_count = max(1, math.ceil(len(nonzero_levels) * 0.2))
    speech_rms = sum(nonzero_levels[-top_count:]) / top_count
    gain = max(0.25, min(max_gain, target_rms / speech_rms))
    return audioop.mul(centered, 2, gain), target_rate


class EnergyVoiceDetector:
    def __init__(self, sample_rate: int, config: AppConfig) -> None:
        self.sample_rate = sample_rate
        self.config = config
        self.silence_blocks = max(1, math.ceil(config.vad_silence_ms / config.vad_block_ms))
        self.minimum_speech_blocks = max(
            1, math.ceil(config.vad_min_speech_ms / config.vad_block_ms)
        )
        self.maximum_blocks = max(
            1, math.ceil(config.vad_max_speech_seconds * 1000 / config.vad_block_ms)
        )
        preroll_blocks = max(1, math.ceil(config.vad_preroll_ms / config.vad_block_ms))
        self.preroll: deque[bytes] = deque(maxlen=preroll_blocks)
        self.noise_floor = max(50.0, config.vad_min_rms / 2)
        self.reset()

    def reset(self) -> None:
        self.speaking = False
        self.active_streak = 0
        self.active_blocks = 0
        self.trailing_silence = 0
        self.current: list[bytes] = []
        self.preroll.clear()

    def accept(self, audio: bytes) -> bytes | None:
        rms = pcm16_rms(audio)
        threshold = max(
            float(self.config.vad_min_rms),
            self.noise_floor * self.config.vad_noise_multiplier,
        )
        active = rms >= threshold

        if not self.speaking:
            self.preroll.append(audio)
            if active:
                self.active_streak += 1
                if self.active_streak >= 2:
                    self.speaking = True
                    self.active_blocks = self.active_streak
                    self.current = list(self.preroll)
            else:
                self.active_streak = 0
                self.noise_floor = self.noise_floor * 0.95 + rms * 0.05
            return None

        self.current.append(audio)
        if active:
            self.active_blocks += 1
            self.trailing_silence = 0
        else:
            self.trailing_silence += 1

        if len(self.current) >= self.maximum_blocks:
            return self._finish()
        if self.trailing_silence >= self.silence_blocks:
            return self._finish()
        return None

    def _finish(self) -> bytes | None:
        result = b"".join(self.current) if self.active_blocks >= self.minimum_speech_blocks else None
        self.reset()
        return result


class ContinuousMicrophoneListener:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.sample_rate = 16000
        self._stream: sd.RawInputStream | None = None
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._detector: EnergyVoiceDetector | None = None
        self.on_utterance: Callable[[bytes, int], None] = lambda _audio, _rate: None
        self.on_status: Callable[[str], None] = lambda _message: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self.on_level: Callable[[int], None] = lambda _level: None

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_processing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_callbacks(
        self,
        *,
        on_utterance: Callable[[bytes, int], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
        on_level: Callable[[int], None],
    ) -> None:
        self.on_utterance = on_utterance
        self.on_status = on_status
        self.on_error = on_error
        self.on_level = on_level

    def start(self) -> None:
        if self.is_running:
            self.resume()
            return
        try:
            device_info = sd.query_devices(self.config.microphone_device, "input")
            self.sample_rate = int(device_info["default_samplerate"])
            blocksize = max(1, int(self.sample_rate * self.config.vad_block_ms / 1000))
            self._detector = EnergyVoiceDetector(self.sample_rate, self.config)
            self._stop_event.clear()
            self._paused.clear()
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=blocksize,
                device=self.config.microphone_device,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._thread = threading.Thread(
                target=self._process_audio, name="maidchan-listener", daemon=True
            )
            self._thread.start()
            self.on_status("🎤 自動待受中")
        except Exception as exc:
            self._stream = None
            raise VoiceError(f"マイクの自動待受を開始できませんでした: {exc}") from exc

    def pause(self) -> None:
        self._paused.set()
        self.on_level(0)

    def resume(self) -> None:
        if not self.is_running or not self.is_processing:
            self.stop()
            self.start()
            return
        self._drain_queue()
        if self._detector is not None:
            self._detector.reset()
        self._paused.clear()
        self.on_level(0)
        self.on_status("🎤 自動待受中")

    def stop(self) -> None:
        self._stop_event.set()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except (sd.PortAudioError, OSError):
                self.on_error("マイクを正常に停止できませんでした。")
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._drain_queue()
        self.on_level(0)

    def _audio_callback(self, indata, _frames, _time, status) -> None:  # type: ignore[no-untyped-def]
        if status or self._paused.is_set():
            return
        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            pass

    def _process_audio(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    audio = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self._paused.is_set() or self._detector is None:
                    continue
                amplified = amplify_pcm16(audio, self.config.microphone_gain)
                self.on_level(pcm16_level_percent(amplified))
                utterance = self._detector.accept(amplified)
                if utterance:
                    self._paused.set()
                    self.on_level(0)
                    self.on_status("音声を認識中…")
                    self.on_utterance(utterance, self.sample_rate)
        except Exception as exc:  # noqa: BLE001 - restart after any worker failure
            self._paused.set()
            self.stop()
            self.on_error(f"マイク待受中にエラーが発生しました: {exc}")

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


class OfflineSpeechRecognizer:
    def __init__(
        self,
        model_manager: SpeechModelManager | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self.model_manager = model_manager or SpeechModelManager()
        self.config = config or AppConfig()
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
        prepared_audio, recognition_rate = prepare_audio_for_recognition(
            audio,
            sample_rate,
            target_rms=self.config.recognition_target_rms,
            max_gain=self.config.recognition_max_gain,
        )
        try:
            recognizer = KaldiRecognizer(model, recognition_rate)
            for offset in range(0, len(prepared_audio), 16000):
                recognizer.AcceptWaveform(prepared_audio[offset : offset + 16000])
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
            cwd=executable.parent,
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
        self.listener = ContinuousMicrophoneListener(config)
        self.recognizer = OfflineSpeechRecognizer(config=config)
        self.voicevox = VoicevoxRuntime(config)
        self.synthesizer = SpeechSynthesizer(config, self.voicevox)

    def close(self) -> None:
        self.recorder.close()
        self.listener.stop()
        self.voicevox.stop_if_owned()
