from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from maidchan.assistant import LocalAssistant
from maidchan.config import AppConfig
from maidchan.ollama_runtime import OllamaRuntime
from maidchan.ui import MascotWindow
from maidchan.voice import VoiceServices


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Maid-chan Local")
    app.setQuitOnLastWindowClosed(False)
    config = AppConfig.load()
    assistant = LocalAssistant(config)
    runtime = OllamaRuntime(config, assistant.client)
    voice = VoiceServices(config)
    app.aboutToQuit.connect(runtime.stop_if_owned)
    app.aboutToQuit.connect(voice.close)
    window = MascotWindow(config, assistant, runtime, voice)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

