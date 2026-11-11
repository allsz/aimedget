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

from dataclasses import dataclass, replace
import colorsys
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


# --- Cor de destaque personalizável ---------------------------------------------------------------
# O padrão (accent_hue=None) é a identidade âmbar do app, com os valores exatos das paletas acima.
# Com um matiz escolhido, o destaque é derivado com a mesma saturação e brilho do âmbar de cada modo.

DEFAULT_ACCENT_HUE = 33    # matiz do âmbar da identidade (só referência visual do seletor)
_LIGHT_INK = "#FFFFFF"
_UNSET = object()


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def _luminance(hex_color: str) -> float:
    c = hex_color.lstrip("#")
    chans = []
    for i in (0, 2, 4):
        v = int(c[i:i + 2], 16) / 255
        chans.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def derive_accent(hue: int, is_dark: bool) -> tuple[str, str, str]:
    """(accent, accent_hover, ink) para um matiz 0-359. Mantém S/V do âmbar do modo; no claro escurece até o
    destaque ter >= 3:1 sobre o painel branco (matizes claros como amarelo e ciano ficariam ilegíveis)."""
    h = (int(hue) % 360) / 360.0
    dark_ink = _hex(*colorsys.hsv_to_rgb(h, 0.85, 0.10))

    def best_ink(accent: str) -> str:
        return _LIGHT_INK if contrast_ratio(accent, _LIGHT_INK) >= contrast_ratio(accent, dark_ink) else dark_ink

    if is_dark:
        sat = 0.79
        while True:   # clareia (menos saturação) só o necessário para o texto sobre o destaque ter >= 4,5:1
            accent = _hex(*colorsys.hsv_to_rgb(h, sat, 1.0))
            if contrast_ratio(accent, best_ink(accent)) >= 4.5 or sat <= 0.5:
                break
            sat -= 0.02
        hover = _hex(*colorsys.hsv_to_rgb(h, min(1.0, sat + 0.11), 0.97))
    else:
        v = 0.90
        while v > 0.30:
            accent = _hex(*colorsys.hsv_to_rgb(h, 0.90, v))
            ink = best_ink(accent)
            if contrast_ratio(accent, "#FFFFFF") >= 3.0 and contrast_ratio(accent, ink) >= 4.5:
                break
            v -= 0.02
        hover = _hex(*colorsys.hsv_to_rgb(h, 0.93, max(0.0, v - 0.07)))
    return accent, hover, best_ink(accent)


def parse_color(text: str) -> str | None:
    """Lê uma cor digitada pelo usuário e devolve '#RRGGBB' (ou None se não for uma cor válida).
    Aceita #RGB, #RRGGBB, #RRGGBBAA (com ou sem #), rgb(r, g, b) e rgba(r, g, b, a). A transparência é ignorada."""
    import re
    raw = (text or "").strip()
    m = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*(?:[,/]\s*[\d.]+%?\s*)?\)",
                     raw, re.IGNORECASE)
    if m:
        r, g, b = (int(v) for v in m.groups())
        return "#{:02X}{:02X}{:02X}".format(r, g, b) if max(r, g, b) <= 255 else None
    h = raw.lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", h):
        h = "".join(ch * 2 for ch in h)
    elif re.fullmatch(r"[0-9a-fA-F]{8}", h):
        h = h[:6]
    if re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return "#" + h.upper()
    return None


def _rgb(hex_color: str) -> tuple[float, float, float]:
    c = hex_color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def hue_of(hex_color: str) -> int:
    """Matiz (0-359) de uma cor, para posicionar o seletor."""
    return int(round(colorsys.rgb_to_hsv(*_rgb(hex_color))[0] * 359)) % 360


def fit_accent(color: str, is_dark: bool) -> tuple[str, str, str]:
    """(accent, accent_hover, ink) para uma cor escolhida pelo usuário. A cor é usada como veio; só é ajustada,
    o mínimo possível, quando ficaria ilegível no modo atual: >= 3:1 sobre o painel e texto sobre ela >= 4,5:1.
    No escuro clareia (brilho e depois menos saturação); no claro escurece."""
    h, sat, val = colorsys.rgb_to_hsv(*_rgb(color))
    panel = "#202020" if is_dark else "#FFFFFF"

    def make(s_: float, v_: float) -> str:
        return _hex(*colorsys.hsv_to_rgb(h, s_, v_))

    def ink_for(accent: str) -> str:
        dark_ink = _hex(*colorsys.hsv_to_rgb(h, 0.85, 0.10))
        return _LIGHT_INK if contrast_ratio(accent, _LIGHT_INK) >= contrast_ratio(accent, dark_ink) else dark_ink

    def ok(accent: str) -> bool:
        return contrast_ratio(accent, panel) >= 3.0 and contrast_ratio(accent, ink_for(accent)) >= 4.5

    accent = make(sat, val)
    if is_dark:
        while not ok(accent) and val < 1.0:
            val = min(1.0, val + 0.02)
            accent = make(sat, val)
        while not ok(accent) and sat > 0.0:
            sat = max(0.0, sat - 0.02)
            accent = make(sat, val)
        hover = make(min(1.0, sat + 0.08), max(0.0, val - 0.04))
    else:
        while not ok(accent) and val > 0.0:
            val = max(0.0, val - 0.02)
            accent = make(sat, val)
        hover = make(min(1.0, sat + 0.03), max(0.0, val - 0.07))
    return accent, hover, ink_for(accent)


def with_accent(theme: HubTheme, accent) -> HubTheme:
    """Aplica a cor de destaque: None = identidade âmbar (o tema como está), int = matiz 0-359, str = '#RRGGBB'."""
    if accent is None:
        return theme
    if isinstance(accent, str):
        color, hover, ink = fit_accent(accent, theme.is_dark)
    else:
        color, hover, ink = derive_accent(accent, theme.is_dark)
    return replace(theme, accent=color, accent_hover=hover, ink=ink)


def resolve_theme(preference: str, accent=_UNSET) -> HubTheme:
    """
    Resolve a preferência ('system', 'light', 'dark', 'true_dark') para o tema ativo, já com a cor de destaque
    salva (ou `accent` explícito: matiz, '#RRGGBB' ou None = âmbar padrão).
    'system' segue o Windows e mapeia somente para Claro ou Escuro (cinza Fluent clássico);
    True Dark nunca é inferido, apenas escolhido explicitamente.
    """
    if preference == "system":
        sys_mode = get_windows_system_theme()
        base = THEME_DARK if sys_mode == "dark" else THEME_LIGHT
    elif preference == "true_dark":
        base = THEME_TRUE_DARK
    elif preference == "dark":
        base = THEME_DARK
    else:
        base = THEME_LIGHT
    if accent is _UNSET:
        from app.core.config_manager import config_manager
        accent = config_manager.get_hub_accent()
    return with_accent(base, accent)


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

    /* Tooltips: pequenos, no painel do tema (o padrão do Qt herda a fonte grande e a cor do sistema) */
    QToolTip {{
        background-color: {t.menu_bg};
        color: {t.body};
        border: 1px solid {t.line};
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
        font-weight: 400;
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
