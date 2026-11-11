"""
Mídia de demonstração das miniaturas do Hub (a "música" que toca em todas as skins do preview).

Sem mídia, cada skin cai no fundo padrão (azul) e a miniatura não parece a skin real. Aqui há duas imagens:
- `cover`: a capa. Um entardecer (violeta, faixa de azul-petróleo, magenta e rosa empoeirado) com o logo do Aimedget.
- `backdrop`: só o entardecer, SEM o logo. É de onde as skins tiram a paleta do fundo: o logo é laranja e, se
  entrasse na extração, o fundo das skins ficaria laranja (cor reservada à seleção no Hub).

Cada skin aplica isso por `BaseMusicSkin.apply_preview_media` (o padrão serve para qualquer skin nova; só quem tem
estado próprio, como a Capa Empilhada, sobrescreve). Para mudar o visual de TODOS os previews, é só editar este arquivo.
"""

from dataclasses import dataclass
from math import sin

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPolygonF, QRadialGradient
from PySide6.QtSvg import QSvgRenderer

from app.core.paths import APP_ICON_CLEAN_SVG

SIZE = 512
LOGO_FRACTION = 0.30   # largura do logo em relação à capa (maior que isso invade o título nas skins de capa cheia)


@dataclass(frozen=True)
class PreviewMedia:
    cover: QImage
    cover_bytes: bytes   # a mesma capa em PNG, no formato que as skins recebem do player
    backdrop: QImage


_cached: PreviewMedia | None = None


def _paint_backdrop() -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # O petróleo é só uma faixa estreita: as skins tiram o matiz dominante da imagem, e um violeta puxado para o azul
    # (ou muito petróleo) faria o fundo delas voltar a parecer azul
    sky = QLinearGradient(QPointF(0, 0), QPointF(SIZE * 0.35, SIZE))
    sky.setColorAt(0.00, QColor("#7a45c8"))
    sky.setColorAt(0.17, QColor("#3a8fa6"))
    sky.setColorAt(0.40, QColor("#a85bc8"))
    sky.setColorAt(0.74, QColor("#d77fb2"))
    sky.setColorAt(1.00, QColor("#e8a3b8"))
    p.fillRect(img.rect(), sky)

    # Brilho rosa claro baixo (profundidade sem tom quente)
    glow = QRadialGradient(QPointF(SIZE * 0.68, SIZE * 0.66), SIZE * 0.42)
    glow.setColorAt(0.0, QColor(255, 214, 232, 235))
    glow.setColorAt(0.45, QColor(244, 160, 196, 120))
    glow.setColorAt(1.0, QColor(244, 160, 196, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QPointF(SIZE * 0.68, SIZE * 0.66), SIZE * 0.42, SIZE * 0.42)

    # Duas colinas em silhueta para não parecer só um degradê
    for color, base, amp, phase in ((QColor(30, 22, 74, 200), 0.80, 0.07, 0.0), (QColor(18, 14, 52, 235), 0.90, 0.05, 1.7)):
        pts = [QPointF(0, SIZE)]
        steps = 32
        for i in range(steps + 1):
            pts.append(QPointF(SIZE * i / steps, SIZE * (base + amp * sin(i / steps * 6.283 * 1.1 + phase))))
        pts.append(QPointF(SIZE, SIZE))
        p.setBrush(color)
        p.drawPolygon(QPolygonF(pts))

    p.end()
    return img


def _paint_cover(backdrop: QImage) -> QImage:
    img = backdrop.copy()
    renderer = QSvgRenderer(APP_ICON_CLEAN_SVG)
    if renderer.isValid():
        side = SIZE * LOGO_FRACTION
        view = renderer.viewBoxF()
        ratio = view.height() / view.width() if view.width() else 1.0
        w, h = side, side * ratio
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Um halo escuro bem suave atrás do logo garante leitura sobre o rosa claro
        halo = QRadialGradient(QPointF(SIZE / 2, SIZE * 0.46), side * 0.85)
        halo.setColorAt(0.0, QColor(24, 14, 56, 150))
        halo.setColorAt(1.0, QColor(24, 14, 56, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(SIZE / 2, SIZE * 0.46), side * 0.85, side * 0.85)
        renderer.render(p, QRectF((SIZE - w) / 2, SIZE * 0.46 - h / 2, w, h))
        p.end()
    return img


def preview_media() -> PreviewMedia:
    """A mídia de demonstração; é desenhada uma vez só."""
    global _cached
    if _cached is None:
        backdrop = _paint_backdrop()
        cover = _paint_cover(backdrop)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        cover.save(buf, "PNG")
        buf.close()
        _cached = PreviewMedia(cover=cover, cover_bytes=bytes(data), backdrop=backdrop)
    return _cached
