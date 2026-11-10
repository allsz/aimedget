"""
Definições de temas, tokens e folha de estilo (QSS) para o Aimedget Hub.
Diretrizes Impeccable (Operate/Tool mode):
- Tipografia unificada estilo Notion (Inter / Segoe UI Variable).
- Escala tipográfica rigorosa (11px, 12px, 13.5px, 15px, 20px, 24px).
- Pesos contidos: Regular (400) e SemiBold (600). Eliminado negrito agressivo (800/Black).
- Paleta neutra e equilibrada inspirada em Notion e Linear.
- Suporte refinado aos modos: Sistema, Claro, Escuro e True Dark (OLED).
- 'system' resolve apenas para Claro ou Escuro; True Dark é sempre escolha manual.
"""

from dataclasses import dataclass
import winreg


@dataclass(frozen=True)
class HubTheme:
    mode: str        # 'light', 'dark' ou 'true_dark'
    is_dark: bool
    bg: str          # Fundo geral da aplicação
    sidebar_bg: str  # Fundo da barra lateral
    panel: str       # Superfície de cards principais
    panel2: str      # Superfície de botões secundários e chips inativos
    line: str        # Bordas e separadores sutis
    text: str        # Texto principal (títulos e rótulos fortes)
    body: str        # Texto de leitura
    mute: str        # Texto secundário e legendas
    accent: str      # Cor de destaque principal (Âmbar/Laranja acolhedor)
    accent_hover: str
    ink: str         # Texto de contraste sobre o acento
    stage_bg: str    # Palco das miniaturas de preview
    menu_bg: str     # Fundo de menus de contexto (QMenu)
    hover: str       # Realce de itens em menus e listas


# Paleta Notion / Linear - Modo Claro
THEME_LIGHT = HubTheme(
    mode="light",
    is_dark=False,
    bg="#F7F6F3",         # Fundo clássico acolhedor estilo Notion
    sidebar_bg="#F1F0ED", # Sidebar ligeiramente contrastada
    panel="#FFFFFF",      # Cards brancos limpos
    panel2="#EAE8E3",     # Controles inativos e chips
    line="#E4E2DC",       # Linhas divisórias orgânicas sutis
    text="#1F1E1D",       # Preto suave / carvão
    body="#37352F",       # Notion primary text (#37352F)
    mute="#787774",       # Notion secondary mute (#787774)
    accent="#E58A18",     # Âmbar elegante e legível
    accent_hover="#D47B0E",
    ink="#FFFFFF",
    stage_bg="#EDEDEA",
    menu_bg="#FFFFFF",
    hover="#F1F0ED",
)

# Paleta Notion / Linear - Modo Escuro
THEME_DARK = HubTheme(
    mode="dark",
    is_dark=True,
    bg="#191919",         # Notion Dark background
    sidebar_bg="#141414", # Sidebar mais profunda
    panel="#202020",      # Superfície de cards com elevação sutil
    panel2="#2A2A2A",     # Controles secundários
    line="#303030",       # Bordas finas e discretas
    text="#FFFFFF",       # Títulos brancos limpos
    body="#D4D4D4",       # Corpo claro confortável aos olhos
    mute="#8A8A8A",       # Textos secundários legíveis
    accent="#FFA336",     # Âmbar suave e luminoso
    accent_hover="#FF9419",
    ink="#1A1305",
    stage_bg="#1E1E1E",
    menu_bg="#202020",
    hover="#2A2A2A",
)

# True Dark (OLED) - preto absoluto, profundidade por bordas finas em vez de cinza chapado
THEME_TRUE_DARK = HubTheme(
    mode="true_dark",
    is_dark=True,
    bg="#000000",         # Preto absoluto
    sidebar_bg="#000000", # Sidebar separada apenas pela borda
    panel="#0A0A0A",      # Cards quase pretos, elevação mínima
    panel2="#141414",     # Controles secundários, chips e item ativo
    line="#232323",       # Bordas e divisores ultra-sutis
    text="#FFFFFF",
    body="#D4D4D4",
    mute="#8A8A8A",       # ~6:1 sobre #000000
    accent="#FFA336",
    accent_hover="#FF9419",
    ink="#1A1305",
    stage_bg="#050505",
    menu_bg="#000000",    # Menu herda o preto puro
    hover="#161616",
)

THEME_MODES = ("system", "light", "dark", "true_dark")


