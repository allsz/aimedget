"""
Miniatura de um TEMA do Volume e mixer para a galeria do Hub.

Reaproveita o mixer "headless" (um VolumeMixerFlyout que nunca é mostrado, só desenhado), que é DIFERENTE do
flyout vivo. Aplica o tema nele só durante o desenho e SEMPRE devolve o visual padrão no fim (as outras
miniaturas, como a da Visão geral, esperam o padrão). Só a região do card + a arte que passa da borda é
desenhada, então figurinhas e sombra aparecem sem sobras.
"""

import math

from PySide6.QtCore import QPoint, QRect, QRectF, QSizeF
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtCore import Qt

from app.core.preview_registry import SkinSpec
from app.widgets.volume_mixer.theme import MixerTheme, default_theme
from app.widgets.volume_mixer.theme_shape import art_overflow

WIDGET_ID = "mixer_theme"
MIN_PAD = 14.0   # mesmo respiro da miniatura do mixer na Visão geral


def _pads(theme: MixerTheme, card: QRectF) -> tuple[float, float, float, float]:
    ov = art_overflow(theme, card.width(), (card.height(),))
    return tuple(max(MIN_PAD, math.ceil(v)) for v in ov)


def _card_size() -> QRectF:
    from app.widgets.volume_mixer.specs import _get_headless_volume_mixer
    return _get_headless_volume_mixer()._card_rect()


def _paint(p, rect: QRectF, theme: MixerTheme, _hub_theme=None):
    from app.widgets.volume_mixer.specs import _get_headless_volume_mixer
    flyout = _get_headless_volume_mixer()
    flyout._apply_theme(theme)
    try:
        card = flyout._card_rect()
        pl, pt, pr, pb = _pads(theme, card)
        source = QRect(int(card.left() - pl), int(card.top() - pt),
                       int(card.width() + pl + pr), int(card.height() + pt + pb))
        # A miniatura é bem menor que o card. Desenhar o card direto nessa escala reduz as imagens do tema (logo,
        # algarismos) de uma vez só pelo filtro bilinear, que serrilha, e os traços finos viram fração de pixel.
        # Então: desenha o card num buffer em escala >= 2x e reduz UMA vez com filtro suave (média de área).
        tf = p.transform()
        dpr = p.device().devicePixelRatioF()
        final = math.hypot(tf.m11(), tf.m12()) * dpr            # pixels do dispositivo por px lógico do card
        if final >= 1.0:                                         # sem redução: desenho direto, igual ao do mixer
            p.save()
            flyout.render(p, QPoint(int(rect.x()), int(rect.y())), QRegion(source))
            p.restore()
            return
        k = 2.0
        w, h = source.width(), source.height()
        buf = QImage(max(1, round(w * k)), max(1, round(h * k)), QImage.Format.Format_ARGB32_Premultiplied)
        buf.fill(0)
        q = QPainter(buf)
        q.scale(k, k)
        flyout.render(q, QPoint(0, 0), QRegion(source))
        q.end()
        buf = buf.scaled(max(1, round(w * final)), max(1, round(h * final)),
                         Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(rect.x(), rect.y(), float(w), float(h)), buf)
        p.restore()
    finally:
        flyout._apply_theme(default_theme())   # o mixer de miniaturas volta ao visual "Windows" do modo atual


def _natural(theme: MixerTheme) -> QSizeF:
    card = _card_size()
    pl, pt, pr, pb = _pads(theme, card)
    return QSizeF(card.width() + pl + pr, card.height() + pt + pb)


def make_theme_spec(theme_id: str, title: str, theme: MixerTheme) -> SkinSpec:
    return SkinSpec(
        id=theme_id, widget_id=WIDGET_ID, title=title, subtitle="",
        natural_size=_natural, paint=_paint, mock_state=lambda: theme,
    )
