from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .assistant import LocalAssistant
from .config import AppConfig
from .ui import MascotWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Maid-chan Local")
    app.setQuitOnLastWindowClosed(False)
    config = AppConfig.load()
    assistant = LocalAssistant(config)
    window = MascotWindow(config, assistant)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