def get_windows_system_theme() -> str:
    """Detecta se o Windows está configurado em tema 'light' ou 'dark'."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if val == 1 else "dark"
    except Exception:
        return "dark"


def resolve_theme(preference: str) -> HubTheme:
    """
    Resolve a preferência ('system', 'light', 'dark', 'true_dark') para o tema ativo.
    'system' segue o Windows e mapeia somente para Claro ou Escuro (cinza Fluent clássico);
    True Dark nunca é inferido, apenas escolhido explicitamente.
    """
    if preference == "system":
        sys_mode = get_windows_system_theme()
        return THEME_DARK if sys_mode == "dark" else THEME_LIGHT
    if preference == "true_dark":
        return THEME_TRUE_DARK
    if preference == "dark":
        return THEME_DARK
    return THEME_LIGHT


def get_hub_stylesheet(t: HubTheme) -> str:
    """
    Gera a folha de estilo (QSS) com rigor tipográfico e espacial:
    - Tipografia única: Inter, Segoe UI Variable, sans-serif.
    - Hierarquia limpa sem ruído visual.
    """
    return f"""
    * {{
        font-family: 'Inter', 'Segoe UI Variable', -apple-system, sans-serif;
    }}

    QMainWindow, QWidget#HubShell {{
        background-color: {t.bg};
        color: {t.body};
    }}

    /* Barra lateral estilo Notion/Linear */
    QWidget#HubSidebar {{
        background-color: {t.sidebar_bg};
        border-right: 1px solid {t.line};
    }}

    QLabel#HubBrand {{
        color: {t.text};
        font-size: 16px;
        font-weight: 600;
        letter-spacing: -0.2px;
        padding: 6px 12px 14px 12px;
    }}

    /* Botões da barra lateral */
    QPushButton.NavButton {{
        background-color: transparent;
        color: {t.mute};
        font-size: 13.5px;
        font-weight: 500;
        text-align: left;
        padding: 7px 12px;
        border: none;
        border-radius: 6px;
    }}

    QPushButton.NavButton:hover {{
        background-color: {t.panel2};
        color: {t.text};
    }}

    QPushButton.NavButton[active="true"] {{
        background-color: {t.panel2};
        color: {t.text};
        font-weight: 600;
    }}

    /* Áreas de Rolagem e Conteúdo Principal */
    QScrollArea {{
        background-color: {t.bg};
        border: none;
    }}

    QScrollArea > QWidget > QWidget {{
        background-color: {t.bg};
        color: {t.body};
    }}

    /* Títulos e Subtítulos - Proporções Notion */
    QLabel.SectionTitle {{
        color: {t.text};
        font-size: 24px;
        font-weight: 600;
        letter-spacing: -0.4px;
        margin: 0px 0px 2px 0px;
    }}

    QLabel.SectionSubtitle {{
        color: {t.mute};
        font-size: 13.5px;
        font-weight: 400;
        line-height: 1.45;
        margin: 0px 0px 12px 0px;
    }}

    /* Cards */
    QFrame.HubCard {{
        background-color: {t.panel};
        border: 1px solid {t.line};
        border-radius: 12px;
        color: {t.body};
    }}

    QFrame.HubCard QLabel {{
        color: {t.body};
    }}

    /* Divisores internos dos cards */
    QFrame.HubDivider {{
        background-color: {t.line};
        border: none;
        min-height: 1px;
        max-height: 1px;
    }}

    /* Palco decorativo da miniatura */
    QFrame.StageCard {{
        background-color: {t.stage_bg};
        border: 1px solid {t.line};
        border-radius: 8px;
    }}

    /* Chips e Botões de Filtro */
    QPushButton.Chip {{
        background-color: {t.panel};
        color: {t.body};
        border: 1px solid {t.line};
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 13px;
        font-weight: 500;
    }}

    QPushButton.Chip:hover {{
        background-color: {t.panel2};
        color: {t.text};
    }}

    QPushButton.Chip[selected="true"] {{
        background-color: {t.text};
        color: {t.bg};
        border-color: {t.text};
        font-weight: 600;
    }}

    /* Campo de busca */
    QLineEdit#SearchInput {{
        background-color: {t.panel};
        color: {t.text};
        border: 1px solid {t.line};
        border-radius: 8px;
        padding: 7px 12px;
        font-size: 13.5px;
        selection-background-color: {t.accent};
    }}

    QLineEdit#SearchInput:focus {{
        border: 1px solid {t.accent};
    }}

    /* Scrollbars elegantes e discretas */
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.line};
        min-height: 20px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.mute};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    """
