"""
Especificação declarativa para o Volume Mixer Flyout.
Renderiza a miniatura realista do controle de volume Master e por aplicativo.
"""

from PySide6.QtCore import QSizeF, QPoint, QRectF
from PySide6.QtGui import QPainter, QImage, QColor
from app.core.preview_registry import WidgetSpec, register_widget, get_widget_spec

_cached_mixer = None


def _get_headless_volume_mixer():
    global _cached_mixer
    if _cached_mixer is None:
        from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout
        from app.services.audio_mixer_service import AppAudioSession

        flyout = VolumeMixerFlyout()
        flyout._slide_t = 1.0

        # Cria linha de app Spotify com ícone vetorial verde
        img = QImage(24, 24, QImage.Format.Format_ARGB32)
        img.fill(0x00000000)
        p_img = QPainter(img)
        p_img.setRenderHint(QPainter.RenderHint.Antialiasing)
        p_img.setBrush(QColor("#1DB954"))
        p_img.setPen(QColor(0, 0, 0, 0))
        p_img.drawEllipse(2, 2, 20, 20)
        p_img.end()

        s1 = AppAudioSession(app_id="spotify", name="Spotify", volume=75, is_muted=False, icon=img)
        flyout.on_sessions_updated([s1])
        flyout.is_expanded = True
        flyout._expand_t = 1.0
        flyout._apply_window_canvas_size(expanded_canvas=True)
        flyout._anim_card_h = flyout._target_expanded_height()
        flyout._hide_timer.stop()
        flyout._anim_timer.stop()
        _cached_mixer = flyout
    return _cached_mixer


def paint_volume(p: QPainter, rect: QRectF, state, theme):
    flyout = _get_headless_volume_mixer()
    card_rect = flyout._card_rect()
    pad = 14
    p.save()
    flyout.render(
        p,
        QPoint(
            int(rect.x() + pad - card_rect.left()),
            int(rect.y() + pad - card_rect.top()),
        ),
    )
    p.restore()


def init_volume_spec() -> WidgetSpec:
    spec = get_widget_spec("vol_mixer")
    if spec:
        return spec
    flyout = _get_headless_volume_mixer()
    card_rect = flyout._card_rect()
    pad = 14
    w = float(card_rect.width() + pad * 2)
    h = float(card_rect.height() + pad * 2)
    spec = WidgetSpec(
        id="vol_mixer",
        title="Per-App Volume",
        subtitle="Minimal Sliders",
        natural_size=QSizeF(w, h),
        paint=paint_volume,
        mock_state=lambda: None,
        category="flyout",
    )
    register_widget(spec)
    return spec
