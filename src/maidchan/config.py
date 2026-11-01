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
    temperature: float = 0.7
    request_timeout_seconds: int = 90
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

