"""Galeria de temas do Timer: recolhe (animada) quando a skin ativa não aceita temas, e volta ao trocar de skin."""

import sys
import unittest
from unittest import mock

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app.hub.components import collapsible_section as cs
from app.hub.components.collapsible_section import CollapsibleSection


def _finish(section, timeout_ms=3000):
    """Espera a animação acabar (o relógio de animações do Qt pode atrasar quando outros testes ocupam o loop)."""
    waited = 0
    while section.is_animating() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20


def _section(opened=True):
    host = QWidget()
    lay = QVBoxLayout(host)
    inner = QWidget()
    QVBoxLayout(inner).addWidget(QLabel("conteudo"))
    section = CollapsibleSection(inner, gap=18, opened=opened)
    lay.addWidget(section)
    host.resize(400, 300)
    host.show()
    return host, section, inner


class CollapsibleSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_starts_in_the_requested_state(self):
        _host, section, _ = _section(opened=False)
        self.assertFalse(section.isVisible())
        _host2, section2, _ = _section(opened=True)
        self.assertTrue(section2.isVisible())

    def test_collapse_animates_then_hides(self):
        _host, section, _inner = _section()
        with mock.patch.object(cs, "animations_enabled", return_value=True):
            section.set_open(False)
            self.assertTrue(section.is_animating())
            self.assertTrue(section.isVisible())          # ainda recolhendo
            _finish(section)
        self.assertFalse(section.isVisible())
        self.assertFalse(section.is_open())

    def test_expand_restores_full_size_without_height_limit(self):
        _host, section, inner = _section(opened=False)
        with mock.patch.object(cs, "animations_enabled", return_value=True):
            section.set_open(True)
            _finish(section)
        self.assertTrue(section.isVisible())
        self.assertEqual(section.height(), section._natural_height(section.width()))   # altura natural cheia
        self.assertEqual(inner.height(), section.height() - 18)                          # o conteudo nunca foi espremido
        self.assertIsNone(section._snapshot)        # a foto so existe durante a animacao
        self.assertTrue(inner.isVisible())           # os widgets reais voltam ao fim

    def test_content_is_never_squeezed_while_animating(self):
        _host, section, inner = _section()
        full = inner.height()
        with mock.patch.object(cs, "animations_enabled", return_value=True):
            section.set_open(False)
            for _ in range(6):
                QTest.qWait(25)
                self.assertEqual(inner.height(), full)          # so a secao muda de altura; o conteudo e cortado
                self.assertLessEqual(section.height(), full + 18)
            _finish(section)

    def test_height_only_shrinks_while_collapsing(self):
        _host, section, _inner = _section()
        heights = []
        with mock.patch.object(cs, "animations_enabled", return_value=True):
            section.set_open(False)
            while section.is_animating():
                QTest.qWait(10)
                heights.append(section.height())
        self.assertEqual(heights, sorted(heights, reverse=True))   # nunca cresce no meio (era o "tranco")

    def test_opening_really_animates(self):
        """Regressao: setStartValue/setEndValue emitiam valueChanged e a abertura durava 1 ms (a galeria so aparecia)."""
        _host, section, _inner = _section()
        with mock.patch.object(cs, "animations_enabled", return_value=True):
            section.set_open(False)
            _finish(section)
            values = []
            section._anim.valueChanged.connect(lambda v: values.append(float(v)))
            section.set_open(True)
            self.assertGreaterEqual(section._anim.duration(), cs.DURATION_MS - 1)
            _finish(section)
        self.assertGreater(len(values), 5)
        self.assertEqual(values, sorted(values))   # so cresce, sem pular para o fim e voltar

    def test_instant_when_system_animations_are_off(self):
        _host, section, _inner = _section()
        with mock.patch.object(cs, "animations_enabled", return_value=False):
            section.set_open(False)
        self.assertFalse(section.is_animating())
        self.assertFalse(section.isVisible())

    def test_reversing_midway_continues_from_the_current_point(self):
        _host, section, _inner = _section()
        with mock.patch.object(cs, "animations_enabled", return_value=True):
            section.set_open(False)
            QTest.qWait(cs.DURATION_MS // 3)
            section.set_open(True)
            _finish(section)
        self.assertTrue(section.isVisible())
        self.assertTrue(section.is_open())


class TimerPageThemeGalleryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_gallery_follows_the_active_skin(self):
        from app.hub.pages import TimerPage
        page = TimerPage()
        page.resize(900, 900)
        page.show()
        self.addCleanup(page.close)
        ctrl = page.bridge.timer_controller
        original = ctrl.active_skin_name
        self.addCleanup(ctrl.set_skin, original)
        with mock.patch.object(cs, "animations_enabled", return_value=False):
            ctrl.set_skin("shinra")
            self.assertFalse(page.theme_section.isVisible())
            self.assertFalse(page.theme_picker.isVisible())
            ctrl.set_skin("windows")
            self.assertTrue(page.theme_section.isVisible())
            self.assertTrue(page.theme_picker.isVisible())

    def test_nothing_above_the_gallery_moves_while_it_animates(self):
        """Regressao do "tranco": a sobra de altura virava vaos entre os cards e empurrava a skin para baixo."""
        from PySide6.QtCore import QPoint
        from app.hub.pages import TimerPage
        for height in (700, 1100):
            page = TimerPage()
            page.resize(900, height)
            page.show()
            self.addCleanup(page.close)
            QTest.qWait(100)
            ctrl = page.bridge.timer_controller
            original = ctrl.active_skin_name
            self.addCleanup(ctrl.set_skin, original)
            ctrl.set_skin("windows")
            _finish(page.theme_section)
            rest = page.sk_header.mapTo(page, QPoint(0, 0)).y()
            seen = []
            with mock.patch.object(cs, "animations_enabled", return_value=True):
                for skin in ("shinra", "windows"):
                    ctrl.set_skin(skin)
                    while page.theme_section.is_animating():
                        QTest.qWait(8)
                        seen.append(page.sk_header.mapTo(page, QPoint(0, 0)).y())
            self.assertTrue(seen)
            self.assertEqual(set(seen), {rest}, f"viewport {height}")

    def test_live_widgets_are_hidden_while_animating(self):
        """Anima uma foto do conteudo: os cards nao sao repintados a cada quadro (era o tearing)."""
        _host, section, inner = _section()
        with mock.patch.object(cs, "animations_enabled", return_value=True):
            section.set_open(False)
            self.assertIsNotNone(section._snapshot)
            self.assertFalse(inner.isVisible())
            _finish(section)

    def test_music_gallery_only_for_the_stacked_cover(self):
        from app.hub.pages import MusicPage
        page = MusicPage()
        page.resize(900, 900)
        page.show()
        self.addCleanup(page.close)
        ctrl = page.bridge.music_controller
        original = ctrl.active_skin_name
        self.addCleanup(page.bridge.set_music_skin, original)
        with mock.patch.object(cs, "animations_enabled", return_value=False):
            page.bridge.set_music_skin("vinyl")
            self.assertFalse(page.theme_section.isVisible())
            page.bridge.set_music_skin("capa_empilhada")
            self.assertTrue(page.theme_section.isVisible())

    def test_skin_card_keeps_its_size_while_the_gallery_animates(self):
        """Regressao do "espasmo": com a pagina maior que a janela, o layout espremia o card de skins a cada quadro."""
        from app.hub.pages import TimerPage
        for height in (420, 760):
            page = TimerPage()
            page.resize(1000, height)
            page.show()
            self.addCleanup(page.close)
            QTest.qWait(100)
            card = page.sk_header.parentWidget()
            ctrl = page.bridge.timer_controller
            original = ctrl.active_skin_name
            self.addCleanup(ctrl.set_skin, original)
            ctrl.set_skin("windows")
            _finish(page.theme_section)
            rest = card.height()
            seen = []
            with mock.patch.object(cs, "animations_enabled", return_value=True):
                for skin in ("shinra", "windows"):
                    ctrl.set_skin(skin)
                    while page.theme_section.is_animating():
                        QTest.qWait(5)
                        seen.append(card.height())
            self.assertTrue(seen)
            self.assertEqual(set(seen), {rest}, f"janela de {height}px")
            self.assertEqual(card.minimumHeight(), 0)   # a trava sai no fim

    def test_only_skins_with_art_of_their_own_opt_out(self):
        from app.widgets.timer.skins import init_timer_skin_specs
        flags = {s.id: s.supports_themes for s in init_timer_skin_specs()}
        self.assertTrue(flags["windows"])
        self.assertFalse(flags["shinra"])


if __name__ == "__main__":
    unittest.main()
