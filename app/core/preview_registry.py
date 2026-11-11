"""
Preview Registry - Sistema central de registro declarativo para Widgets e Skins.
Permite que o Hub renderize miniaturas reais e precisas de forma automatizada,
orientada a dados e sem timers ou overhead em segundo plano.
"""

from dataclasses import dataclass
from typing import Callable, Any
from PySide6.QtCore import QSizeF, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget


@dataclass
class WidgetSpec:
    """Especificação declarativa para um widget completo do sistema."""
    id: str
    title: str
    subtitle: str
    natural_size: Callable[[Any], QSizeF] | QSizeF
    paint: Callable[[QPainter, QRectF, Any, Any], None]
    mock_state: Callable[[], Any]
    category: str = "widget"
    create_live: Callable[[], QWidget] | None = None


@dataclass
class SkinSpec:
    """Especificação declarativa para uma variação visual (skin) de um widget."""
    id: str
    widget_id: str
    title: str
    subtitle: str
    natural_size: Callable[[Any], QSizeF] | QSizeF
    paint: Callable[[QPainter, QRectF, Any, Any], None]
    mock_state: Callable[[], Any]
    available: bool = True   # False = vaga "TBA": não é selecionável nem reage ao mouse


WIDGET_REGISTRY: dict[str, WidgetSpec] = {}
SKIN_REGISTRY: dict[str, list[SkinSpec]] = {}


def register_widget(spec: WidgetSpec) -> None:
    """Registra uma especificação de widget no sistema."""
    WIDGET_REGISTRY[spec.id] = spec


def register_skin(spec: SkinSpec) -> None:
    """Registra uma especificação de skin para um determinado widget."""
    if spec.widget_id not in SKIN_REGISTRY:
        SKIN_REGISTRY[spec.widget_id] = []
    # Substitui se já existir com o mesmo id
    SKIN_REGISTRY[spec.widget_id] = [
        s for s in SKIN_REGISTRY[spec.widget_id] if s.id != spec.id
    ]
    SKIN_REGISTRY[spec.widget_id].append(spec)


def get_widget_spec(widget_id: str) -> WidgetSpec | None:
    return WIDGET_REGISTRY.get(widget_id)


def get_skins_for_widget(widget_id: str) -> list[SkinSpec]:
    return SKIN_REGISTRY.get(widget_id, [])


def get_all_widgets() -> list[WidgetSpec]:
    return list(WIDGET_REGISTRY.values())
