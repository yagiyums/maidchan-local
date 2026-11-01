from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QObject, QPoint, QRunnable, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .assistant import LocalAssistant, Reply
from .config import AppConfig
from .ollama_runtime import OllamaRuntime, RuntimeResult
from .voice import VoiceError, VoiceRuntimeResult, VoiceServices


class WorkerSignals(QObject):
    finished = Signal(object)


class ReplyWorker(QRunnable):
    def __init__(self, assistant: LocalAssistant, text: str) -> None:
        super().__init__()
        self.assistant = assistant
        self.text = text
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        reply = self.assistant.reply(self.text)
        self.signals.finished.emit(reply)


class RuntimeWorkerSignals(QObject):
    progress = Signal(str)
    finished = Signal(object)


class RuntimeWorker(QRunnable):
    def __init__(self, runtime: OllamaRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self.signals = RuntimeWorkerSignals()

    @Slot()
    def run(self) -> None:
        result = self.runtime.ensure_ready(self.signals.progress.emit)
        self.signals.finished.emit(result)


class TranscriptionSignals(QObject):
    progress = Signal(str)
    finished = Signal(str)
    failed = Signal(str)


class TranscriptionWorker(QRunnable):
    def __init__(self, voice: VoiceServices, audio: bytes, sample_rate: int) -> None:
        super().__init__()
        self.voice = voice
        self.audio = audio
        self.sample_rate = sample_rate
        self.signals = TranscriptionSignals()

    @Slot()
    def run(self) -> None:
        try:
            text = self.voice.recognizer.transcribe(
                self.audio, self.sample_rate, self.signals.progress.emit
            )
            self.signals.finished.emit(text)
        except VoiceError as exc:
            self.signals.failed.emit(str(exc))


class SpeechWorker(QRunnable):
    def __init__(self, voice: VoiceServices, text: str) -> None:
        super().__init__()
        self.voice = voice
        self.text = text

    @Slot()
    def run(self) -> None:
        try:
            self.voice.synthesizer.speak(self.text)
        except VoiceError:
            pass


class VoiceRuntimeWorker(QRunnable):
    def __init__(self, voice: VoiceServices) -> None:
        super().__init__()
        self.voice = voice
        self.signals = RuntimeWorkerSignals()

    @Slot()
    def run(self) -> None:
        result = self.voice.voicevox.ensure_ready(self.signals.progress.emit)
        self.signals.finished.emit(result)


class MascotWindow(QWidget):
    def __init__(
        self,
        config: AppConfig,
        assistant: LocalAssistant,
        runtime: OllamaRuntime,
        voice: VoiceServices,
    ) -> None:
        super().__init__()
        self.config = config
        self.assistant = assistant
        self.runtime = runtime
        self.voice = voice
        self._drag_offset: QPoint | None = None
        self._threads = QThreadPool.globalInstance()
        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._restore_position()
        self.start_local_ai()

    def _setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.config.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(self.config.assistant_name)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.bubble = QFrame()
        self.bubble.setObjectName("bubble")
        bubble_layout = QVBoxLayout(self.bubble)
        self.message = QLabel(
            f"おかえりなさい、{self.config.user_name}。\nダブルクリックで話しかけてください。"
        )
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_layout.addWidget(self.message)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("話しかける…  (/help でコマンド表示)")
        self.input.returnPressed.connect(self._send)
        self.send_button = QPushButton("送信")
        self.send_button.clicked.connect(self._send)
        self.mic_button = QPushButton("🎤 話す")
        self.mic_button.setToolTip("クリックで録音開始、もう一度クリックで送信")
        self.mic_button.clicked.connect(self._toggle_recording)
        self.mic_button.setVisible(self.config.voice_input_enabled)
        self.speaker_button = QPushButton("🔊" if self.config.tts_enabled else "🔇")
        self.speaker_button.setToolTip(
            f"応答音声のオン・オフ（{self.config.voicevox_credit}）"
        )
        self.speaker_button.clicked.connect(self._toggle_speech)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.mic_button)
        input_row.addWidget(self.speaker_button)
        bubble_layout.addLayout(input_row)
        self.bubble.hide()
        root.addWidget(self.bubble)

        asset_path = files("maidchan").joinpath("assets/maid.png")
        original = QPixmap(str(asset_path))
        self.mascot = QLabel()
        self.mascot.setPixmap(
            original.scaledToWidth(
                self.config.mascot_width, Qt.TransformationMode.SmoothTransformation
            )
        )
        self.mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.mascot)

        self.setStyleSheet(
            """
            QFrame#bubble {
                background: rgba(26, 21, 29, 235);
                border: 1px solid rgba(184, 74, 92, 220);
                border-radius: 14px;
            }
            QLabel { color: #fff7f2; font-size: 14px; }
            QLineEdit {
                color: #fff; background: rgba(255,255,255,24);
                border: 1px solid rgba(255,255,255,60); border-radius: 8px; padding: 8px;
            }
            QPushButton {
                color: #fff; background: #9d3448; border: 0; border-radius: 8px; padding: 8px 12px;
            }
            QPushButton:disabled { background: #5c4a50; }
            """
        )
        self.adjustSize()

    def _setup_tray(self) -> None:
        pixmap = self.mascot.pixmap()
        self.tray = QSystemTrayIcon(QIcon(pixmap), self)
        menu = QMenu()
        talk = QAction("話しかける", self)
        talk.triggered.connect(self.show_chat)
        status = QAction("Ollama接続を確認", self)
        status.triggered.connect(lambda: self._submit("/status"))
        start_ai = QAction("ローカルAIを起動", self)
        start_ai.triggered.connect(self.start_local_ai)
        hide = QAction("隠す / 表示", self)
        hide.triggered.connect(self._toggle_visible)
        quit_action = QAction("終了", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(talk)
        menu.addAction(status)
        menu.addAction(start_ai)
        menu.addSeparator()
        menu.addAction(hide)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _restore_position(self) -> None:
        if self.config.start_x is not None and self.config.start_y is not None:
            self.move(self.config.start_x, self.config.start_y)
            return
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(screen.right() - self.width() - 24, screen.bottom() - self.height() - 24)

    def show_chat(self) -> None:
        self.show()
        self.raise_()
        self.bubble.show()
        self.adjustSize()
        self.input.setFocus()

    def _send(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self._submit(text)

    def _submit(self, text: str) -> None:
        self.show_chat()
        self.message.setText("考え中…")
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.mic_button.setEnabled(False)
        worker = ReplyWorker(self.assistant, text)
        worker.signals.finished.connect(self._show_reply)
        self._threads.start(worker)

    def _toggle_recording(self) -> None:
        if self.voice.recorder.is_recording:
            try:
                audio, sample_rate = self.voice.recorder.stop()
            except VoiceError as exc:
                self._voice_failed(str(exc))
                return
            self.mic_button.setText("🎤 話す")
            self._show_voice_progress("音声を認識中…")
            worker = TranscriptionWorker(self.voice, audio, sample_rate)
            worker.signals.progress.connect(self._show_voice_progress)
            worker.signals.finished.connect(self._transcription_finished)
            worker.signals.failed.connect(self._voice_failed)
            self._threads.start(worker)
            return
        try:
            self.voice.recorder.start()
        except VoiceError as exc:
            self._voice_failed(str(exc))
            return
        self.mic_button.setText("■ 停止")
        self.message.setText("録音中…\n話し終わったら「停止」を押してください。")
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)

    def _toggle_speech(self) -> None:
        self.config.tts_enabled = not self.config.tts_enabled
        self.config.save()
        self.speaker_button.setText("🔊" if self.config.tts_enabled else "🔇")

    @Slot(str)
    def _show_voice_progress(self, message: str) -> None:
        self.message.setText(message)
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.mic_button.setEnabled(False)

    @Slot(str)
    def _transcription_finished(self, text: str) -> None:
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.mic_button.setEnabled(True)
        if not text:
            self.message.setText("音声を聞き取れませんでした。もう一度お試しください。")
            return
        self.input.setText(text)
        self._submit(text)

    @Slot(str)
    def _voice_failed(self, message: str) -> None:
        self.message.setText(message)
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.mic_button.setText("🎤 話す")

    def start_local_ai(self) -> None:
        self.show_chat()
        self._show_runtime_progress("ローカルAIを確認中…")
        worker = RuntimeWorker(self.runtime)
        worker.signals.progress.connect(self._show_runtime_progress)
        worker.signals.finished.connect(self._runtime_finished)
        self._threads.start(worker)

    @Slot(str)
    def _show_runtime_progress(self, message: str) -> None:
        self.message.setText(message)
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.mic_button.setEnabled(False)

    @Slot(object)
    def _runtime_finished(self, result: RuntimeResult) -> None:
        self._local_ai_status = result.message
        self._show_runtime_progress("VOICEVOXを確認中…")
        worker = VoiceRuntimeWorker(self.voice)
        worker.signals.progress.connect(self._show_runtime_progress)
        worker.signals.finished.connect(self._voice_runtime_finished)
        self._threads.start(worker)

    @Slot(object)
    def _voice_runtime_finished(self, result: VoiceRuntimeResult) -> None:
        self.message.setText(f"{self._local_ai_status}\n{result.message}")
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.input.setFocus()
        self.adjustSize()

    @Slot(object)
    def _show_reply(self, reply: Reply) -> None:
        suffix = "\n\n[オフライン応答]" if reply.source == "offline" else ""
        self.message.setText(reply.text + suffix)
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.mic_button.setEnabled(True)
        self.input.setFocus()
        self.adjustSize()
        if self.config.tts_enabled:
            self._threads.start(SpeechWorker(self.voice, reply.text))

    def _toggle_visible(self) -> None:
        self.hide() if self.isVisible() else self.show_chat()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.bubble.setVisible(not self.bubble.isVisible())
            self.adjustSize()
            if self.bubble.isVisible():
                self.input.setFocus()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self.config.start_x = self.x()
            self.config.start_y = self.y()
            self.config.save()

    def contextMenuEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.tray.contextMenu():
            self.tray.contextMenu().popup(event.globalPos())

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(self.config.mascot_width + 16, super().sizeHint().height())

