"""Paleta da skin Capa Empilhada (separada da skin para o tema poder usá-la sem importar a skin inteira)."""

from dataclasses import dataclass

from PySide6.QtGui import QColor


@dataclass
class PastelStackTheme:
    """Paleta pastel adaptativa inspirada na referência capaEmpilhada.png."""
    card_bg: QColor          # Fundo pastel suave do card (#FDE9E5 na referência)
    title_color: QColor      # Título escuro profundo (#140908)
    subtitle_color: QColor   # Subtítulo "Artista | Álbum" em tom acento suave (#C66363)
    btn_grad_tl: QColor      # Topo-esquerdo do botão squircle neumórfico (#F8D2C6)
    btn_grad_br: QColor      # Base-direita do botão squircle neumórfico (#FFF3EF)
    btn_shadow: QColor       # Sombra suave sob o botão squircle
    accent_main: QColor      # Ícone Play/Pause vibrante (#EB5757)
    accent_muted: QColor     # Ícones Repeat e Shuffle em repouso (#E58885)


def get_default_pastel_theme() -> PastelStackTheme:
    """Retorna a paleta coral/creme idêntica à referência capaEmpilhada.png."""
    return PastelStackTheme(
        card_bg=QColor("#FDE9E5"),
        title_color=QColor("#140908"),
        subtitle_color=QColor("#C86464"),
        btn_grad_tl=QColor("#F8D1C5"),
        btn_grad_br=QColor("#FFF4F0"),
        btn_shadow=QColor(218, 145, 132, 52),
        accent_main=QColor("#EB5757"),
        accent_muted=QColor("#E48885"),
    )
