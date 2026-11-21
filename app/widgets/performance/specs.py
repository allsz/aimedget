"""
Miniatura do Performance Widget para o Hub (cartão da Visão Geral).
Usa o mesmo `paint_performance_card` do widget vivo com um estado de exemplo parado (zero timers, zero Win32).
"""

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPainter

from app.core.i18n import t
from app.core.preview_registry import SkinSpec, WidgetSpec, get_widget_spec, register_skin, register_widget
from app.services.performance_service import PerformanceSnapshot
from app.ui_components.floating_card import CARD_H, CARD_W
from app.widgets.performance.card_painter import paint_performance_card
from app.widgets.performance.card_state import PerformanceState, SKIN_FLUENT, SKIN_NOTHING_DOT

_MOCK_CPU_SERIES = (
    18, 22, 20, 26, 32, 28, 24, 19, 17, 21, 29, 38, 44, 39, 34, 30, 27, 25, 22, 24,
    28, 33, 31, 26, 23, 21, 25, 30, 29, 27, 24, 22, 26, 35, 41, 37, 32, 28, 26, 24,
)


def mock_state(skin_id: str = SKIN_FLUENT) -> PerformanceState:
    state = PerformanceState(selected="cpu", skin_id=skin_id)
    for val in _MOCK_CPU_SERIES:
        state.history["cpu"].append(float(val))
    state.latest = PerformanceSnapshot(
        cpu_pct=24.0,
        cpu_ghz=3.85,
        gpu_pct=62.0,
        gpu_name="RTX 3080 Ti",
        vram_pct=28.0,
        vram_used_gb=3.3,
        vram_total_gb=11.8,
        ram_pct=44.0,
        ram_used_gb=14.1,
        ram_total_gb=32.0,
    )
    return state


def paint_performance(p: QPainter, rect: QRectF, state, theme=None):
    """Encaixa o cartão (300:262) no retângulo, centralizado."""
    state = state or mock_state()
    scale = min(rect.width() / CARD_W, rect.height() / CARD_H)
    w, h = CARD_W * scale, CARD_H * scale
    target = QRectF(rect.x() + (rect.width() - w) / 2.0, rect.y() + (rect.height() - h) / 2.0, w, h)
    paint_performance_card(p, target, state)


def init_performance_spec() -> WidgetSpec:
    spec = get_widget_spec("performance")
    if spec:
        return spec
    spec = WidgetSpec(
        id="performance",
        title="Performance",
        subtitle="Aimedget",
        natural_size=QSizeF(CARD_W, CARD_H),
        paint=paint_performance,
        mock_state=mock_state,
        category="widget",
    )
    register_widget(spec)
    return spec


def init_performance_skin_specs() -> list[SkinSpec]:
    specs = [
        SkinSpec(
            id=SKIN_FLUENT,
            widget_id="performance",
            title=t("perf_skin_label"),
            subtitle="",
            natural_size=QSizeF(CARD_W, CARD_H),
            paint=paint_performance,
            mock_state=lambda: mock_state(SKIN_FLUENT),
        ),
        SkinSpec(
            id=SKIN_NOTHING_DOT,
            widget_id="performance",
            title="Nothing Dot",
            subtitle="",
            natural_size=QSizeF(CARD_W, CARD_H),
            paint=paint_performance,
            mock_state=lambda: mock_state(SKIN_NOTHING_DOT),
        ),
    ]
    for s in specs:
        register_skin(s)
    return specs
