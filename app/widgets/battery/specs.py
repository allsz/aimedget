"""
Miniatura do Battery Widget para o Hub: o mesmo `paint_battery_card` do widget vivo com dispositivos de exemplo.
"""

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QColor, QPainter

from app.core.i18n import t
from app.core.preview_registry import WidgetSpec, get_widget_spec, register_widget
from app.services.battery.models import KIND_CONTROLLER, KIND_KEYBOARD, KIND_MOUSE, BatteryDevice
from app.widgets.battery import layout as lay
from app.widgets.battery.card_painter import THEME_DARK, THEME_LIGHT, paint_battery_card
from app.widgets.battery.card_state import BatteryState

_MOCK = (
    BatteryDevice("m1", "MX Master 3S", KIND_MOUSE, 82.0),
    BatteryDevice("k1", "MX Keys S", KIND_KEYBOARD, 64.0, charging=True),
    BatteryDevice("c1", "DualSense 1", KIND_CONTROLLER, 47.0),
    BatteryDevice("c2", "DualSense 2", KIND_CONTROLLER, 91.0, charging=True),
    BatteryDevice("c3", "DualSense 3", KIND_CONTROLLER, 18.0),
    BatteryDevice("m2", "VXE R1", KIND_MOUSE, 71.0),
)


def mock_state() -> BatteryState:
    state = BatteryState(animated=False)
    state.set_devices(list(_MOCK))
    state.step(0.0)
    return state


def paint_battery(p: QPainter, rect: QRectF, state=None, theme=None):
    st = state or mock_state()
    w, h = st.card_size()
    scale = min(rect.width() / w, rect.height() / h)
    tw, th = w * scale, h * scale
    target = QRectF(rect.x() + (rect.width() - tw) / 2.0, rect.y() + (rect.height() - th) / 2.0, tw, th)
    light = bool(theme is not None and not getattr(theme, "is_dark", True))
    from app.core.config_manager import config_manager
    accent = None
    if theme is not None and config_manager.get_battery("follow_accent", False):
        accent = QColor(theme.accent)
    paint_battery_card(p, target, st, theme=THEME_LIGHT if light else THEME_DARK, accent=accent)


def init_battery_spec() -> WidgetSpec:
    spec = get_widget_spec("battery")
    if spec:
        return spec
    spec = WidgetSpec(
        id="battery",
        title=t("overview_card_battery"),
        subtitle="Aimedget",
        natural_size=QSizeF(*lay.DEFAULT_SIZE),
        paint=paint_battery,
        mock_state=mock_state,
        category="widget",
    )
    register_widget(spec)
    return spec
