import math
from dataclasses import dataclass
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QLinearGradient, QRadialGradient


@dataclass
class ThemePalette:
    """Paleta de cores adaptativa para o fundo do widget."""
    stop0: QColor        # Esquerda (fundo escuro profundo atrás do texto)
    stop1: QColor        # Meio-esquerda (transição escura saturada)
    stop2: QColor        # Meio-direita (cor dominante principal da capa)
    stop3: QColor        # Direita (tom luminoso atrás do disco de vinil)
    glow: QColor         # Luz radial no topo direito (cx=0.74, cy=0.20)
    bottom_shade: QColor # Vinheta escura inferior para garantir contraste com barra branca e botões


def get_default_palette() -> ThemePalette:
    """Retorna a paleta azul original do widget-bg.svg."""
    return ThemePalette(
        stop0=QColor("#03070f"),
        stop1=QColor("#0a2748"),
        stop2=QColor("#1566a3"),
        stop3=QColor("#1a86bd"),
        glow=QColor(92, 195, 255, 89),
        bottom_shade=QColor(2, 6, 15, 95),
    )


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
        int(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def lerp_palette(p1: ThemePalette, p2: ThemePalette, t: float) -> ThemePalette:
    """Interpola suavemente entre duas paletas para transição fluida ao trocar de faixa."""
    return ThemePalette(
        stop0=_lerp_color(p1.stop0, p2.stop0, t),
        stop1=_lerp_color(p1.stop1, p2.stop1, t),
        stop2=_lerp_color(p1.stop2, p2.stop2, t),
        stop3=_lerp_color(p1.stop3, p2.stop3, t),
        glow=_lerp_color(p1.glow, p2.glow, t),
        bottom_shade=_lerp_color(p1.bottom_shade, p2.bottom_shade, t),
    )


def palettes_are_close(p1: ThemePalette, p2: ThemePalette, threshold: int = 2) -> bool:
    """Verifica se a transição entre duas paletas já convergiu."""
    for attr in ("stop0", "stop1", "stop2", "stop3", "glow", "bottom_shade"):
        c1: QColor = getattr(p1, attr)
        c2: QColor = getattr(p2, attr)
        if (
            abs(c1.red() - c2.red()) > threshold
            or abs(c1.green() - c2.green()) > threshold
            or abs(c1.blue() - c2.blue()) > threshold
        ):
            return False
    return True


def extract_palette_from_image(img: QImage | None) -> ThemePalette:
    """
    Extrai a cor dominante da capa do álbum (QImage) e gera um gradiente
    atmosférico adaptativo mantendo os tons escuros à esquerda e na base
    para contraste legível com os textos, barra de progresso e botões brancos.
    """
    if img is None or img.isNull():
        return get_default_palette()

    small = img.scaled(44, 44, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    small = small.convertToFormat(QImage.Format.Format_ARGB32)

    w, h = small.width(), small.height()
    num_bins = 18
    bin_weights = [0.0] * num_bins
    bin_cos = [0.0] * num_bins
    bin_sin = [0.0] * num_bins
    bin_sat = [0.0] * num_bins
    bin_val = [0.0] * num_bins

    total_sat = 0.0
    valid_pixels = 0

    for y in range(2, h - 2):
        for x in range(2, w - 2):
            c = small.pixelColor(x, y)
            if c.alpha() < 128:
                continue

            hue, sat, val, _ = c.getHsvF()
            valid_pixels += 1
            total_sat += sat

            # Ignora pretos absolutos ou brancos estourados sem saturação na escolha do matiz
            if val < 0.10 or (sat < 0.08 and val > 0.88):
                continue

            if hue < 0.0:
                continue

            # Dá peso maior às cores vibrantes e bem iluminadas que definem a identidade da capa
            weight = (sat ** 1.35) * (0.25 + 0.75 * val)
            if weight <= 0.001:
                continue

            b = int(hue * num_bins) % num_bins
            angle = hue * 2.0 * math.pi
            bin_weights[b] += weight
            bin_cos[b] += math.cos(angle) * weight
            bin_sin[b] += math.sin(angle) * weight
            bin_sat[b] += sat * weight
            bin_val[b] += val * weight

    avg_sat = (total_sat / valid_pixels) if valid_pixels > 0 else 0.0
    max_weight = max(bin_weights) if bin_weights else 0.0

    # Capa monocromática (Preto & Branco / Cinza)
    if max_weight < 0.35 or avg_sat < 0.075:
        return ThemePalette(
            stop0=QColor("#050608"),
            stop1=QColor("#141820"),
            stop2=QColor("#2c3444"),
            stop3=QColor("#3e485c"),
            glow=QColor(200, 215, 235, 70),
            bottom_shade=QColor(4, 5, 8, 120),
        )

    best_bin = bin_weights.index(max_weight)

    # Combina o bin vencedor com seus vizinhos imediatos para obter um matiz suave e fiel
    sum_w = 0.0
    sum_cos = 0.0
    sum_sin = 0.0
    sum_sat = 0.0
    sum_val = 0.0

    for offset in (-1, 0, 1):
        idx = (best_bin + offset) % num_bins
        factor = 1.0 if offset == 0 else 0.45
        w_b = bin_weights[idx] * factor
        sum_w += w_b
        sum_cos += bin_cos[idx] * factor
        sum_sin += bin_sin[idx] * factor
        sum_sat += bin_sat[idx] * factor
        sum_val += bin_val[idx] * factor

    mean_angle = math.atan2(sum_sin, sum_cos)
    if mean_angle < 0:
        mean_angle += 2.0 * math.pi
    dom_hue = (mean_angle / (2.0 * math.pi)) % 1.0
    dom_sat = (sum_sat / sum_w) if sum_w > 0 else 0.70
    dom_val = (sum_val / sum_w) if sum_w > 0 else 0.65

    # Ajusta saturação para um intervalo elegante e rico
    rich_sat = max(0.54, min(0.86, dom_sat * 1.12))

    # Matizes amarelos/verdes/cianos têm luminância perceptual muito alta; reduzimos o brilho máximo
    # para nunca ofuscar os textos brancos nem a barra de progresso
    high_lum_hue = 0.11 <= dom_hue <= 0.50
    lum_scale = 0.80 if high_lum_hue else 1.00

    v_base = max(0.50, min(0.74, dom_val * 0.95)) * lum_scale

    stop0 = QColor.fromHsvF(dom_hue, min(0.95, rich_sat * 1.08), 0.07)
    stop1 = QColor.fromHsvF(dom_hue, min(0.92, rich_sat * 1.02), 0.25 * lum_scale)
    stop2 = QColor.fromHsvF(dom_hue, rich_sat * 0.92, v_base * 0.84)

    accent_hue = (dom_hue + 0.02) % 1.0
    stop3 = QColor.fromHsvF(accent_hue, rich_sat * 0.85, min(0.76, v_base * 1.05))

    glow_hue = (dom_hue + 0.03) % 1.0
    glow = QColor.fromHsvF(glow_hue, max(0.35, rich_sat * 0.58), 0.96, 0.34)

    bottom_shade = QColor.fromHsvF(dom_hue, min(0.95, rich_sat), 0.04, 0.46)

    return ThemePalette(
        stop0=stop0,
        stop1=stop1,
        stop2=stop2,
        stop3=stop3,
        glow=glow,
        bottom_shade=bottom_shade,
    )


def render_adaptive_card_background(painter: QPainter, card_rect: QRectF, palette: ThemePalette):
    """
    Desenha o fundo adaptativo do card (960x540) reproduzindo a geometria de luz do widget-bg.svg,
    acrescentando uma vinheta escura sutil na parte inferior para garantir contraste total
    com a barra de progresso branca e os botões Pill.
    """
    w = card_rect.width()
    h = card_rect.height()

    # 1. Gradiente Linear Principal (esquerda escura -> direita luminosa atrás do vinil)
    linear = QLinearGradient(0.0, 0.0, w, 0.0)
    linear.setColorAt(0.00, palette.stop0)
    linear.setColorAt(0.38, palette.stop1)
    linear.setColorAt(0.78, palette.stop2)
    linear.setColorAt(1.00, palette.stop3)
    painter.fillRect(card_rect, linear)

    # 2. Glow Radial Superior Direito (cx=0.74, cy=0.20, r=0.60 como no widget-bg.svg)
    radial = QRadialGradient(QPointF(w * 0.74, h * 0.20), w * 0.55)
    radial.setColorAt(0.0, palette.glow)
    glow_transparent = QColor(palette.glow)
    glow_transparent.setAlpha(0)
    radial.setColorAt(1.0, glow_transparent)
    painter.fillRect(card_rect, radial)

    # 3. Vinheta Escura Inferior (garante contraste perfeito para os controles e barra branca na base)
    bottom_grad = QLinearGradient(0.0, h * 0.48, 0.0, h)
    top_clear = QColor(palette.bottom_shade)
    top_clear.setAlpha(0)
    bottom_grad.setColorAt(0.0, top_clear)
    bottom_grad.setColorAt(1.0, palette.bottom_shade)
    painter.fillRect(card_rect, bottom_grad)
