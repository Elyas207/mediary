"""The preview dock: audition audio without leaving the library.

The reason this exists rather than reusing the detail dialog: finding the right
whoosh means listening to fifteen of them. A modal per file turns that into
fifteen open-listen-close cycles, and you lose your place in the grid every
time. A docked player keeps the list in front of you and makes auditioning a
single click per item, which is how every sound library worth using behaves.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QSlider, QWidget

from app.models.media import MediaItem
from app.ui.theme import Size, Space, get_theme
from app.ui.theme.motion import Duration, animate, grow_height
from app.ui.widgets.audio_player import MULTIMEDIA_AVAILABLE, WaveformBar, generate_waveform
from app.ui.widgets.common import (
    ElidedLabel,
    button,
    hbox,
    icon_button,
    label,
    vbox,
)
from app.ui.widgets.thumbnail import Thumbnail
from app.utils.formatting import format_duration
from app.utils.logging import get_logger

log = get_logger("preview")

BAR_HEIGHT = 68


class PreviewBar(QFrame):
    """A docked transport for the item currently being auditioned."""

    closed = Signal()
    open_detail_requested = Signal(object)     # MediaItem
    playing_changed = Signal(object, bool)     # MediaItem, is_playing

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewBar")
        self.item: MediaItem | None = None
        self._duration_ms = 0
        self._player = None
        self._audio_output = None

        self.setMaximumHeight(0)   # collapsed until something is previewed
        self.setMinimumHeight(0)

        layout = hbox(self, spacing=Space.md, margins=(Space.lg, Space.sm, Space.md, Space.sm))

        # -- What is playing ------------------------------------------------
        self.thumb = Thumbnail(radius=5, aspect=1.0, fallback_icon="waveform", parent=self)
        self.thumb.setFixedSize(QSize(44, 44))
        layout.addWidget(self.thumb)

        text_column = vbox(spacing=1)
        self.title = ElidedLabel("", "itemTitle", parent=self)
        self.title.setMinimumWidth(120)
        text_column.addWidget(self.title)
        self.subtitle = ElidedLabel("", "muted", parent=self)
        text_column.addWidget(self.subtitle)
        layout.addLayout(text_column, 2)

        # -- Transport --------------------------------------------------------
        self.play_btn = icon_button("play", tooltip="Play / pause  (Space)", size=18, tone="text")
        self.play_btn.clicked.connect(self.toggle)
        layout.addWidget(self.play_btn)

        self.position_label = label("0:00", "mono")
        self.position_label.setFixedWidth(40)
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.position_label)

        self.waveform = WaveformBar(self)
        self.waveform.setFixedHeight(34)
        self.waveform.setMinimumWidth(160)
        self.waveform.seek_requested.connect(self._seek_fraction)
        layout.addWidget(self.waveform, 5)

        self.duration_label = label("0:00", "mono")
        self.duration_label.setFixedWidth(40)
        layout.addWidget(self.duration_label)

        # -- Output -----------------------------------------------------------
        volume_icon = icon_button("volume", tooltip="Volume", size=14, tone="muted")
        volume_icon.setEnabled(False)
        layout.addWidget(volume_icon)

        self.volume = QSlider(Qt.Orientation.Horizontal, self)
        self.volume.setFixedWidth(78)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.valueChanged.connect(self._on_volume)
        layout.addWidget(self.volume)

        self.details_btn = button("Details", variant="ghost", size="sm")
        self.details_btn.clicked.connect(
            lambda: self.item and self.open_detail_requested.emit(self.item)
        )
        layout.addWidget(self.details_btn)

        close = icon_button("close", tooltip="Close preview  (Esc)", size=13, tone="muted")
        close.clicked.connect(self.close_preview)
        layout.addWidget(close)

        self._build_player()

    # ------------------------------------------------------------------

    def _build_player(self) -> None:
        if not MULTIMEDIA_AVAILABLE:
            self.play_btn.setEnabled(False)
            self.volume.setEnabled(False)
            self.play_btn.setToolTip("Audio playback is unavailable on this system")
            return

        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(0.8)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)

    @property
    def is_available(self) -> bool:
        return self._player is not None

    @property
    def is_playing(self) -> bool:
        if self._player is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer

        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ------------------------------------------------------------------
    # Showing and hiding
    # ------------------------------------------------------------------

    def preview(self, item: MediaItem) -> None:
        """Start auditioning ``item``, or toggle it if it is already loaded."""
        if self.item is not None and self.item.id == item.id:
            self.toggle()
            return

        previous = self.item
        self.item = item
        if previous is not None:
            self.playing_changed.emit(previous, False)

        self.title.setText(item.display_title)
        bits = [b for b in (item.creator, item.category) if b]
        if item.container:
            bits.append(item.container.upper())
        self.subtitle.setText("  ·  ".join(bits))

        from app.models.category import resolve_category

        theme = get_theme()
        colour = (
            theme.palette.category(resolve_category(item.category).accent)
            if theme is not None else ""
        )
        self.thumb.set_placeholder(item.display_title, colour)
        self.thumb.set_source(item.thumbnail_path, max_edge=160)
        self.thumb.set_fallback_icon("music" if item.category == "Music" else "waveform")

        self.waveform.set_peaks([])
        self.waveform.set_position(0.0)
        self.duration_label.setText(format_duration(item.duration))
        self.position_label.setText("0:00")

        self.expand()

        if not item.exists:
            self.subtitle.setText("File unavailable")
            self.play_btn.setEnabled(False)
            return

        generate_waveform(item.file_path, self.waveform.set_peaks, owner=self)

        if self._player is None:
            return
        from PySide6.QtCore import QUrl

        self.play_btn.setEnabled(True)
        self._player.setSource(QUrl.fromLocalFile(str(Path(item.file_path))))
        self._player.play()

    def expand(self) -> None:
        if self.maximumHeight() >= BAR_HEIGHT:
            return
        self.show()
        self.setMinimumHeight(BAR_HEIGHT)
        grow_height(self, BAR_HEIGHT, duration=Duration.normal)

    def close_preview(self) -> None:
        self.stop()
        item, self.item = self.item, None
        if item is not None:
            self.playing_changed.emit(item, False)

        self.setMinimumHeight(0)
        grow_height(self, 0, duration=Duration.fast, on_finished=self.hide)
        self.closed.emit()

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def toggle(self) -> None:
        if self._player is None or self.item is None:
            return
        if self.is_playing:
            self._player.pause()
        else:
            self._player.play()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def _seek_fraction(self, fraction: float) -> None:
        if self._player is not None and self._duration_ms:
            self._player.setPosition(int(self._duration_ms * fraction))

    def _on_volume(self, value: int) -> None:
        if self._audio_output is not None:
            self._audio_output.setVolume(value / 100.0)

    def _on_position(self, position_ms: int) -> None:
        self.position_label.setText(format_duration(position_ms / 1000))
        if self._duration_ms:
            self.waveform.set_position(position_ms / self._duration_ms)

    def _on_duration(self, duration_ms: int) -> None:
        self._duration_ms = duration_ms
        if duration_ms:
            self.duration_label.setText(format_duration(duration_ms / 1000))

    def _on_state(self, state) -> None:
        theme = get_theme()
        if theme is None:
            return
        playing = self.is_playing
        self.play_btn.setIcon(theme.icon("pause" if playing else "play", 18, "text"))
        if self.item is not None:
            self.playing_changed.emit(self.item, playing)

    def _on_error(self, error, message: str = "") -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if error == QMediaPlayer.Error.NoError:
            return
        log.debug("Preview playback error: %s %s", error, message)
        self.subtitle.setText("This format cannot be previewed here — use Open file")

    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.close_preview()
            return
        super().keyPressEvent(event)


_ = (Size, animate)   # kept for the shared metrics/motion vocabulary
