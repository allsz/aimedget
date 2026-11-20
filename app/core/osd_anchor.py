"""
Âncora compartilhada dos flyouts de sistema (Caps/Num Lock e Mixer de Volume).

Cada flyout escolhe a sua posição no Hub, entre 8 âncoras (grade 3x3 sem o centro):

    tl  tc  tr
    ml      mr
    bl  bc  br

Regra de empilhamento (quando os dois estão na MESMA âncora e aparecem juntos):
- Embaixo (bl/bc/br): o mixer fica colado na borda e o Caps Lock empilha ACIMA dele (comportamento original).
- Em cima (tl/tc/tr): espelho — o mixer fica colado no topo e o Caps Lock desce para BAIXO dele.
- No meio (ml/mr): o par fica centralizado no eixo Y. O Caps Lock fica acima e o mixer abaixo; ao aparecer o
  segundo, os dois se afastam do centro em direções opostas.

Nada gira: o que muda é qual borda do card fica parada (e para onde ele cresce/desliza).
"""

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication

ANCHORS: tuple[str, ...] = ("tl", "tc", "tr", "ml", "mr", "bl", "bc", "br")
DEFAULT_ANCHOR = "bc"   # centro inferior, logo acima da barra de tarefas (o padrão de sempre)

SIDE_GAP_PX = 24        # distância do card às laterais da tela nas âncoras de canto/lateral (= widgets do Hub)
STACK_GAP_PX = 10.0     # espaço entre o Caps Lock e o mixer quando empilhados

# Constantes compartilhadas de posicionamento externo (barra de volume da música, HUD de alinhamento, etc.)
EDGE_GAP = 12           # distância entre o widget e o overlay externo
SIDE_HYSTERESIS = 48    # folga extra exigida para VOLTAR ao lado direito (evita vai-e-volta na parede)
SCREEN_MARGIN = 8       # folga mínima até a borda da tela

_VERTICAL = {"t": "top", "m": "middle", "b": "bottom"}
_HORIZONTAL = {"l": "left", "c": "center", "r": "right"}


def normalize(anchor: object) -> str:
    """Âncora válida; qualquer valor estranho (config editada à mão, versão antiga) volta ao padrão."""
    return anchor if isinstance(anchor, str) and anchor in ANCHORS else DEFAULT_ANCHOR


def vertical(anchor: str) -> str:
    """'top', 'middle' ou 'bottom'."""
    return _VERTICAL[normalize(anchor)[0]]


def horizontal(anchor: str) -> str:
    """'left', 'center' ou 'right'."""
    return _HORIZONTAL[normalize(anchor)[1]]


