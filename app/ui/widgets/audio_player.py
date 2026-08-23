"""A compact audio preview: transport, seekable waveform and volume.

Mediary is a library, not an editor, so this is deliberately minimal. The
waveform is a cheap peak envelope computed with ffmpeg when it is available and
falls back to a plain progress track when it is not.
"""

from __future__ import annotations

import array
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSlider, QWidget

try:
    # QtMultimedia links against the platform's audio stack - PulseAudio on
    # most Linux systems. A machine without it must still be able to open the
    # library and everything else; only in-app playback goes away.
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    MULTIMEDIA_AVAILABLE = True
except ImportError as _multimedia_error:  # pragma: no cover - platform dependent
    QAudioOutput = QMediaPlayer = None
    MULTIMEDIA_AVAILABLE = False
    _MULTIMEDIA_ERROR = str(_multimedia_error)

from app.media.ffmpeg import get_ffmpeg
from app.ui.theme import Space, get_theme
from app.ui.widgets.common import hbox, icon_button, label, vbox
from app.utils.formatting import format_duration
from app.utils.logging import get_logger
from app.utils.paths import is_windows

log = get_logger("audio")

WAVEFORM_BUCKETS = 260
_CREATE_NO_WINDOW = 0x08000000 if is_windows() else 0


class _WaveformSignals(QObject):
    ready = Signal(object)   # list[float] peaks, 0..1


class _WaveformWorker(QRunnable):
    """Decodes a low-rate mono PCM stream and reduces it to peak buckets."""

    def __init__(self, path: str, ffmpeg_path: str, buckets: int = WAVEFORM_BUCKETS) -> None:
        super().__init__()
        self.path = path
        self.ffmpeg_path = ffmpeg_path
        self.buckets = buckets
        self.signals = _WaveformSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        peaks: list = []
        try:
            # 8 kHz mono 16-bit is far more resolution than a 260px strip needs
            # and keeps the decode cheap even for a long track.
            result = subprocess.run(
                [
                    self.ffmpeg_path, "-v", "quiet", "-i", self.path,
                    "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
                ],
                capture_output=True,
                timeout=45,
                creationflags=_CREATE_NO_WINDOW,
            )
            raw = result.stdout or b""
            if len(raw) >= 4:
                samples = array.array("h")
                samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
                peaks = _reduce_to_peaks(samples, self.buckets)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            log.debug("Waveform generation failed for %s: %s", self.path, exc)
        self.signals.ready.emit(peaks)


