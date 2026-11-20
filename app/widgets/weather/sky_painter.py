"""
Fundo animado do cartão de clima: gradiente do céu, manchas de luz que derivam, chuva, neve, neblina, estrelas e
relâmpago. Pintura pura em unidades do cartão de referência (300 x 262); quem chama já escalou o QPainter.

Todo movimento é função do tempo (`now`, em segundos), sem estado: o mesmo instante sempre dá o mesmo quadro, e a
miniatura do Hub é só um `now` fixo.
"""

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient

from app.widgets.weather import motion as mo
from app.widgets.weather.conditions import Blob, Scene

CARD_W = 300.0
CARD_H = 262.0
_RAIN_TILT = math.radians(8.0)
_RAIN_TRAVEL = (-50.0, 380.0)   # `wx-fall`: translate(-50px, 380px)


def paint_sky(p: QPainter, scene: Scene, now: float, animated: bool, opacity: float = 1.0):
    """Céu completo (camada suave + partículas)."""
    paint_sky_soft(p, scene, now, animated, opacity)
    paint_sky_particles(p, scene, now, animated, opacity)


def paint_sky_soft(p: QPainter, scene: Scene, now: float, animated: bool, opacity: float = 1.0):
    """Só o que é desfocado por natureza (gradiente, manchas, neblina, clarão): pode ser desenhado em baixa
    resolução e ampliado sem perda visível — é a parte cara do quadro."""
    if opacity <= 0.0:
        return
    p.save()
    p.setOpacity(p.opacity() * opacity)
    grad = QLinearGradient(0, 0, 0, CARD_H)
    for pos, color in scene.sky:
        grad.setColorAt(pos, QColor(color))
    p.fillRect(QRectF(0, 0, CARD_W, CARD_H), grad)
    for blob in scene.blobs:
        _paint_blob(p, blob, now if animated else 0.0)
    if scene.fog:
        _paint_fog(p, scene.fog, now if animated else 0.0)
    if animated and scene.flash:
        _paint_flash(p, now)
    p.restore()


def paint_sky_particles(p: QPainter, scene: Scene, now: float, animated: bool, opacity: float = 1.0):
    """Estrelas, chuva e neve: traços finos, sempre na resolução da tela."""
    if opacity <= 0.0 or not (scene.stars or scene.rain or scene.snow):
        return
    p.save()
    p.setOpacity(p.opacity() * opacity)
    if scene.stars:
        _paint_stars(p, scene.stars, now if animated else 0.0)
    if animated:   # partículas não existem com os efeitos do Windows desligados (como reduced-motion)
        if scene.rain:
            _paint_rain(p, scene, now)
        if scene.snow:
            _paint_snow(p, scene.snow, now)
    elif scene.snow:
        _paint_snow(p, scene.snow, 2.3)   # neve parada ainda diz "neve"
    p.restore()


