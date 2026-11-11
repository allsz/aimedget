import math
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor


class SoundWaveVisualizer:
    """
    Renderizador procedual da onda sonora (7 barras arredondadas) com animação fluida a 60 FPS:
    - Baseado fielmente na geometria do ícone enviado pelo usuário.
    - Quando tocando (is_playing=True): as 7 barras ondulam organicamente simulando equalizador.
    - Quando pausado (is_playing=False): as barras descansam suavemente na forma original exata.
    """
    # Proporções de altura originais extraídas da imagem (7 barras simétricas)
    REST_RATIOS = [0.15, 0.49, 1.00, 0.66, 0.32, 0.66, 0.15]

    def __init__(self):
        self._current_heights = list(self.REST_RATIOS)
        self._phase = 0.0

    def update(self, dt: float, is_playing: bool):
        """Atualiza a física dos keyframes de altura para cada barra."""
        self._phase += dt * 4.2
        speed = min(1.0, dt * 9.0)

        for i in range(7):
            if is_playing:
                # Frequências e fases desfasadas para gerar movimento rítmico orgânico
                w1 = math.sin(self._phase * 1.5 + i * 1.15)
                w2 = math.cos(self._phase * 2.3 - i * 0.95)
                w3 = math.sin(self._phase * 0.8 + i * 2.2)
                
                # Modulação com ênfase nas barras centrais
                weight = 0.65 + 0.35 * self.REST_RATIOS[i]
                target = (0.20 + 0.45 * (0.5 + 0.5 * w1) + 0.25 * (0.5 + 0.5 * w2) + 0.10 * (0.5 + 0.5 * w3)) * weight
                target = max(0.12, min(1.0, target))
            else:
                target = self.REST_RATIOS[i]

            # Interpolação suave para evitar saltos ou trancos
            self._current_heights[i] += (target - self._current_heights[i]) * speed

    def render(self, painter: QPainter, rect: QRectF, color: QColor | None = None):
        """
        Desenha as 7 barras arredondadas preenchendo o QRectF fornecido.
        Todas as barras ficam perfeitamente centralizadas no eixo vertical.
        """
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if color is None:
            color = QColor(255, 255, 255, 220)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)

        w = rect.width()
        h = rect.height()
        cy = rect.center().y()

        # Proporções idênticas à imagem original (23px largura / 16px espaçamento em base 257px)
        bar_w = max(2.0, w * (23.0 / 257.0))
        spacing = max(1.2, w * (16.0 / 257.0))
        total_w = 7 * bar_w + 6 * spacing
        start_x = rect.center().x() - total_w / 2.0

        radius = bar_w / 2.0

        for i in range(7):
            bx = start_x + i * (bar_w + spacing)
            bh = max(bar_w, h * self._current_heights[i])
            by = cy - bh / 2.0
            painter.drawRoundedRect(QRectF(bx, by, bar_w, bh), radius, radius)

        painter.restore()

