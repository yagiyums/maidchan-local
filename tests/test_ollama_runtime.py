from pathlib import Path

from maidchan.config import AppConfig
from maidchan.ollama_runtime import OllamaRuntime


class FakeClient:
    def __init__(self, *, available: bool, has_model: bool = True) -> None:
        self.available = available
        self.model_available = has_model
        self.pull_count = 0

    def is_available(self) -> bool:
        return self.available

    def has_model(self) -> bool:
        return self.model_available

    def pull_model(self) -> None:
        self.pull_count += 1
        self.model_available = True


def test_existing_server_with_model_is_ready() -> None:
    client = FakeClient(available=True, has_model=True)
    runtime = OllamaRuntime(AppConfig(), client)  # type: ignore[arg-type]
    result = runtime.ensure_ready()
    assert result.ready is True
    assert client.pull_count == 0


def test_missing_model_is_pulled_automatically() -> None:
    client = FakeClient(available=True, has_model=False)
    runtime = OllamaRuntime(AppConfig(auto_pull_model=True), client)  # type: ignore[arg-type]
    result = runtime.ensure_ready()
    assert result.ready is True
    assert client.pull_count == 1


def test_missing_ollama_returns_install_message(monkeypatch) -> None:
    client = FakeClient(available=False)
    runtime = OllamaRuntime(AppConfig(), client)  # type: ignore[arg-type]
    monkeypatch.setattr(runtime, "find_executable", lambda: None)
    result = runtime.ensure_ready()
    assert result.ready is False
    assert "インストール" in result.message


def test_find_executable_uses_explicit_environment_path(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "ollama.exe"
    executable.write_bytes(b"test")
    monkeypatch.setenv("MAIDCHAN_OLLAMA_PATH", str(executable))
    runtime = OllamaRuntime(
        AppConfig(), FakeClient(available=False)  # type: ignore[arg-type]
    )
    assert runtime.find_executable() == Path(executable)