def _paint_blob(p: QPainter, b: Blob, now: float):
    d = mo.alternate(now, mo.DRIFT_DUR * b.slow, mo.EASE_IN_OUT, reverse=b.reverse)
    dx = mo.DRIFT_DISTANCE * d
    dy = -0.6 * mo.DRIFT_DISTANCE * d
    scale = 1.0 + 0.08 * d
    cx = b.x + b.w / 2 + dx
    cy = b.y + b.h / 2 + dy
    r, g, bl, a = b.rgba

    p.save()
    p.translate(cx, cy)
    p.scale(b.w / 2 * scale, b.h / 2 * scale)
    grad = QRadialGradient(QPointF(0, 0), 1.0)
    # CSS: o gradiente vai até o canto mais distante (raio * raiz de 2) e a caixa recorta numa elipse
    stop = min(1.0, b.stop * math.sqrt(2.0))
    grad.setColorAt(0.0, QColor(r, g, bl, int(a * 255)))
    grad.setColorAt(stop, QColor(r, g, bl, 0))
    grad.setColorAt(1.0, QColor(r, g, bl, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QPointF(0, 0), 1.0, 1.0)
    p.restore()


# O risco de chuva vai de transparente (topo) à cor cheia (base). Um gradiente por risco a cada quadro custava caro
# (chuva forte = ~25% de um núcleo); em vez disso cada risco é feito de trechos de cor sólida com alfa crescente,
# agrupados por alfa para desenhar todos os riscos de um mesmo tom numa chamada só.
_RAIN_SEGMENTS = 4


def _paint_rain(p: QPainter, scene: Scene, now: float):
    lo, hi = scene.rain_len
    sx, sy = -math.sin(_RAIN_TILT), math.cos(_RAIN_TILT)
    batches = [[] for _ in range(_RAIN_SEGMENTS)]
    for i in range(scene.rain):
        x_pct = min(((i * 37) % 100) + (i % 3) * 2, 112)
        length = lo + (i * 7) % max(1, (hi - lo + 1))
        prog = (now / (scene.rain_ms / 1000.0) + mo.golden_spread(i)) % 1.0
        x = CARD_W * x_pct / 100.0 + _RAIN_TRAVEL[0] * prog
        y = -24.0 + _RAIN_TRAVEL[1] * prog
        if y > CARD_H or y + length < 0:
            continue
        step = length / _RAIN_SEGMENTS
        for k in range(_RAIN_SEGMENTS):
            a, b = k * step, (k + 1) * step
            batches[k].append(QLineF(x + sx * a, y + sy * a, x + sx * b, y + sy * b))
    p.save()
    for k, lines in enumerate(batches):
        if not lines:
            continue
        alpha = scene.rain_alpha * (k + 0.5) / _RAIN_SEGMENTS
        p.setPen(QPen(QColor(255, 255, 255, int(alpha * 255)), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawLines(lines)
    p.restore()


def _paint_snow(p: QPainter, count: int, now: float):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(count):
        dur = 5.0 + (i % 4) * 0.9
        prog = (now / dur + mo.golden_spread(i * 3 + 1)) % 1.0
        x = mo.golden_spread(i) * CARD_W * 1.1 - CARD_W * 0.05 + math.sin(now * 0.8 + i * 1.7) * 6.0
        y = -6.0 + prog * (CARD_H + 12.0)
        radius = 1.1 + (i % 3) * 0.55
        alpha = 0.5 + (i % 2) * 0.3
        p.setBrush(QColor(255, 255, 255, int(alpha * 255)))
        p.drawEllipse(QPointF(x, y), radius, radius)
    p.restore()


def _paint_fog(p: QPainter, count: int, now: float):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(count):
        period = 14.0 + i * 3.0
        dx = math.sin((now / period) * 2 * math.pi + i * 1.3) * 30.0
        cy = 70.0 + i * (170.0 / max(1, count - 1))
        w = CARD_W * 1.5
        h = 46.0 + (i % 2) * 18.0
        p.save()
        p.translate(CARD_W / 2 + dx + (i % 2) * 20 - 10, cy)
        p.scale(w / 2, h / 2)
        grad = QRadialGradient(QPointF(0, 0), 1.0)
        grad.setColorAt(0.0, QColor(235, 240, 245, 52))
        grad.setColorAt(0.7, QColor(235, 240, 245, 16))
        grad.setColorAt(1.0, QColor(235, 240, 245, 0))
        p.setBrush(grad)
        p.drawEllipse(QPointF(0, 0), 1.0, 1.0)
        p.restore()
    p.restore()


def _paint_stars(p: QPainter, count: int, now: float):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(count):
        x = 8.0 + mo.golden_spread(i) * (CARD_W - 16.0)
        y = 6.0 + mo.golden_spread(i * 7 + 3) * CARD_H * 0.62
        radius = 0.6 + (i % 3) * 0.35
        twinkle = mo.wave(now, 2.5 + (i % 5) * 0.7, mo.golden_spread(i * 5))
        alpha = 0.25 + 0.6 * twinkle
        p.setBrush(QColor(255, 255, 255, int(alpha * 255)))
        p.drawEllipse(QPointF(x, y), radius, radius)
    p.restore()


def _paint_flash(p: QPainter, now: float):
    x = (now % mo.FLASH_DUR) / mo.FLASH_DUR
    opacity = mo.keyframes(x, mo.FLASH_FRAMES, mo.EASE_OUT)
    if opacity <= 0.001:
        return
    p.save()
    p.setOpacity(p.opacity() * opacity)
    p.translate(CARD_W * 0.7, 0.0)
    p.scale(CARD_W * 0.95, CARD_H * 1.1)
    grad = QRadialGradient(QPointF(0, 0), 1.0)
    grad.setColorAt(0.0, QColor(255, 255, 255, 128))
    grad.setColorAt(0.7, QColor(255, 255, 255, 0))
    grad.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRect(QRectF(-2, -1, 4, 3))
    p.restore()
