"""
PreviewStage - Palco de renderização vetorial sob demanda para miniaturas de widgets e skins.
- Renderiza miniaturas a partir de especificações declarativas (WidgetSpec / SkinSpec).
- Escala matemática dinâmica sem números mágicos ou cortes: min(avail/natural, 1.0).
- Cache offscreen de QPixmap de alta resolução (DPI-aware).
- 0% de overhead de CPU em repouso.
"""

from typing import Any
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QSizePolicy

from app.core.preview_registry import WidgetSpec, SkinSpec
from app.hub.theme import HubTheme, THEME_LIGHT


class PreviewStage(QWidget):
    """
    Componente visual de palco neutro que desenha a miniatura fiel de um widget ou skin.
    """

    def __init__(
        self,
        spec: WidgetSpec | SkinSpec | None = None,
        state: Any = None,
        theme: HubTheme = THEME_LIGHT,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._spec = spec
        self._state = state if state is not None else (spec.mock_state() if spec else None)
        self._theme = theme

        self._cached_pixmap: QPixmap | None = None
        self._cache_key: tuple | None = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_spec(self, spec: WidgetSpec | SkinSpec, state: Any = None):
        if self._spec != spec or state is not None:
            self._spec = spec
            self._state = state if state is not None else spec.mock_state()
            self._invalidate_cache()
            self.update()

    def set_theme(self, theme: HubTheme):
        if self._theme != theme:
            self._theme = theme
            self._invalidate_cache()
            self.update()

    def set_state(self, state: Any):
        self._state = state
        self._invalidate_cache()
        self.update()

    def _invalidate_cache(self):
        self._cached_pixmap = None
        self._cache_key = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._invalidate_cache()

    def _render_preview_pixmap(self, stage_w: float, stage_h: float, dpr: float) -> QPixmap:
        px_w = max(1, int(round(stage_w * dpr)))
        px_h = max(1, int(round(stage_h * dpr)))

        pixmap = QPixmap(px_w, px_h)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        if not self._spec:
            return pixmap

        p = QPainter(pixmap)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        natural = (
            self._spec.natural_size(self._state)
            if callable(self._spec.natural_size)
            else self._spec.natural_size
        )
        nat_w = max(1.0, float(natural.width()))
        nat_h = max(1.0, float(natural.height()))

        padding = 10.0
        avail_w = max(10.0, stage_w - padding * 2.0)
        avail_h = max(10.0, stage_h - padding * 2.0)

        scale = min(avail_w / nat_w, avail_h / nat_h, 1.0)
        draw_w = nat_w * scale
        draw_h = nat_h * scale
        draw_x = (stage_w - draw_w) * 0.5
        draw_y = (stage_h - draw_h) * 0.5

        p.save()
        p.translate(draw_x, draw_y)
        p.scale(scale, scale)
        self._spec.paint(p, QRectF(0.0, 0.0, nat_w, nat_h), self._state, self._theme)
        p.restore()
        p.end()

        return pixmap

    def paintEvent(self, event):
        if not self._spec:
            return

        w = float(self.width())
        h = float(self.height())
        if w < 10 or h < 10:
            return

        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else float(self.devicePixelRatio())
        theme_dark = getattr(self._theme, "mode", "dark")
        spec_id = self._spec.id if self._spec else ""
        cache_key = (round(w), round(h), dpr, theme_dark, spec_id)

        if self._cached_pixmap is None or self._cache_key != cache_key:
            self._cached_pixmap = self._render_preview_pixmap(w, h, dpr)
            self._cache_key = cache_key

        if self._cached_pixmap and not self._cached_pixmap.isNull():
            p.drawPixmap(0, 0, self._cached_pixmap)
