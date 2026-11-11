"""Menu de contexto do Music Widget: "Fechar widget" (como no Timer), ligado ao mesmo caminho do atalho."""

import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from app.core.i18n import t
from app.ui_components.fluent_menu import FluentMusicMenu
from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin
from app.widgets.music.skins.fullcover_skin import FullCoverSkin
from app.widgets.music.skins.ripple_skin import RippleSkin
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin

_app = QApplication.instance() or QApplication([])
SKINS = (CapaEmpilhadaSkin, FullCoverSkin, RippleSkin, VinylMusicSkin)


def _make(cls):
    try:
        return cls(scale=0.5)
    except TypeError:
        return cls()


def _open_menu(skin):
    """Dispara o menu de contexto sem bloquear em exec() e devolve as ações de nível superior."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    captured = {}

    def fake_exec(self, *args, **kwargs):
        captured["actions"] = list(self.actions())

    with mock.patch.object(FluentMusicMenu, "exec", fake_exec):
        skin.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)))
    return captured["actions"]


class CloseMenuItemTests(unittest.TestCase):
    def test_close_is_the_last_item_of_every_skin_menu_with_an_icon(self):
        for cls in SKINS:
            with self.subTest(skin=cls.__name__):
                actions = _open_menu(_make(cls))
                last = actions[-1]
                self.assertEqual(last.text(), t("menu_close_widget"))
                self.assertFalse(last.icon().isNull())
                self.assertTrue(actions[-2].isSeparator())      # separado das preferências, como no Timer

    def test_clicking_it_emits_close_requested(self):
        skin = _make(VinylMusicSkin)
        got = []
        skin.close_requested.connect(lambda: got.append(1))
        _open_menu(skin)[-1].trigger()
        self.assertEqual(got, [1])

    def test_label_in_both_languages(self):
        from app.core import i18n
        self.assertEqual(i18n.TRANSLATIONS["pt"]["menu_close_widget"], "Fechar widget")
        self.assertTrue(i18n.TRANSLATIONS["en"]["menu_close_widget"])


class ControllerCloseTests(unittest.TestCase):
    def test_close_request_hides_like_the_hotkey_does(self):
        from app.widgets.music.music_controller import MusicWidgetController

        class Worker:
            from PySide6.QtCore import QObject, Signal
            _last_is_playing = False
            _last_title = ""
            current_source_app_id = ""
            _last_provider = ""

            def __init__(self):
                from PySide6.QtCore import QObject, Signal

                class Sig(QObject):
                    media_updated = Signal(str, str, bool, float, float, object, str)
                self._s = Sig()
                self.media_updated = self._s.media_updated

            def send_command(self, *a):
                pass

        c = MusicWidgetController(media_worker=Worker())
        try:
            with mock.patch.object(c, "hide") as hide:
                c.skin.close_requested.emit()
                hide.assert_called_once_with(by_user=True)
        finally:
            c.skin.close()


if __name__ == "__main__":
    unittest.main()


class MenuTranslationTests(unittest.TestCase):
    def test_every_skin_menu_follows_the_app_language(self):
        from app.core.i18n import i18n
        with mock.patch.object(i18n, "_current_lang", "en"):
            for cls in SKINS:
                with self.subTest(skin=cls.__name__):
                    texts = [a.text() for a in _open_menu(_make(cls))]
                    self.assertIn("Size", texts)
                    self.assertIn("Remember position", texts)
                    self.assertNotIn("Tamanho", texts)
                    self.assertNotIn("Lembrar posição", texts)


class NoMediaTextTests(unittest.TestCase):
    def test_placeholder_is_translated_only_when_shown(self):
        from app.core.i18n import i18n
        for cls in SKINS:
            with self.subTest(skin=cls.__name__):
                skin = _make(cls)
                with mock.patch.object(i18n, "_current_lang", "en"):
                    self.assertEqual(skin.shown_title(), "Nothing playing right now")
                    self.assertEqual(skin.shown_artist(), "What are we listening to today?")
                self.assertEqual(skin.title_text, "Nenhuma mídia ativa")      # o marcador interno não muda
                skin.title_text, skin.artist_text = "Faixa", "Artista"
                self.assertEqual((skin.shown_title(), skin.shown_artist()), ("Faixa", "Artista"))
