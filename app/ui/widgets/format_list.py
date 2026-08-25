"""The pick-a-format lists on an analysed item.

Two panels sit side by side: what the source offers as video, and what it can
be turned into as audio. Every row states the size, because "1080p" and "720p"
are not a real choice until you know one is 1.2 GB and the other is 240 MB.

Sizes the source reported are shown plainly. Sizes Mediary worked out for a
conversion it has not performed yet are prefixed with ``~``, because an
estimate presented as a fact is a small lie that costs the user disk space.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QRadioButton,
    QSizePolicy,
    QWidget,
)

from app.models.download import (
    MP3_BITRATES,
    MediaInfo,
    quality_to_height,
)
from app.ui.theme import Space
from app.ui.widgets.common import ElidedLabel, hbox, label, vbox
from app.utils.formatting import format_bytes


@dataclass
class FormatChoice:
    """One selectable row."""

    value: str          # the quality ladder entry, or "<fmt>@<bitrate>"
    title: str          # "Best Quality", "1080p", "MP3"
    spec: str           # "MP4 · 1080p", "320 kbps"
    size: int = 0       # bytes; 0 means unknown
    estimated: bool = False
    best: bool = False

    def size_label(self) -> str:
        if not self.size:
            return "—"
        return ("~" if self.estimated else "") + format_bytes(self.size)


class FormatRow(QFrame):
    """A radio, a title, and the two facts needed to choose between rows."""

    def __init__(self, choice: FormatChoice, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FormatRow")
        self.choice = choice
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = hbox(self, spacing=Space.sm, margins=(Space.sm, 5, Space.sm, 5))

        self.radio = QRadioButton(self)
        self.radio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.radio.toggled.connect(self._sync)
        layout.addWidget(self.radio)

        self.title = ElidedLabel(choice.title, "itemTitle", parent=self)
        self.title.setMinimumWidth(76)
        layout.addWidget(self.title, 1)

        self.spec = label(choice.spec, "meta", parent=self)
        self.spec.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.spec)

        self.size = label(choice.size_label(), "meta", parent=self)
        self.size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.size.setFixedWidth(66)
        layout.addWidget(self.size)

        self._sync(False)

    def _sync(self, checked: bool) -> None:
        self.setProperty("active", "true" if checked else "false")
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # The whole row is the target. A 13px radio is not.
        self.radio.setChecked(True)
        super().mousePressEvent(event)


class FormatList(QFrame):
    """One titled panel of mutually exclusive format rows."""

    changed = Signal(str)          # the selected value
    auto_toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        auto_text: str = "Automatically select best quality",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InsetPanel")
        self._rows: dict = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._updating = False

        self._layout = vbox(self, spacing=2, margins=(Space.sm,) * 4)

        self._title = label(title, "sectionLabel", parent=self)
        self._title.setContentsMargins(Space.sm, 2, 0, Space.xs)
        self._layout.addWidget(self._title)

        self._rows_holder = QWidget(self)
        self._rows_layout = vbox(self._rows_holder, spacing=1)
        self._layout.addWidget(self._rows_holder)

        self._empty = label("This source offers none.", "muted", parent=self)
        self._empty.setContentsMargins(Space.sm, Space.sm, Space.sm, Space.sm)
        self._layout.addWidget(self._empty)

        self._layout.addStretch(1)

        self.auto_check = QCheckBox(auto_text, self)
        self.auto_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_check.toggled.connect(self._on_auto)
        self._layout.addWidget(self.auto_check)

    # ------------------------------------------------------------------

    def set_choices(self, choices: list) -> None:
        """Rebuild the rows. Keeps the current selection where it still exists."""
        previous = self.value()
        self._updating = True

        while self._rows_layout.count():
            widget = self._rows_layout.takeAt(0).widget()
            if widget is not None:
                self._group.removeButton(widget.radio)
                widget.deleteLater()
        self._rows.clear()

        for choice in choices:
            row = FormatRow(choice, self._rows_holder)
            row.radio.toggled.connect(
                lambda checked, v=choice.value: self._on_selected(checked, v)
            )
            self._group.addButton(row.radio)
            self._rows_layout.addWidget(row)
            self._rows[choice.value] = row

        has_rows = bool(choices)
        self._rows_holder.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        self.auto_check.setEnabled(has_rows)

        self._updating = False
        if previous and previous in self._rows:
            self.set_value(previous)
        elif choices:
            self.set_value(choices[0].value)

    def set_value(self, value: str) -> None:
        row = self._rows.get(value)
        if row is None or row.radio.isChecked():
            return
        self._updating = True
        row.radio.setChecked(True)
        self._updating = False

    def value(self) -> str:
        for value, row in self._rows.items():
            if row.radio.isChecked():
                return value
        return ""

    def set_auto(self, on: bool) -> None:
        blocked = self.auto_check.blockSignals(True)
        self.auto_check.setChecked(on)
        self.auto_check.blockSignals(blocked)
        self._apply_auto(on)

    def is_auto(self) -> bool:
        return self.auto_check.isChecked()

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt naming
        super().setEnabled(enabled)
        self.setProperty("dim", "false" if enabled else "true")
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    # ------------------------------------------------------------------

    def _on_selected(self, checked: bool, value: str) -> None:
        if not checked or self._updating:
            return
        self.changed.emit(value)

    def _on_auto(self, on: bool) -> None:
        self._apply_auto(on)
        self.auto_toggled.emit(on)

    def _apply_auto(self, on: bool) -> None:
        """On auto, the rows go read-only and jump to the best entry.

        Leaving them clickable while the choice is being made for you is the
        kind of control that looks live and silently ignores you.
        """
        self._rows_holder.setEnabled(not on)
        if not on:
            return
        best = next((v for v, r in self._rows.items() if r.choice.best), "")
        if best:
            self.set_value(best)


# ---------------------------------------------------------------------------
# Turning a probe into rows
# ---------------------------------------------------------------------------


def video_choices(info: MediaInfo, container: str = "mp4") -> list:
    """One row per resolution the source actually offers, best first."""
    if not info.has_video:
        return []

    choices: list = []
    seen: set = set()
    for quality in info.available_video_qualities:
        if quality == "best":
            match = _largest_video(info)
            height = match.height if match else info.best_height
            title = "Best quality"
        else:
            match = _video_at(info, quality_to_height(quality))
            if match is None:
                continue
            height = match.height
            # "360p" on a source whose smallest stream is 480p would promise a
            # file it cannot produce, and would show 480p's size next to it.
            if height in seen:
                continue
            title = quality
        seen.add(height)
        spec = f"{container.upper()} · {height}p" if height else container.upper()
        choices.append(
            FormatChoice(
                value=quality,
                title=title,
                spec=spec,
                size=_total_size(info, match),
                estimated=match is None or not match.filesize,
                best=(quality == "best"),
            )
        )
    return choices


def audio_choices(info: MediaInfo) -> list:
    """One row per audio format Mediary can produce from this source.

    Sizes here are arithmetic, not measurement: the file does not exist yet.
    """
    duration = info.duration or 0.0
    choices: list = []

    source = _best_audio(info)
    if source is not None:
        size = source.filesize or _size_from_bitrate(duration, source.abr or source.tbr)
        choices.append(
            FormatChoice(
                value="source",
                title="Best quality",
                spec=_audio_spec(source),
                size=size,
                estimated=not source.filesize,
                best=True,
            )
        )

    # An MP3 ladder plus the two lossless containers. Listing every format at
    # every bitrate would be eleven rows that mostly differ by a megabyte,
    # which is a longer list rather than a better choice.
    for rate in reversed(MP3_BITRATES):
        choices.append(
            FormatChoice(
                value=f"mp3@{rate}",
                title="MP3",
                spec=f"{rate} kbps",
                size=_size_from_bitrate(duration, float(rate)),
                estimated=True,
            )
        )
    for fmt in ("wav", "flac"):
        choices.append(
            FormatChoice(
                value=f"{fmt}@lossless",
                title=fmt.upper(),
                spec="Lossless",
                size=_lossless_size(duration, fmt, info),
                estimated=True,
            )
        )
    return choices


def _largest_video(info: MediaInfo):
    videos = [f for f in info.formats if f.has_video and f.height]
    return max(videos, key=lambda f: f.height, default=None)


def _video_at(info: MediaInfo, height: int):
    """The smallest format that still reaches the requested height."""
    candidates = [f for f in info.formats if f.has_video and f.height and f.height >= height]
    return min(candidates, key=lambda f: f.height, default=None)


def _best_audio(info: MediaInfo):
    audios = [f for f in info.formats if f.has_audio and not f.has_video]
    if not audios:
        audios = [f for f in info.formats if f.has_audio]
    return max(audios, key=lambda f: (f.abr or f.tbr or 0), default=None)


def _total_size(info: MediaInfo, video) -> int:
    """A video-only stream is muxed with audio, so quote the pair."""
    if video is None:
        return 0
    size = video.filesize or 0
    if size and not video.has_audio:
        audio = _best_audio(info)
        if audio is not None:
            size += audio.filesize or _size_from_bitrate(info.duration, audio.abr or audio.tbr)
    return size


def _audio_spec(fmt) -> str:
    rate = fmt.abr or fmt.tbr
    if rate:
        return f"{fmt.ext.upper()} · {rate:.0f} kbps"
    return fmt.ext.upper()


def _size_from_bitrate(duration: float, kbps: float) -> int:
    if not duration or not kbps:
        return 0
    return int(duration * kbps * 1000 / 8)


def _lossless_size(duration: float, fmt: str, info: MediaInfo) -> int:
    """WAV is exact arithmetic; FLAC lands around 60% of it."""
    if not duration:
        return 0
    sample_rate = 44100
    raw = int(duration * sample_rate * 2 * 2)      # stereo, 16-bit
    return raw if fmt == "wav" else int(raw * 0.6)


__all__ = [
    "FormatChoice",
    "FormatList",
    "FormatRow",
    "audio_choices",
    "video_choices",
]
