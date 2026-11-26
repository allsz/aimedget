"""
Especificações declarativas para as Skins do Music Player.
Permite renderizar miniaturas 100% idênticas às skins reais no Hub,
com zero timers ativos e sem overhead de CPU.
"""

from PySide6.QtCore import QSizeF, QPoint
from app.core.i18n import t
from app.core.preview_registry import SkinSpec, register_skin, get_skins_for_widget
from app.widgets.music.skins.preview_media import preview_media


_cached_instances = {}


def _get_headless(skin_id: str, skin_class_loader):
    if skin_id not in _cached_instances:
        SkinClass = skin_class_loader()
        skin = SkinClass(scale=0.50)
        skin.set_glow_room(False)   # miniatura: sem a folga do brilho de ancorado (a imagem é o cartão)
        if hasattr(skin, "timer"):
            skin.timer.stop()
        skin.title_text = "Nome da Música"
        skin.artist_text = "Artista"
        skin.is_playing = True
        skin.current_time = 85.0
        skin.duration = 243.0
        # A mesma "música" em todas as miniaturas (ver preview_media.py); cada skin sabe aplicá-la
        skin.apply_preview_media(preview_media())
        _cached_instances[skin_id] = skin
    return _cached_instances[skin_id]


_loaders: dict = {}   # skin_id -> loader, para o aquecimento em segundo plano


def warm_previews(delay_ms: int = 700):
    """
    Monta as skins das miniaturas aos poucos (uma por volta do laço de eventos), depois de `delay_ms`. Sem isso a
    primeira visita à página Música montava as quatro de uma vez no paint (~100 ms de travada no clique).
    """
    from PySide6.QtCore import QTimer

    pending = [sid for sid in _loaders if sid not in _cached_instances]

    def _next():
        while pending:
            sid = pending.pop(0)
            if sid not in _cached_instances:
                _get_headless(sid, _loaders[sid])
                break
        if pending:
            QTimer.singleShot(0, _next)

    if pending:
        QTimer.singleShot(max(0, int(delay_ms)), _next)


def _make_skin_paint(skin_id: str, skin_class_loader):
    _loaders[skin_id] = skin_class_loader
    def paint_fn(p, rect, state, theme):
        skin = _get_headless(skin_id, skin_class_loader)
        skin.render(p, QPoint(int(rect.x()), int(rect.y())))
    return paint_fn


def init_music_skin_specs() -> list[SkinSpec]:
    """Inicializa e registra as especificações visuais das 4 skins de música."""
    existing = get_skins_for_widget("music")
    if existing:
        return existing

    def load_vinyl():
        from app.widgets.music.skins.vinyl_skin import VinylMusicSkin
        return VinylMusicSkin

    def load_fullcover():
        from app.widgets.music.skins.fullcover_skin import FullCoverSkin
        return FullCoverSkin

    def load_ripple():
        from app.widgets.music.skins.ripple_skin import RippleSkin
        return RippleSkin

    def load_capa_empilhada():
        from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
        return CapaEmpilhadaSkin

    specs = [
        SkinSpec(
            id="vinyl",
            widget_id="music",
            supports_themes=False,
            title=t("skin_vinyl_title"),
            subtitle=t("skin_vinyl_sub"),
            natural_size=QSizeF(480, 270),
            paint=_make_skin_paint("vinyl", load_vinyl),
            mock_state=lambda: None,
        ),
        SkinSpec(
            id="fullcover",
            widget_id="music",
            supports_themes=False,
            title=t("skin_fullcover_title"),
            subtitle=t("skin_fullcover_sub"),
            natural_size=QSizeF(480, 270),
            paint=_make_skin_paint("fullcover", load_fullcover),
            mock_state=lambda: None,
        ),
        SkinSpec(
            id="ripple",
            widget_id="music",
            supports_themes=False,
            title=t("skin_ripple_title"),
            subtitle=t("skin_ripple_sub"),
            natural_size=QSizeF(480, 270),
            paint=_make_skin_paint("ripple", load_ripple),
            mock_state=lambda: None,
        ),
        SkinSpec(
            id="capa_empilhada",
            widget_id="music",
            title=t("skin_stacked_title"),
            subtitle=t("skin_stacked_sub"),
            natural_size=QSizeF(490, 240),
            paint=_make_skin_paint("capa_empilhada", load_capa_empilhada),
            mock_state=lambda: None,
        ),
    ]

    for s in specs:
        register_skin(s)

    return specs
