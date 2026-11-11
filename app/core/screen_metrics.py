"""
ScreenMetrics - Módulo de detecção de resolução, densidade de tela e escala proporcional.
Calcula e gerencia os fatores de escala ideais para os widgets flutuantes da suíte Aimedget,
garantindo que em qualquer tela (720p, 1080p, 1440p, 4K, ultrawide ou portrait) o tamanho inicial
seja proporcional e sem distorções ou "jumpscare".
"""

from typing import Optional, Tuple
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QApplication, QWidget

# Baseline canônico de design da suíte Aimedget:
# Resolução de referência onde os widgets foram concebidos e calibrados (1440p @ 100% DPI).
BASELINE_WIDTH: float = 2560.0
BASELINE_HEIGHT: float = 1440.0

# Escalas e tamanhos de referência canônicos (escala 1.0x da tela)
BASELINE_MUSIC_SCALE: float = 0.50  # Canvas 960x540 -> 480x270 px / Canvas 980x480 -> 490x240 px
BASELINE_TIMER_SIZE: Tuple[int, int] = (164, 164)

# Limites de salvaguarda para o cálculo automático
MIN_AUTO_RATIO: float = 0.50   # Mínimo para telas 720p / 1366x768
MAX_AUTO_RATIO: float = 1.75   # Máximo para painéis 4K / UHD

# Presets de escala customizada disponíveis para o usuário
MUSIC_SCALE_PRESETS = [
    (0.375, "75% (Compacto)"),
    (0.50, "100% (Padrão 1440p)"),
    (0.625, "125% (Grande)"),
    (0.75, "150% (Extra Grande)"),
]


def get_screen_for_widget(widget: Optional[QWidget] = None) -> Optional[QScreen]:
    """
    Retorna a tela (QScreen) onde o widget está posicionado atualmente,
    ou a tela primária caso o widget não esteja associado a nenhuma tela específica.
    """
    app = QApplication.instance()
    if not app:
        return None

    if widget is not None:
        # Se a janela nativa já tiver uma tela associada
        handle = widget.windowHandle()
        if handle and handle.screen():
            return handle.screen()

        # Caso contrário, verifica qual tela engloba o centro do widget
        center = widget.geometry().center()
        screen = app.screenAt(center)
        if screen:
            return screen

    return app.primaryScreen()


def get_screen_scale_ratio(screen: Optional[QScreen] = None, widget: Optional[QWidget] = None) -> float:
    """
    Calcula a razão de escala proporcional da tela em relação ao baseline de 1440p.
    Usa min(width, height) para funcionar perfeitamente em telas horizontais (16:9, ultrawide)
    e telas verticais/portrait (1080x1920).
    
    Retorna um float arredondado a passos de 0.05, limitado entre MIN_AUTO_RATIO e MAX_AUTO_RATIO.
    Exemplos:
    - 720p (1280x720)   -> 0.50
    - 768p (1366x768)   -> 0.55
    - 1080p (1920x1080) -> 0.75
    - 1440p (2560x1440) -> 1.00
    - 4K (3840x2160)    -> 1.50
    """
    target_screen = screen or get_screen_for_widget(widget)
    if not target_screen:
        return 1.0

    geom = target_screen.geometry()
    w, h = geom.width(), geom.height()
    if w <= 0 or h <= 0:
        return 1.0

    # A menor dimensão física/lógica define a densidade real da tela (imune a rotação de monitor)
    effective_dim = min(w, h)
    raw_ratio = effective_dim / BASELINE_HEIGHT

    # Snapping a cada 5% (0.05) para escalas limpas e previsíveis
    snapped = round(raw_ratio * 20.0) / 20.0
    return max(MIN_AUTO_RATIO, min(MAX_AUTO_RATIO, snapped))


def get_auto_music_scale(screen: Optional[QScreen] = None, widget: Optional[QWidget] = None) -> float:
    """
    Calcula a escala inicial ideal do Music Widget para a resolução da tela.
    Exemplos de tamanho resultante (Canvas 960x540):
    - 720p:  escala 0.250 -> 240 x 135 px
    - 1080p: escala 0.375 -> 360 x 202 px
    - 1440p: escala 0.500 -> 480 x 270 px (Tamanho canônico atual)
    - 4K:    escala 0.750 -> 720 x 405 px
    """
    ratio = get_screen_scale_ratio(screen=screen, widget=widget)
    return round(BASELINE_MUSIC_SCALE * ratio, 4)


def get_auto_timer_size(screen: Optional[QScreen] = None, widget: Optional[QWidget] = None) -> Tuple[int, int]:
    """
    Calcula o tamanho inicial proporcional do Timer Widget para a resolução da tela.
    Mantém proporção 1:1 e garante legibilidade mínima (120x120px).
    """
    ratio = get_screen_scale_ratio(screen=screen, widget=widget)
    base_w, base_h = BASELINE_TIMER_SIZE
    w = max(120, int(round(base_w * ratio)))
    h = max(120, int(round(base_h * ratio)))
    return (w, h)


def format_scale_percent(scale: float) -> str:
    """Formata um float de escala em percentual humano em relação ao baseline de 1440p (ex: 0.50 -> 100%)."""
    pct = int(round((scale / BASELINE_MUSIC_SCALE) * 100))
    return f"{pct}%"
