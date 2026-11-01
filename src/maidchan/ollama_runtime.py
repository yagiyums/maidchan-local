from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .assistant import OllamaClient, OllamaError
from .config import AppConfig

StatusCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    ready: bool
    message: str
    started_server: bool = False


class OllamaRuntime:
    def __init__(self, config: AppConfig, client: OllamaClient) -> None:
        self.config = config
        self.client = client
        self._server_process: subprocess.Popen[bytes] | None = None

    def ensure_ready(self, progress: StatusCallback | None = None) -> RuntimeResult:
        notify = progress or (lambda _message: None)
        if not self.config.auto_start_ollama:
            return RuntimeResult(False, "Ollamaの自動起動は設定で無効です。")

        started_server = False
        if not self.client.is_available():
            notify("ローカルAIエンジンを起動中…")
            executable = self.find_executable()
            if executable is None:
                return RuntimeResult(
                    False,
                    "Ollamaが見つかりません。先にOllamaをインストールしてください。",
                )
            try:
                self._server_process = self._start_server(executable)
                started_server = True
            except OSError as exc:
                return RuntimeResult(False, f"Ollamaを起動できませんでした: {exc}")
            if not self._wait_for_server():
                self.stop_if_owned()
                return RuntimeResult(False, "Ollamaの起動がタイムアウトしました。")

        try:
            if not self.client.has_model():
                if not self.config.auto_pull_model:
                    return RuntimeResult(
                        False,
                        f"モデル {self.config.ollama_model} が未取得です。",
                        started_server,
                    )
                notify(
                    f"初回のみ {self.config.ollama_model} を準備中…\n"
                    "モデルの取得には数分かかる場合があります。"
                )
                self.client.pull_model()
        except OllamaError as exc:
            return RuntimeResult(False, f"ローカルAIの準備に失敗しました: {exc}", started_server)

        return RuntimeResult(
            True,
            f"ローカルAI準備完了（{self.config.ollama_model}）",
            started_server,
        )

    def find_executable(self) -> Path | None:
        candidates: list[str | Path | None] = [
            os.environ.get("MAIDCHAN_OLLAMA_PATH"),
            shutil.which("ollama"),
        ]
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe")
        for candidate in candidates:
            if candidate:
                path = Path(candidate).expanduser()
                if path.is_file():
                    return path
        return None

    def _start_server(self, executable: Path) -> subprocess.Popen[bytes]:
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        return subprocess.Popen(
            [str(executable), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

    def _wait_for_server(self, timeout_seconds: float = 20) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.client.is_available():
                return True
            if self._server_process is not None and self._server_process.poll() is not None:
                return False
            time.sleep(0.25)
        return False

    def stop_if_owned(self) -> None:
        process = self._server_process
        self._server_process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
