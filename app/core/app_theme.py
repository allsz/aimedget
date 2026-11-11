"""
Tema "Aimedget": os flyouts (Volume/Mixer e Caps/Num Lock) herdam a aparência do app.

Diferente de um tema de pasta (theme.json estático), este é calculado a partir do `HubTheme` em uso
(claro / escuro / true dark + cor de destaque), então acompanha o app quando o usuário muda um deles.
Só cores: formato, raio, sombra e tamanho continuam os originais de cada flyout.

As funções `*_from_hub` são puras e memorizadas por `HubTheme` (dataclass congelada): enquanto o app não
mudar de aparência devolvem o MESMO objeto, que é o que o loader e as miniaturas usam para saber se algo mudou.
"""

from functools import lru_cache

from PySide6.QtGui import QColor

from app.hub.theme import HubTheme
from app.widgets.keylock_osd.theme import KeyLockTheme
from app.widgets.volume_mixer.theme import MixerTheme


def current_hub_theme() -> HubTheme:
    """Aparência salva do app (modo + destaque), a mesma que o Hub e o menu usam."""
    from app.core.config_manager import config_manager
    from app.hub.theme import resolve_theme
    return resolve_theme(config_manager.get_hub_theme("system"))


def _c(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def _mix(a: str, b: str, amount: float, alpha: int = 255) -> QColor:
    """`a` com `amount` (0..1) de `b` misturado."""
    ca, cb = QColor(a), QColor(b)
    k = max(0.0, min(1.0, amount))
    return QColor(round(ca.red() + (cb.red() - ca.red()) * k),
                  round(ca.green() + (cb.green() - ca.green()) * k),
                  round(ca.blue() + (cb.blue() - ca.blue()) * k), alpha)


@lru_cache(maxsize=16)
def mixer_theme_from_hub(hub: HubTheme) -> MixerTheme:
    return MixerTheme(
        card_bg=_c(hub.panel, 248),
        border=_c(hub.line),
        text=_c(hub.text),
        muted_text=_c(hub.mute),
        icon=_c(hub.text),
        accent=_c(hub.accent),
        thumb=_c(hub.accent),
        thumb_outer=_c(hub.panel2),
        thumb_border=_c(hub.line),
        track_inactive=_mix(hub.mute, hub.panel, 0.45),
        button_bg=_c(hub.panel2),
        button_hover=_mix(hub.panel2, hub.text, 0.07),
        button_pressed=_mix(hub.panel2, hub.bg, 0.6),
        button_border=_c(hub.line),
        divider=_c(hub.line),
        on_accent=_c(hub.ink),
        switch_on=_c(hub.accent),
        drawer_bg=_mix(hub.panel, hub.text, 0.04, 250),
        drawer_border=_c(hub.line),
        tabs_bg=_c(hub.panel2, 220),
        tabs_border=_c(hub.line),
    )


@lru_cache(maxsize=16)
def keylock_theme_from_hub(hub: HubTheme) -> KeyLockTheme:
    return KeyLockTheme(
        card_bg=_c(hub.panel, 248),
        border=_c(hub.line),
        text=_c(hub.text),
        icon=_c(hub.text),
        off_color=_c(hub.panel2),
        on_color=_c(hub.accent),
    )


def app_mixer_theme() -> MixerTheme:
    return mixer_theme_from_hub(current_hub_theme())


def app_keylock_theme() -> KeyLockTheme:
    return keylock_theme_from_hub(current_hub_theme())
