from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
from app.widgets.keylock_osd.skin import KeyLockState, paint_keylock, natural_size
from app.core.preview_registry import WidgetSpec, register_widget


def _create_mock_state():
    return KeyLockState(
        label="Caps Lock",
        is_on=True,
        anim_val=1.0,
        draw_shadow=True,
    )


KEYLOCK_SPEC = WidgetSpec(
    id="keylock_osd",
    title="Lock keys",
    subtitle="Flyouts minimalistas para Caps Lock e Num Lock",
    natural_size=natural_size,
    paint=paint_keylock,
    mock_state=_create_mock_state,
    category="widget",
    create_live=lambda: KeyLockFlyout(),
)

register_widget(KEYLOCK_SPEC)

__all__ = ["KeyLockFlyout", "KEYLOCK_SPEC"]
