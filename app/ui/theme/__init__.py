"""Theme controller: resolves the active palette and applies it app-wide."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from app.config.settings import THEME_DARK, THEME_LIGHT, THEME_SYSTEM
from app.ui.theme import icons
from app.ui.theme.stylesheet import build_stylesheet
from app.ui.theme.tokens import DARK, LIGHT, PALETTES, Palette, Radius, Size, Space, Type
from app.utils.logging import get_logger

log = get_logger("theme")

__all__ = [
    "DARK",
    "LIGHT",
    "PALETTES",
    "Palette",
    "Radius",
    "Size",
    "Space",
    "Theme",
    "Type",
    "icons",
]


class Theme(QObject):
    """Applies a palette to the running :class:`QApplication`.

    Also mirrors the palette into Qt's own :class:`QPalette` so native pieces
    (tooltips, text-cursor colours, native dialogs) match the stylesheet.
    """

    changed = Signal(object)   # Palette

    def __init__(
        self,
        app: QApplication,
        preference: str = THEME_SYSTEM,
        *,
        use_system_accent: bool = False,
    ) -> None:
        super().__init__(app)
        self._app = app
        self._preference = preference
        self._use_system_accent = use_system_accent
        self._palette = self._resolve(preference)
        try:
            app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except (AttributeError, TypeError):  # pragma: no cover - older Qt
            pass

    # -- State ------------------------------------------------------------

    @property
    def palette(self) -> Palette:
        return self._palette

    @property
    def preference(self) -> str:
        return self._preference

    @property
    def is_dark(self) -> bool:
        return self._palette.name == "dark"

    # -- Resolution -------------------------------------------------------

    def _resolve(self, preference: str) -> Palette:
        if preference == THEME_DARK:
            base = DARK
        elif preference == THEME_LIGHT:
            base = LIGHT
        else:
            base = DARK if self._system_prefers_dark() else LIGHT
        return self._apply_system_accent(base)

    def _apply_system_accent(self, base: Palette) -> Palette:
        """Recolour the palette's accent from the desktop's own accent colour.

        Only the accent family changes - surfaces, text and semantic colours are
        Mediary's, because a system accent says nothing about those and letting
        it drive them would wreck contrast.
        """
        if not self._use_system_accent:
            return base

        from dataclasses import replace

        from app.ui.theme.system import accent_variants, usable_accent

        colour = usable_accent(dark=base.name == "dark")
        if colour is None:
            return base
        try:
            return replace(base, **accent_variants(colour))
        except Exception:  # noqa: BLE001 - a bad accent must not break theming
            log.debug("Could not apply the system accent", exc_info=True)
            return base

    @property
    def use_system_accent(self) -> bool:
        return self._use_system_accent

    def set_use_system_accent(self, value: bool) -> None:
        self._use_system_accent = bool(value)

    def _system_prefers_dark(self) -> bool:
        try:
            scheme = self._app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False
        except (AttributeError, TypeError):
            pass
        # Fall back to luminance of the platform window colour.
        window = self._app.palette().color(QPalette.ColorRole.Window)
        return window.lightnessF() < 0.5

    def _on_system_scheme_changed(self, *_args) -> None:
        if self._preference == THEME_SYSTEM:
            self.apply(THEME_SYSTEM)

    # -- Application ------------------------------------------------------

    def apply(self, preference: str | None = None) -> Palette:
        """Recompute and install the stylesheet. Returns the active palette."""
        if preference is not None:
            self._preference = preference
        self._palette = self._resolve(self._preference)
        icons.clear_cache()

        self._install_app_font()
        self._install_qss_pixmaps()
        self._app.setStyleSheet(build_stylesheet(self._palette))
        self._apply_qpalette(self._palette)
        self.changed.emit(self._palette)
        return self._palette

    def _apply_qpalette(self, p: Palette) -> None:
        """Keep Qt's native palette in step with the stylesheet."""
        qp = QPalette()
        text = QColor(p.text)
        base = QColor(p.inset)
        window = QColor(p.surface)

        qp.setColor(QPalette.ColorRole.Window, window)
        qp.setColor(QPalette.ColorRole.WindowText, text)
        qp.setColor(QPalette.ColorRole.Base, base)
        qp.setColor(QPalette.ColorRole.AlternateBase, QColor(p.elevated))
        qp.setColor(QPalette.ColorRole.Text, text)
        qp.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text_muted))
        qp.setColor(QPalette.ColorRole.Button, QColor(p.elevated))
        qp.setColor(QPalette.ColorRole.ButtonText, text)
        qp.setColor(QPalette.ColorRole.BrightText, QColor(p.danger))
        qp.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
        qp.setColor(QPalette.ColorRole.HighlightedText, QColor(p.accent_text))
        qp.setColor(QPalette.ColorRole.Link, QColor(p.accent))
        qp.setColor(QPalette.ColorRole.LinkVisited, QColor(p.accent_pressed))
        qp.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.elevated))
        qp.setColor(QPalette.ColorRole.ToolTipText, text)

        disabled = QColor(p.text_muted)
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
        ):
            qp.setColor(QPalette.ColorGroup.Disabled, role, disabled)

        self._app.setPalette(qp)
        try:
            self._app.styleHints().setColorScheme(
                Qt.ColorScheme.Dark if self.is_dark else Qt.ColorScheme.Light
            )
        except (AttributeError, TypeError):
            pass

    def _install_app_font(self) -> None:
        """Set the base application font from the resolved family.

        Setting it on QApplication (as well as in the stylesheet) means native
        widgets and popups inherit it too, and it guarantees a real family is
        in play even if a stylesheet rule is ever missed.
        """
        from PySide6.QtGui import QFont

        from app.ui.theme.tokens import Type, font_family, resolve_fonts

        resolve_fonts(force=True)
        font = QFont(font_family())
        font.setPixelSize(Type.body)
        font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
        self._app.setFont(font)

    def _install_qss_pixmaps(self) -> None:
        """Render the glyphs the stylesheet references via ``url(mediary:name)``.

        Qt cannot draw a chevron from border tricks reliably across platforms,
        so the combo/spin arrows are real images regenerated on every theme
        change and exposed through a QDir search path.
        """
        p = self._palette
        for name, icon_name, colour, size, width in (
            ("check", "check", p.accent_text, 12, 2.6),
            ("chevron-down", "chevron-down", p.text_muted, 10, 2.0),
            ("chevron-down-hover", "chevron-down", p.text, 10, 2.0),
            ("chevron-up", "chevron-up", p.text_muted, 10, 2.0),
            ("chevron-right", "chevron-right", p.text_muted, 10, 2.0),
        ):
            _register_pixmap(
                name,
                icons.icon_pixmap(icon_name, colour, size, stroke_width=width, dpr=1.0),
            )

    # -- Convenience for widgets -----------------------------------------

    def icon(self, name: str, size: int = Size.icon, tone: str = "secondary", **kwargs) -> QIcon:
        """A palette-aware icon. ``tone`` selects the colour role."""
        p = self._palette
        color = {
            "text": p.text,
            "secondary": p.text_secondary,
            "muted": p.text_muted,
            "accent": p.accent,
            "success": p.success,
            "warning": p.warning,
            "danger": p.danger,
            "inverted": p.accent_text,
        }.get(tone, p.text_secondary)
        return icons.make_icon(
            name,
            color,
            size,
            disabled_color=p.text_muted,
            active_color=p.text if tone in ("secondary", "muted") else color,
            dpr=self._device_pixel_ratio(),
            **kwargs,
        )

    def pixmap(self, name: str, size: int = Size.icon, tone: str = "secondary", **kwargs) -> QPixmap:
        p = self._palette
        color = {
            "text": p.text,
            "secondary": p.text_secondary,
            "muted": p.text_muted,
            "accent": p.accent,
            "success": p.success,
            "warning": p.warning,
            "danger": p.danger,
            "inverted": p.accent_text,
        }.get(tone, p.text_secondary)
        return icons.icon_pixmap(name, color, size, dpr=self._device_pixel_ratio(), **kwargs)

    def _device_pixel_ratio(self) -> float:
        try:
            screen = self._app.primaryScreen()
            return float(screen.devicePixelRatio()) if screen else 1.0
        except Exception:  # noqa: BLE001 - headless test environments
            return 1.0


_PIXMAP_REGISTRY: dict = {}


def _register_pixmap(name: str, pixmap: QPixmap) -> None:
    """Expose a generated pixmap to QSS as ``url(mediary:<name>)``."""
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QDir

    directory = _PIXMAP_REGISTRY.get("__dir__")
    if directory is None:
        directory = Path(tempfile.mkdtemp(prefix="mediary-ui-"))
        _PIXMAP_REGISTRY["__dir__"] = directory
        QDir.setSearchPaths("mediary", [str(directory)])
    target = directory / name
    pixmap.save(str(target), "PNG")
    _PIXMAP_REGISTRY[name] = target


_theme: Theme | None = None


def get_theme() -> Theme | None:
    """The installed theme controller, if the app has created one."""
    return _theme


def set_theme(theme: Theme | None) -> None:
    global _theme
    _theme = theme
