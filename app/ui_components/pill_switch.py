import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen


class PillSwitch:
    """
    Componente visual de Pill Switch (Chave Seletora em Pílula) no estilo Fluent:
    - Formato pílula ultra-compacto (24x13px) ideal para listas de itens e menus inline.
    - Animação suave e fluida do thumb e do preenchimento da pista independente de FPS (144 Hz).
    - Efeito tátil de pressão (o thumb alonga levemente ao clicar).
    - Cores Fluent: Inativo #444444 / Ativo #54aff4.
    """

    WIDTH = 28.0
    HEIGHT = 15.0
    THUMB_SIZE = 10.5

    def __init__(self, is_checked: bool = False):
        self.is_checked = is_checked
        self.is_hovered = False
        self.is_pressed = False
        # Cor da pista ligada (um tema pode trocá-la); o padrão é o azul Fluent original
        self.accent = QColor(84, 175, 244)

        self._x = 0.0
        self._y = 0.0

        # Animação do progresso (0.0 = desmarcado, 1.0 = marcado)
        self._progress = 1.0 if is_checked else 0.0
        self._target_progress = self._progress

        # Animação do alongamento tátil (press squish)
        self._press_anim = 0.0
        self._target_press = 0.0

    def set_geometry(self, x: float, y: float):
        self._x = float(x)
        self._y = float(y)

    def set_checked(self, checked: bool, animated: bool = True):
        self.is_checked = checked
        self._target_progress = 1.0 if checked else 0.0
        if not animated:
            self._progress = self._target_progress

    def toggle(self):
        self.set_checked(not self.is_checked)

    def hit_rect(self) -> QRectF:
        # Área de clique ampliada para facilitar a interação com mouse
        return QRectF(self._x - 4.0, self._y - 4.0, self.WIDTH + 8.0, self.HEIGHT + 8.0)

    def contains(self, pt: QPointF) -> bool:
        return self.hit_rect().contains(pt)

    def step_animation(self, dt: float) -> bool:
        """Avança as transições suaves de deslizamento e cor. Retorna True se ainda estiver animando."""
        animating = False

        # 1. Transição de posição e cor (deslizamento do thumb)
        diff = self._target_progress - self._progress
        if abs(diff) > 0.003:
            alpha = 1.0 - math.exp(-32.0 * dt)
            self._progress += diff * alpha
            animating = True
        else:
            self._progress = self._target_progress

        # 2. Transição tátil de pressão (squish)
        press_diff = self._target_press - self._press_anim
        if abs(press_diff) > 0.005:
            alpha_press = 1.0 - math.exp(-38.0 * dt)
            self._press_anim += press_diff * alpha_press
            animating = True
        else:
            self._press_anim = self._target_press

        return animating

    def draw(self, p: QPainter):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        t = max(0.0, min(1.0, self._progress))

        # 1. Interpolação de cor da pista:
        # Inativo: #2d2d2d com borda sutil #555555 -> Ativo: #54aff4 (Fluent Accent)
        acc = self.accent
        r = int(round(45 + (acc.red() - 45) * t))
        g = int(round(45 + (acc.green() - 45) * t))
        b = int(round(45 + (acc.blue() - 45) * t))

        if self.is_hovered:
            r = min(255, r + 14)
            g = min(255, g + 14)
            b = min(255, b + 14)

        track_rect = QRectF(self._x, self._y, self.WIDTH, self.HEIGHT)
        radius = self.HEIGHT * 0.5

        # Borda sutil quando inativo para dar definição
        border_alpha = int(round(180 * (1.0 - t)))
        if border_alpha > 5:
            p.setPen(QPen(QColor(85, 85, 85, border_alpha), 1.0))
        else:
            p.setPen(Qt.PenStyle.NoPen)

        p.setBrush(QColor(r, g, b))
        p.drawRoundedRect(track_rect, radius, radius)

        # 2. Posição e dimensões do thumb animado
        pad_x = 2.2
        pad_y = (self.HEIGHT - self.THUMB_SIZE) * 0.5
        travel_x = self.WIDTH - self.THUMB_SIZE - pad_x * 2.0

        thumb_x0 = self._x + pad_x + travel_x * t
        thumb_y0 = self._y + pad_y

        # Alongamento tátil ao clicar (squish horizontal)
        squish_w = self._press_anim * 2.5
        thumb_w = self.THUMB_SIZE + squish_w
        thumb_h = self.THUMB_SIZE

        if t < 0.5:
            thumb_draw_x = thumb_x0
        else:
            thumb_draw_x = thumb_x0 - squish_w

        thumb_rect = QRectF(thumb_draw_x, thumb_y0, thumb_w, thumb_h)
        thumb_radius = self.THUMB_SIZE * 0.5

        # Micro-sombra suave abaixo do thumb para dar relevo físico tátil
        p.setPen(Qt.PenStyle.NoPen)
        sh_alpha = int(round(45 + 25 * t))
        p.setBrush(QColor(0, 0, 0, sh_alpha))
        p.drawRoundedRect(thumb_rect.adjusted(-0.3, 0.5, 0.3, 1.0), thumb_radius, thumb_radius)

        # Cor do thumb:
        # Inativo: #cecece (ou #e5e5e5 em hover)
        # Ativo: #ffffff (Branco puro vibrante)
        inact_lum = 225 if self.is_hovered else 198
        thumb_lum = int(round(inact_lum + (255 - inact_lum) * t))
        p.setBrush(QColor(thumb_lum, thumb_lum, thumb_lum))
        p.drawRoundedRect(thumb_rect, thumb_radius, thumb_radius)

        p.restore()
