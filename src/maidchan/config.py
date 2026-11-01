from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_DIR_NAME = "MaidchanLocal"


def app_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class AppConfig:
    assistant_name: str = "メイドちゃん"
    user_name: str = "ご主人様"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    auto_start_ollama: bool = True
    auto_pull_model: bool = True
    voice_input_enabled: bool = True
    vad_min_rms: int = 500
    vad_noise_multiplier: float = 3.0
    vad_silence_ms: int = 900
    vad_min_speech_ms: int = 300
    vad_max_speech_seconds: int = 20
    vad_preroll_ms: int = 300
    vad_block_ms: int = 50
    tts_enabled: bool = True
    tts_engine: str = "voicevox"
    voicevox_url: str = "http://127.0.0.1:50021"
    voicevox_speaker: int = 103
    voicevox_credit: str = "VOICEVOX:ユーレイちゃん"
    voicevox_speed_scale: float = 1.05
    voicevox_pitch_scale: float = 0.0
    voicevox_intonation_scale: float = 1.0
    voicevox_volume_scale: float = 1.0
    auto_start_voicevox: bool = True
    tts_voice_keyword: str = "Haruka"
    tts_rate: int = 1
    tts_volume: int = 100
    microphone_device: str | None = None
    temperature: float = 0.7
    request_timeout_seconds: int = 90
    model_pull_timeout_seconds: int = 3600
    mascot_width: int = 190
    always_on_top: bool = True
    save_history: bool = True
    start_x: int | None = None
    start_y: int | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        config_path = path or app_data_dir() / "config.json"
        if not config_path.exists():
            config = cls()
            config.save(config_path)
            return config
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            allowed = {field.name for field in fields(cls)}
            values = {key: value for key, value in raw.items() if key in allowed}
            return cls(**values)
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        config_path = path or app_data_dir() / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