def card_left_x(anchor: str, avail: QRect, card_w: float, art_left: float = 0.0, art_right: float = 0.0) -> float:
    """
    X (tela) da borda esquerda do CARD para a âncora. A arte que passa da borda lateral (figurinhas) empurra o
    card para dentro, para não sair da tela.
    """
    side = horizontal(anchor)
    if side == "left":
        return float(avail.x() + SIDE_GAP_PX) + art_left
    if side == "right":
        return float(avail.x() + avail.width() - SIDE_GAP_PX) - art_right - card_w
    return float(avail.x() + (avail.width() - card_w) // 2)


def primary_available_geometry() -> QRect | None:
    """Área útil (sem a barra de tarefas) do monitor primário, onde os flyouts de sistema aparecem."""
    app = QApplication.instance()
    if app and app.primaryScreen():
        return app.primaryScreen().availableGeometry()
    return None


def compute_osd_placement(
    anchor: QRect,
    osd_size: QSize,
    screen: QRect,
    gap: int = EDGE_GAP,
    margin: int = SCREEN_MARGIN,
    previous_side: str | None = None,
    hysteresis: int = SIDE_HYSTERESIS,
) -> tuple[QPoint, str]:
    """
    Posição do canto superior esquerdo de um overlay externo (barra de volume, HUD de alinhamento, etc.)
    e o lado escolhido ("right", "left", "above", "below" ou "over"), sempre fora do widget e dentro da tela.

    1. Preferência: lateral externa direita, centrada verticalmente no widget.
    2. Sem espaço à direita: lateral esquerda.
    3. Nenhuma lateral cabe: acima ou abaixo.
    4. Último recurso: sobre a borda direita do widget, ainda preso na área útil da tela.
    """
    w, h = osd_size.width(), osd_size.height()
    left_limit = screen.left() + margin
    right_limit = screen.right() + 1 - margin
    top_limit = screen.top() + margin
    bottom_limit = screen.bottom() + 1 - margin

    def clamp(v: int, lo: int, hi: int) -> int:
        return max(lo, min(v, hi)) if hi >= lo else lo

    mid_y = clamp(anchor.center().y() - h // 2, top_limit, bottom_limit - h)

    x_right = anchor.right() + 1 + gap
    x_left = anchor.left() - gap - w
    right_fits = x_right + w <= right_limit
    right_fits_clear = x_right + w <= right_limit - hysteresis
    left_fits = x_left >= left_limit

    if previous_side == "left":
        if right_fits_clear:
            return QPoint(x_right, mid_y), "right"
        if left_fits:
            return QPoint(x_left, mid_y), "left"
        if right_fits:
            return QPoint(x_right, mid_y), "right"
    else:
        if right_fits:
            return QPoint(x_right, mid_y), "right"
        if left_fits:
            return QPoint(x_left, mid_y), "left"

    mid_x = clamp(anchor.center().x() - w // 2, left_limit, right_limit - w)
    y_above = anchor.top() - gap - h
    if y_above >= top_limit:
        return QPoint(mid_x, y_above), "above"
    y_below = anchor.bottom() + 1 + gap
    if y_below + h <= bottom_limit:
        return QPoint(mid_x, y_below), "below"

    return QPoint(clamp(anchor.right() + 1 - w - gap, left_limit, right_limit - w), mid_y), "over"


def compute_osd_position(
    anchor: QRect,
    osd_size: QSize,
    screen: QRect,
    gap: int = EDGE_GAP,
    margin: int = SCREEN_MARGIN,
) -> QPoint:
    """Atalho: só a posição (sem histerese). Ver `compute_osd_placement`."""
    return compute_osd_placement(anchor, osd_size, screen, gap, margin)[0]


class OsdStack:
    """
    Cada flyout tem a SUA âncora (o Caps Lock pode ficar no topo direito e o mixer embaixo à esquerda). Só quando
    os dois escolhem a mesma posição eles se empilham; em âncoras diferentes um ignora o outro.

    - o mixer publica os limites visuais do card (o Caps Lock empilha acima/abaixo deles);
    - o Caps Lock publica sua presença e altura (no meio da tela o mixer abre espaço para o par ficar centralizado);
    - nas colunas laterais o Caps Lock se alinha pelo CENTRO da coluna do mixer (fica mais longe da borda, alinhado).
    """

    def __init__(self, keylock_flyout, volume_flyout):
        self.caps = keylock_flyout
        self.mixer = volume_flyout
        volume_flyout.card_bounds_changed.connect(self._on_mixer_bounds)
        keylock_flyout.stack_presence_changed.connect(self._on_caps_presence)
        keylock_flyout.set_column_provider(self._shared_column_center)

    def same_anchor(self) -> bool:
        return self.caps.anchor() == self.mixer.anchor()

    def _shared_column_center(self) -> float | None:
        """Centro X da coluna do mixer quando os dois dividem uma âncora lateral; None = o Caps Lock se posiciona só."""
        if not self.same_anchor() or horizontal(self.caps.anchor()) == "center":
            return None
        return self.mixer.column_center_x()

    def _on_mixer_bounds(self, top: float, bottom: float, active: bool):
        self.caps.on_mixer_bounds_changed(top, bottom, active and self.same_anchor())

    def _on_caps_presence(self, visual_h: float, active: bool):
        self.mixer.on_caps_presence_changed(visual_h, active and self.same_anchor())

    def set_anchors(self, keylock_anchor: str, mixer_anchor: str):
        """Aplica as duas âncoras e refaz o empilhamento na hora (os dois podem estar na tela)."""
        self.mixer.set_anchor(mixer_anchor)
        self.caps.set_anchor(keylock_anchor, force=True)   # a coluna pode ter mudado mesmo com a mesma âncora
        caps_on_screen = self.caps.isVisible() and self.caps.is_presenting()
        self._on_caps_presence(self.caps.visual_height() if caps_on_screen else 0.0, caps_on_screen)
        bounds = self.mixer.get_card_screen_bounds()
        self._on_mixer_bounds(*(bounds or (0.0, 0.0)), bounds is not None)


def link_flyouts(keylock_flyout, volume_flyout) -> OsdStack:
    """Liga o empilhamento cooperativo e aplica as âncoras salvas de cada flyout."""
    from app.core.config_manager import config_manager
    from app.widgets.volume_mixer.theme import load_user_theme

    # O tema do mixer só seria lido na 1ª exibição; as figurinhas laterais dele definem a coluna do Caps Lock
    volume_flyout._apply_theme(load_user_theme())
    stack = OsdStack(keylock_flyout, volume_flyout)
    stack.set_anchors(config_manager.get_osd_anchor("keylock"), config_manager.get_osd_anchor("mixer"))
    return stack
