"""
Miniatura do Storage Widget para o Hub (página Personalização).
Usa o mesmo `paint_storage_card` do widget vivo com estado estático de exemplo.
"""

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QPainter

from app.core.i18n import t
from app.core.preview_registry import WidgetSpec, get_widget_spec, register_widget
from app.services.storage_service import DriveUsage, FolderUsage, StorageSnapshot
from app.widgets.storage.card_painter import paint_storage_card
from app.widgets.storage.card_state import CARD_W, COMPACT_H, StorageState


def mock_state() -> StorageState:
    gb = 1024 ** 3
    snap = StorageSnapshot(
        drives=[
            DriveUsage(
                drive="D:",
                label="Secondary SSD (D:)",
                total_bytes=int(931 * gb),
                used_bytes=int(642.8 * gb),
                folders=[
                    FolderUsage("Emulators", "D:\\Emulators", "D:", int(312.6 * gb), 18450),
                    FolderUsage("Videos", "D:\\Videos", "D:", int(118.2 * gb), 96),
                    FolderUsage("Downloads", "D:\\Downloads", "D:", int(64.5 * gb), 412),
                ],
            ),
            DriveUsage(
                drive="C:",
                label="System SSD (C:)",
                total_bytes=int(476 * gb),
                used_bytes=int(240.0 * gb),
                folders=[
                    FolderUsage("Downloads", "C:\\Users\\User\\Downloads", "C:", int(42.8 * gb), 1420),
                ],
            ),
        ]
    )
    state = StorageState(animated=False, always_expanded=False)
    state.apply_snapshot(snap, animate=False)
    return state


def paint_storage(p: QPainter, rect: QRectF, state=None, theme=None):
    st = state or mock_state()
    scale = min(rect.width() / CARD_W, rect.height() / COMPACT_H)
    w, h = CARD_W * scale, COMPACT_H * scale
    target = QRectF(rect.x() + (rect.width() - w) / 2.0, rect.y() + (rect.height() - h) / 2.0, w, h)
    light = bool(theme is not None and not getattr(theme, "is_dark", True))
    paint_storage_card(p, target, st, light=light, theme=theme)


def init_storage_spec() -> WidgetSpec:
    spec = get_widget_spec("storage")
    if spec:
        return spec
    spec = WidgetSpec(
        id="storage",
        title=t("overview_card_storage"),
        subtitle="Aimedget",
        natural_size=QSizeF(CARD_W, COMPACT_H),
        paint=paint_storage,
        mock_state=mock_state,
        category="widget",
    )
    register_widget(spec)
    return spec