def _reduce_to_peaks(samples, buckets: int) -> list:
    total = len(samples)
    if total == 0:
        return []
    step = max(1, total // buckets)
    peaks = []
    for start in range(0, total, step):
        window = samples[start : start + step]
        if not window:
            continue
        peak = max(abs(int(v)) for v in window)
        peaks.append(peak / 32768.0)
        if len(peaks) >= buckets:
            break
    ceiling = max(peaks) if peaks else 0.0
    if ceiling > 0:
        # Normalise so quiet files still render a readable shape.
        peaks = [min(1.0, p / ceiling) for p in peaks]
    return peaks


def generate_waveform(path: str, callback, *, owner: QObject | None = None) -> bool:
    """Compute a waveform for ``path`` off the GUI thread.

    Shared by the detail view and the preview dock. Returns False when there is
    no ffmpeg to decode with, in which case the caller just gets no waveform -
    the transport still works.
    """
    ffmpeg = get_ffmpeg()
    if not ffmpeg.available or not path:
        return False
    worker = _WaveformWorker(path, ffmpeg.path)
    if owner is not None:
        worker.signals.setParent(owner)
    worker.signals.ready.connect(callback)
    QThreadPool.globalInstance().start(worker)
    return True


class WaveformBar(QWidget):
    """A click- and drag-seekable waveform strip."""

    seek_requested = Signal(float)   # 0..1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._peaks: list = []
        self._position = 0.0
        self._hover = -1.0
        self.setMouseTracking(True)

    def set_peaks(self, peaks: list) -> None:
        self._peaks = list(peaks or [])
        self.update()

    def set_position(self, fraction: float) -> None:
        self._position = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        theme = get_theme()
        if theme is None:
            return
        palette = theme.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        width, height = self.width(), self.height()
        mid = height / 2

        if not self._peaks:
            # No waveform available: a slim track still communicates position.
            track = QRectF(0, mid - 2, width, 4)
            painter.setBrush(QColor(palette.border_strong))
            painter.drawRoundedRect(track, 2, 2)
            painter.setBrush(QColor(palette.accent))
            painter.drawRoundedRect(QRectF(0, mid - 2, width * self._position, 4), 2, 2)
            painter.end()
            return

        count = len(self._peaks)
        bar_width = max(1.5, (width / count) * 0.62)
        gap = width / count
        played_to = width * self._position

        for index, peak in enumerate(self._peaks):
            x = index * gap
            bar_height = max(2.0, peak * (height - 8))
            rect = QRectF(x, mid - bar_height / 2, bar_width, bar_height)
            if x + bar_width <= played_to:
                colour = QColor(palette.accent)
            elif x <= played_to:
                colour = QColor(palette.accent)
                colour.setAlpha(170)
            else:
                colour = QColor(palette.border_strong)
            painter.setBrush(colour)
            painter.drawRoundedRect(rect, 1, 1)

        if self._hover >= 0:
            painter.setBrush(QColor(palette.text_muted))
            painter.drawRect(QRectF(width * self._hover, 0, 1, height))

        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._emit_seek(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hover = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._emit_seek(event.position().x())
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hover = -1.0
        self.update()
        super().leaveEvent(event)

    def _emit_seek(self, x: float) -> None:
        self.seek_requested.emit(max(0.0, min(1.0, x / max(1, self.width()))))


class AudioPlayer(QWidget):
    """Transport + waveform + volume for one audio file."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = ""
        self._duration_ms = 0

        self._audio_output = None
        self._player = None
        if MULTIMEDIA_AVAILABLE:
            self._audio_output = QAudioOutput(self)
            self._audio_output.setVolume(0.8)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio_output)
            self._player.positionChanged.connect(self._on_position)
            self._player.durationChanged.connect(self._on_duration)
            self._player.playbackStateChanged.connect(self._on_state)
            self._player.errorOccurred.connect(self._on_error)
        else:
            log.warning("QtMultimedia is unavailable; in-app playback is disabled")

        layout = vbox(self, spacing=Space.sm)

        self.waveform = WaveformBar(self)
        self.waveform.seek_requested.connect(self._seek_fraction)
        layout.addWidget(self.waveform)

        controls = QWidget(self)
        controls_layout = hbox(controls, spacing=Space.sm)

        self._play_btn = icon_button("play", tooltip="Play", size=18, tone="text",
                                     on_click=self.toggle)
        controls_layout.addWidget(self._play_btn)

        self._position_label = label("0:00", "mono")
        self._position_label.setFixedWidth(44)
        controls_layout.addWidget(self._position_label)

        controls_layout.addStretch(1)

        self._duration_label = label("0:00", "mono")
        controls_layout.addWidget(self._duration_label)

        controls_layout.addSpacing(Space.md)

        volume_icon = icon_button("volume", tooltip="Volume", size=14, tone="muted")
        volume_icon.setEnabled(False)
        controls_layout.addWidget(volume_icon)

        self._volume = QSlider(Qt.Orientation.Horizontal, controls)
        self._volume.setFixedWidth(80)
        self._volume.setRange(0, 100)
        self._volume.setValue(80)
        self._volume.valueChanged.connect(
            lambda value: self._audio_output.setVolume(value / 100.0)
        )
        controls_layout.addWidget(self._volume)

        layout.addWidget(controls)

        self._error_label = label("", "danger")
        self._error_label.setProperty("role", "meta")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        if not MULTIMEDIA_AVAILABLE:
            # The waveform still renders (it comes from ffmpeg), so the item is
            # not a dead panel - only the transport is unavailable.
            self._play_btn.setEnabled(False)
            self._volume.setEnabled(False)
            self._error_label.setProperty("role", "muted")
            self._error_label.setText(
                "Audio playback is unavailable on this system. Use Open file to "
                "play it in your usual player."
            )
            self._error_label.show()

    # ------------------------------------------------------------------

    def set_source(self, path: str) -> None:
        from PySide6.QtCore import QUrl

        self._path = path or ""
        self.waveform.set_peaks([])
        self.waveform.set_position(0.0)
        self._error_label.hide()

        if not path or not Path(path).is_file():
            self._play_btn.setEnabled(False)
            self._error_label.setProperty("role", "meta")
            self._error_label.setText("The audio file is not available.")
            self._error_label.show()
            return

        # The waveform comes from ffmpeg and is worth drawing even when the
        # platform cannot play the file back in-app.
        self._generate_waveform(path)
        if self._player is None:
            return

        self._play_btn.setEnabled(True)
        self._player.setSource(QUrl.fromLocalFile(str(Path(path))))

    def _generate_waveform(self, path: str) -> None:
        generate_waveform(path, self.waveform.set_peaks, owner=self)

    # ------------------------------------------------------------------

    def toggle(self) -> None:
        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def _seek_fraction(self, fraction: float) -> None:
        if self._player is not None and self._duration_ms:
            self._player.setPosition(int(self._duration_ms * fraction))

    def _on_position(self, position_ms: int) -> None:
        self._position_label.setText(format_duration(position_ms / 1000))
        if self._duration_ms:
            self.waveform.set_position(position_ms / self._duration_ms)

    def _on_duration(self, duration_ms: int) -> None:
        self._duration_ms = duration_ms
        self._duration_label.setText(format_duration(duration_ms / 1000))

    def _on_state(self, state) -> None:
        theme = get_theme()
        if theme is None:
            return
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setIcon(theme.icon("pause" if playing else "play", 18, "text"))
        self._play_btn.setToolTip("Pause" if playing else "Play")

    def _on_error(self, error, message: str = "") -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        log.debug("Audio playback error: %s %s", error, message)
        self._error_label.setText(
            "This format cannot be previewed here. Use Open file to play it externally."
        )
        self._error_label.show()
