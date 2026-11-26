from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
from app.widgets.keylock_osd.skin import KeyLockState, paint_keylock, natural_size
from app.core.preview_registry import WidgetSpec, register_widget


def keylock_mock_state(theme=None):
    from app.widgets.keylock_osd.theme import default_theme
    return KeyLockState(
        label="Caps Lock",
        is_on=True,
        anim_val=1.0,
        draw_shadow=True,
        theme=theme if theme is not None else default_theme(),   # o visual "Windows" no modo atual do Windows
    )


KEYLOCK_SPEC = WidgetSpec(
    id="keylock_osd",
    title="Lock keys",
    subtitle="Flyouts minimalistas para Caps Lock e Num Lock",
    natural_size=natural_size,
    paint=paint_keylock,
    mock_state=keylock_mock_state,
    category="widget",
    create_live=lambda: KeyLockFlyout(),
)

register_widget(KEYLOCK_SPEC)

__all__ = ["KeyLockFlyout", "KEYLOCK_SPEC", "keylock_mock_state"]
