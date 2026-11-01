from __future__ import annotations

import random
from importlib.resources import files

from PySide6.QtCore import (
    QObject,
    QPoint,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QIcon,
    QImageReader,
    QMouseEvent,
    QMovie,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .assistant import LocalAssistant, Reply
from .config import AppConfig
from .emotion import choose_idle_emotion
from .ollama_runtime import OllamaRuntime, RuntimeResult
from .voice import VoiceError, VoiceRuntimeResult, VoiceServices


class WorkerSignals(QObject):
    finished = Signal(object)


class ReplyWorker(QRunnable):
    def __init__(self, assistant: LocalAssistant, text: str, input_source: str) -> None:
        super().__init__()
        self.assistant = assistant
        self.text = text
        self.input_source = input_source
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        reply = self.assistant.reply(self.text, self.input_source)
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


class ListeningSignals(QObject):
    utterance = Signal(bytes, int)
    status = Signal(str)
    failed = Signal(str)
    level = Signal(int)


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
        except Exception as exc:  # noqa: BLE001 - keep the listener recoverable
            message = str(exc) if isinstance(exc, VoiceError) else f"音声認識エラー: {exc}"
            self.signals.failed.emit(message)


class SpeechWorker(QRunnable):
    def __init__(self, voice: VoiceServices, text: str) -> None:
        super().__init__()
        self.voice = voice
        self.text = text
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.voice.synthesizer.speak(self.text)
        except Exception:  # noqa: BLE001, S110 - recovery runs in finally
            pass
        finally:
            self.signals.finished.emit(None)


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
        self._listen_signals = ListeningSignals()
        self._listen_signals.utterance.connect(self._auto_utterance)
        self._listen_signals.status.connect(self._set_mic_status)
        self._listen_signals.failed.connect(self._voice_failed)
        self._listen_signals.level.connect(self._set_mic_level)
        self.voice.listener.set_callbacks(
            on_utterance=self._listen_signals.utterance.emit,
            on_status=self._listen_signals.status.emit,
            on_error=self._listen_signals.failed.emit,
            on_level=self._listen_signals.level.emit,
        )
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
        self.mic_status = QLabel("🎤 準備中")
        self.mic_status.setToolTip("発話を自動検出して送信します")
        self.speaker_button = QPushButton("🔊" if self.config.tts_enabled else "🔇")
        self.speaker_button.setToolTip(
            f"応答音声のオン・オフ（{self.config.voicevox_credit}）"
        )
        self.speaker_button.clicked.connect(self._toggle_speech)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.mic_status)
        input_row.addWidget(self.speaker_button)
        bubble_layout.addLayout(input_row)

        audio_row = QHBoxLayout()
        audio_row.addWidget(QLabel("メイドちゃん音量"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 200)
        self.volume_slider.setSingleStep(5)
        self.volume_slider.setValue(round(self.config.voicevox_volume_scale * 100))
        self.volume_slider.setToolTip("VOICEVOXの読み上げ音量（0〜200%）")
        self.volume_value = QLabel(f"{self.volume_slider.value()}%")
        self.volume_slider.valueChanged.connect(self._set_voice_volume)
        audio_row.addWidget(self.volume_slider, 1)
        audio_row.addWidget(self.volume_value)

        audio_row.addWidget(QLabel("マイク感度"))
        self.mic_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.mic_gain_slider.setRange(100, 600)
        self.mic_gain_slider.setSingleStep(25)
        self.mic_gain_slider.setValue(round(self.config.microphone_gain * 100))
        self.mic_gain_slider.setToolTip("小さいマイク入力を認識前に増幅します")
        self.mic_gain_value = QLabel(f"{self.mic_gain_slider.value()}%")
        self.mic_gain_slider.valueChanged.connect(self._set_microphone_gain)
        audio_row.addWidget(self.mic_gain_slider, 1)
        audio_row.addWidget(self.mic_gain_value)

        self.mic_level = QProgressBar()
        self.mic_level.setRange(0, 100)
        self.mic_level.setValue(0)
        self.mic_level.setTextVisible(False)
        self.mic_level.setFixedWidth(60)
        self.mic_level.setToolTip("現在のマイク入力レベル")
        audio_row.addWidget(self.mic_level)
        bubble_layout.addLayout(audio_row)
        self.bubble.hide()
        root.addWidget(self.bubble)

        self.mascot = QLabel()
        self.mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        animation_files = {
            "neutral": "maid_idle.gif",
            "happy": "maid_happy.gif",
            "sad": "maid_sad.gif",
            "surprised": "maid_surprised.gif",
            "angry": "maid_angry.gif",
            "thinking": "maid_thinking.gif",
        }
        animation_path = files("maidchan").joinpath("assets/maid_idle.gif")
        source_size = QImageReader(str(animation_path)).size()
        self._mascot_movies: dict[str, QMovie] = {}
        self._mascot_movie = QMovie(str(animation_path))
        if self._mascot_movie.isValid() and source_size.isValid():
            height = round(
                self.config.mascot_width * source_size.height() / source_size.width()
            )
            scaled_size = QSize(self.config.mascot_width, height)
            for emotion, filename in animation_files.items():
                movie_path = files("maidchan").joinpath(f"assets/{filename}")
                movie = QMovie(str(movie_path))
                if not movie.isValid():
                    continue
                movie.setScaledSize(scaled_size)
                movie.setCacheMode(QMovie.CacheMode.CacheAll)
                self._mascot_movies[emotion] = movie
            self._mascot_movie = self._mascot_movies.get("neutral", self._mascot_movie)
            self.mascot.setFixedSize(scaled_size)
            self.mascot.setMovie(self._mascot_movie)
            self._mascot_movie.start()
        else:
            asset_path = files("maidchan").joinpath("assets/maid.png")
            original = QPixmap(str(asset_path))
            self.mascot.setPixmap(
                original.scaledToWidth(
                    self.config.mascot_width,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        root.addWidget(self.mascot)

        self._emotion_return_timer = QTimer(self)
        self._emotion_return_timer.setSingleShot(True)
        self._emotion_return_timer.timeout.connect(self._return_to_idle)
        self._idle_emotion_timer = QTimer(self)
        self._idle_emotion_timer.setSingleShot(True)
        self._idle_emotion_timer.timeout.connect(self._show_random_idle_emotion)
        self._schedule_idle_emotion()

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
            QSlider::groove:horizontal {
                height: 5px; background: rgba(255,255,255,45); border-radius: 2px;
            }
            QSlider::sub-page:horizontal { background: #dc667d; border-radius: 2px; }
            QSlider::handle:horizontal {
                background: #fff7f2; width: 13px; margin: -4px 0; border-radius: 6px;
            }
            QProgressBar {
                background: rgba(255,255,255,25); border: 0; border-radius: 4px;
            }
            QProgressBar::chunk { background: #65d39b; border-radius: 4px; }
            """
        )
        self.adjustSize()

    def _setup_tray(self) -> None:
        pixmap = self._mascot_movie.currentPixmap()
        if pixmap.isNull():
            pixmap = self.mascot.pixmap()
        self.tray = QSystemTrayIcon(QIcon(pixmap), self)
        menu = QMenu()
        talk = QAction("話しかける", self)
        talk.triggered.connect(self.show_chat)
        status = QAction("Ollama接続を確認", self)
        status.triggered.connect(lambda: self._submit("/status"))
        start_ai = QAction("ローカルAIを起動", self)
        start_ai.triggered.connect(self.start_local_ai)
        self.listen_action = QAction("マイク自動待受", self)
        self.listen_action.setCheckable(True)
        self.listen_action.setChecked(self.config.voice_input_enabled)
        self.listen_action.toggled.connect(self._set_hands_free)
        hide = QAction("隠す / 表示", self)
        hide.triggered.connect(self._toggle_visible)
        quit_action = QAction("終了", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(talk)
        menu.addAction(status)
        menu.addAction(start_ai)
        menu.addAction(self.listen_action)
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

    def _submit(self, text: str, input_source: str = "text") -> None:
        self.voice.listener.pause()
        self._stop_emotion_timers()
        self._set_animation("thinking")
        self.show_chat()
        self.message.setText("考え中…")
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        worker = ReplyWorker(self.assistant, text, input_source)
        worker.signals.finished.connect(self._show_reply)
        self._threads.start(worker)

    @Slot(bytes, int)
    def _auto_utterance(self, audio: bytes, sample_rate: int) -> None:
        self.show_chat()
        self._show_voice_progress("音声を認識中…")
        worker = TranscriptionWorker(self.voice, audio, sample_rate)
        worker.signals.progress.connect(self._show_voice_progress)
        worker.signals.finished.connect(self._transcription_finished)
        worker.signals.failed.connect(self._voice_failed)
        self._threads.start(worker)

    @Slot(str)
    def _set_mic_status(self, status: str) -> None:
        self.mic_status.setText(status)

    @Slot(int)
    def _set_mic_level(self, level: int) -> None:
        self.mic_level.setValue(level)

    @Slot(int)
    def _set_voice_volume(self, percent: int) -> None:
        self.config.voicevox_volume_scale = percent / 100
        self.config.tts_volume = min(100, percent)
        self.volume_value.setText(f"{percent}%")
        self.config.save()

    @Slot(int)
    def _set_microphone_gain(self, percent: int) -> None:
        self.config.microphone_gain = percent / 100
        self.mic_gain_value.setText(f"{percent}%")
        self.config.save()

    @Slot(bool)
    def _set_hands_free(self, enabled: bool) -> None:
        self.config.voice_input_enabled = enabled
        self.config.save()
        if enabled:
            try:
                self.voice.listener.start()
            except VoiceError as exc:
                self._voice_failed(str(exc))
                self.listen_action.setChecked(False)
        else:
            self.voice.listener.stop()
            self.mic_status.setText("🎤 停止中")

    def _toggle_speech(self) -> None:
        self.config.tts_enabled = not self.config.tts_enabled
        self.config.save()
        self.speaker_button.setText("🔊" if self.config.tts_enabled else "🔇")

    @Slot(str)
    def _show_voice_progress(self, message: str) -> None:
        self._stop_emotion_timers()
        self._set_animation("thinking")
        self.message.setText(message)
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)

    @Slot(str)
    def _transcription_finished(self, text: str) -> None:
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        if not text:
            self.message.setText("音声を聞き取れませんでした。もう一度お試しください。")
            self._resume_listening()
            return
        self.input.setText(text)
        self._submit(text, input_source="voice")

    @Slot(str)
    def _voice_failed(self, message: str) -> None:
        self._play_temporary_emotion("sad")
        self.message.setText(message)
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self._resume_listening()

    def start_local_ai(self) -> None:
        self.show_chat()
        self._show_runtime_progress("ローカルAIを確認中…")
        worker = RuntimeWorker(self.runtime)
        worker.signals.progress.connect(self._show_runtime_progress)
        worker.signals.finished.connect(self._runtime_finished)
        self._threads.start(worker)

    @Slot(str)
    def _show_runtime_progress(self, message: str) -> None:
        self._set_animation("thinking")
        self.message.setText(message)
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)

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
        self._play_temporary_emotion("happy", 3500)
        self.message.setText(f"{self._local_ai_status}\n{result.message}")
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.input.setFocus()
        self.adjustSize()
        if self.config.voice_input_enabled:
            self._set_hands_free(True)
        else:
            self.mic_status.setText("🎤 停止中")

    @Slot(object)
    def _show_reply(self, reply: Reply) -> None:
        self._play_temporary_emotion(reply.emotion)
        suffix = "\n\n[オフライン応答]" if reply.source == "offline" else ""
        self.message.setText(reply.text + suffix)
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.input.setFocus()
        self.adjustSize()
        if self.config.tts_enabled:
            worker = SpeechWorker(self.voice, reply.text)
            worker.signals.finished.connect(self._speech_finished)
            self._threads.start(worker)
        else:
            self._resume_listening()

    @Slot(object)
    def _speech_finished(self, _result: object) -> None:
        self._return_to_idle()
        self._resume_listening()

    def _set_animation(self, emotion: str) -> None:
        movie = self._mascot_movies.get(emotion)
        if movie is None:
            movie = self._mascot_movies.get("neutral")
        if movie is None or movie is self._mascot_movie:
            return
        self._mascot_movie.stop()
        self._mascot_movie = movie
        self.mascot.setMovie(movie)
        movie.jumpToFrame(0)
        movie.start()

    def _play_temporary_emotion(
        self, emotion: str, duration_ms: int | None = None
    ) -> None:
        self._stop_emotion_timers()
        self._set_animation(emotion)
        duration = duration_ms or self.config.response_emotion_seconds * 1000
        self._emotion_return_timer.start(max(1000, duration))

    def _return_to_idle(self) -> None:
        self._emotion_return_timer.stop()
        self._set_animation("neutral")
        self._schedule_idle_emotion()

    def _stop_emotion_timers(self) -> None:
        self._emotion_return_timer.stop()
        self._idle_emotion_timer.stop()

    def _schedule_idle_emotion(self) -> None:
        minimum = max(5, self.config.idle_emotion_min_seconds)
        maximum = max(minimum, self.config.idle_emotion_max_seconds)
        self._idle_emotion_timer.start(random.randint(minimum, maximum) * 1000)

    @Slot()
    def _show_random_idle_emotion(self) -> None:
        if not self.input.isEnabled():
            self._schedule_idle_emotion()
            return
        self._play_temporary_emotion(
            choose_idle_emotion(), self.config.idle_emotion_display_seconds * 1000
        )

    def _resume_listening(self) -> None:
        if self.config.voice_input_enabled:
            try:
                self.voice.listener.resume()
            except VoiceError as exc:
                self.message.setText(str(exc))
                self.input.setEnabled(True)
                self.send_button.setEnabled(True)
                self.mic_status.setText("🎤 再起動エラー")

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

