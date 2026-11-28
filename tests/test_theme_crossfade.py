"""Troca de tema com a transição comum (a do Clima): foto antiga dissolve por cima do tema novo, sem pulo no 1º quadro,
sem janelas soltas, acompanhando a janela se ela mudar de lugar/tamanho, e sem efeito quando não há o que animar."""
import contextlib
import dataclasses
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.core import theme_crossfade as tc

app = QApplication.instance() or QApplication(sys.argv)


class _Swatch(QWidget):
    """Janela que pinta uma cor sólida; trocar `color` é o "tema"."""

    def __init__(self, color="red", size=(120, 60)):
        super().__init__()
        self.color = QColor(color)
        self.resize(*size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.color)
        p.end()


class CrossfadeTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        patch = mock.patch("time.perf_counter", side_effect=lambda: self.clock[0])
        patch.start()
        self.addCleanup(patch.stop)
        anim = mock.patch.object(tc, "animations_enabled", return_value=True)
        self.anim = anim.start()
        self.addCleanup(anim.stop)
        self.w = _Swatch("red")
        self.w.show()
        app.processEvents()
        self.addCleanup(self.w.close)

    def _layer_image(self) -> QImage:
        layer = self.w._theme_crossfade
        img = QImage(self.w.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        layer.render(img)
        return img

    def _paint_at(self, progress: float) -> QImage:
        self.clock[0] = self.w._theme_crossfade._t0 + progress * tc.DURATION_MS / 1000.0
        return self._layer_image()

    def test_old_look_dissolves_over_the_new_one_and_the_layer_goes_away(self):
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("blue")        # o tema novo já está aplicado por baixo
        layer = self.w._theme_crossfade
        self.assertIsNotNone(layer)
        self.assertTrue(layer.is_running())
        first = self._paint_at(0.0)
        self.assertEqual(first.pixelColor(60, 30).red(), 255)      # 1º quadro = foto antiga inteira (sem salto)
        self.assertGreaterEqual(first.pixelColor(60, 30).alpha(), 254)
        alphas = [self._paint_at(k / 10).pixelColor(60, 30).alpha() for k in range(0, 10)]
        self.assertEqual(alphas, sorted(alphas, reverse=True))      # só some, nunca volta
        self.assertLess(alphas[-1], 40)
        self.assertTrue(any(0 < a < 255 for a in alphas))           # há meio-termo: é uma dissolvência
        self.clock[0] += 1.0
        layer._tick()                                                # passou da duração
        self.assertIsNone(self.w._theme_crossfade)
        self.assertFalse(layer.is_running())

    def test_layer_is_a_transparent_child_never_a_loose_window(self):
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("blue")
        layer = self.w._theme_crossfade
        self.assertFalse(layer.isWindow())
        self.assertIs(layer.parentWidget(), self.w)
        self.assertTrue(layer.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        layer.stop()

    def test_the_old_look_shrinks_a_little_while_leaving(self):
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("blue")
        img = self._paint_at(0.3)
        # no meio da saída a foto já encolheu: a borda extrema fica sem cor antiga, o centro ainda tem
        self.assertEqual(img.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(img.pixelColor(60, 30).alpha(), 0)

    def test_nothing_to_animate_means_plain_apply(self):
        self.anim.return_value = False                                # sem efeitos de animação do Windows
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("blue")
        self.assertIsNone(getattr(self.w, "_theme_crossfade", None))
        self.anim.return_value = True
        self.w.hide()                                                  # oculto: não há o que dissolver
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("green")
        self.assertIsNone(getattr(self.w, "_theme_crossfade", None))

    def test_the_old_look_stays_at_the_same_screen_point_if_the_window_moves_or_resizes(self):
        self.w.move(200, 150)
        app.processEvents()
        before = self.w.mapToGlobal(QPoint(0, 0))                      # onde o conteúdo estava NA TELA
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("blue")
            self.w.setGeometry(180, 140, 160, 80)                      # o tema pediu margem maior em volta
        app.processEvents()
        layer = self.w._theme_crossfade
        self.assertEqual(layer.geometry(), self.w.rect())              # a camada cobre a janela nova
        shift = before - self.w.mapToGlobal(QPoint(0, 0))              # onde a foto deve começar na janela nova
        self.assertNotEqual(shift, QPoint(0, 0))
        img = QImage(self.w.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        layer.render(img)
        inside = img.pixelColor(shift.x() + 3, shift.y() + 3)
        self.assertGreater(inside.alpha(), 200)                        # a foto está onde o conteúdo antigo estava
        self.assertEqual(inside.red(), 255)
        if shift.x() > 4 and shift.y() > 4:
            self.assertEqual(img.pixelColor(shift.x() - 3, shift.y() - 3).alpha(), 0)   # e não passa para cima/esquerda
        layer.stop()

    def test_starting_again_mid_fade_snapshots_the_widget_not_the_old_layer(self):
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("blue")
        first = self.w._theme_crossfade
        self._paint_at(0.5)
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("green")
        layer = self.w._theme_crossfade
        self.assertIsNot(layer, first)
        snap = layer._snapshot.toImage()
        self.assertEqual(snap.pixelColor(60, 30).blue(), 255)          # a foto é o azul de verdade, sem vermelho da camada
        self.assertEqual(snap.pixelColor(60, 30).red(), 0)
        self.assertFalse(first.is_running())                               # a anterior parou na hora...
        self.assertTrue(first.isHidden())                                  # ...e já não aparece (some do desenho)
        self.assertTrue(layer.is_running())
        layer.stop()

    def test_dragging_the_widget_during_the_fade_takes_the_old_look_along(self):
        with tc.theme_crossfade(self.w):
            self.w.color = QColor("blue")
        layer = self.w._theme_crossfade
        before = self._paint_at(0.0)
        self.w.move(self.w.x() + 300, self.w.y() + 120)               # o usuário arrasta no meio da dissolvência
        app.processEvents()
        after = self._paint_at(0.0)
        self.assertEqual(before.pixelColor(60, 30), after.pixelColor(60, 30))   # a foto não ficou para trás
        layer.stop()

    def test_a_failing_apply_drops_the_layer_and_propagates(self):
        with self.assertRaises(RuntimeError):
            with tc.theme_crossfade(self.w):
                raise RuntimeError("tema inválido")
        self.assertIsNone(getattr(self.w, "_theme_crossfade", None))


class RealTimeTests(unittest.TestCase):
    """Sem relógio falso: roda no relógio de quadros compartilhado e termina sozinha."""

    def test_it_runs_on_the_shared_frame_clock_and_finishes_by_itself(self):
        from app.core.frame_clock import frame_clock
        anim = mock.patch.object(tc, "animations_enabled", return_value=True)
        anim.start()
        self.addCleanup(anim.stop)
        w = _Swatch("red")
        w.show()
        app.processEvents()
        self.addCleanup(w.close)
        with tc.theme_crossfade(w):
            w.color = QColor("blue")
        layer = w._theme_crossfade
        self.assertIn(layer._timer, frame_clock()._subs)
        QTest.qWait(tc.DURATION_MS + 120)
        self.assertIsNone(getattr(w, "_theme_crossfade", None))
        self.assertNotIn(layer._timer, frame_clock()._subs)


class TeardownTests(unittest.TestCase):
    def test_the_window_dying_mid_fade_does_not_crash(self):
        """Tema trocado e, 100 ms depois, a skin trocada e apagada: a camada morre junto, sem acesso a memória solta."""
        anim = mock.patch.object(tc, "animations_enabled", return_value=True)
        anim.start()
        self.addCleanup(anim.stop)
        for _ in range(5):
            w = _Swatch("red")
            w.show()
            app.processEvents()
            with tc.theme_crossfade(w):
                w.color = QColor("blue")
            self.assertTrue(w._theme_crossfade.is_running())
            w.resize(w.width() + 10, w.height())      # o filtro de eventos está ativo
            w.close()
            w.deleteLater()
            QApplication.sendPostedEvents(w, QEvent.Type.DeferredDelete)   # só ESTE objeto (nada de varrer o processo)
            del w
        QTest.qWait(250)                               # o relógio compartilhado segue em pé, sem assinantes mortos
        from app.core.frame_clock import frame_clock
        self.assertTrue(all(sub is not None for sub in frame_clock()._subs))


class WiringTests(unittest.TestCase):
    """Cada lugar que troca tema ao vivo usa a transição comum."""

    def setUp(self):
        anim = mock.patch.object(tc, "animations_enabled", return_value=True)
        anim.start()
        self.addCleanup(anim.stop)

    def _recording(self):
        calls = []

        @contextlib.contextmanager
        def fake(widget, *a, **k):
            calls.append((widget, k))
            yield

        return calls, fake

    def test_timer_and_music_themes_apply_inside_the_crossfade(self):
        from app.hub import service_bridge as sb
        calls, fake = self._recording()
        timer_skin = mock.Mock()
        music_skin = mock.Mock()
        with mock.patch.object(sb, "theme_crossfade", fake):
            sb.HubServiceBridge.apply_timer_theme(SimpleNamespace(timer_controller=SimpleNamespace(skin=timer_skin)))
            fake_music = SimpleNamespace(music_controller=SimpleNamespace(skin=music_skin, active_skin_name="capa_empilhada"))
            sb.HubServiceBridge.apply_music_theme(fake_music)
        self.assertEqual([c[0] for c in calls], [timer_skin, music_skin])
        timer_skin.reload_skin_theme.assert_called_once()
        music_skin.reload_skin_theme.assert_called_once()

    def test_music_theme_that_switches_the_skin_does_not_fade_twice(self):
        """A skin nova já entra com a troca própria (swap_skin_windows); um 2º fade em cima dela seria feio."""
        from app.hub import service_bridge as sb
        calls, fake = self._recording()
        skin = mock.Mock()
        bridge = SimpleNamespace(music_controller=SimpleNamespace(skin=skin, active_skin_name="vinyl"),
                                 set_music_skin_active=mock.Mock(), set_music_skin=mock.Mock())
        with mock.patch.object(sb, "theme_crossfade", fake), \
                mock.patch("app.core.theme_loader.ThemeLoader.active_id", return_value="outro-tema"), \
                mock.patch.object(sb.config_manager, "get_active_widget_skins", return_value=["capa_empilhada"]):
            sb.HubServiceBridge.apply_music_theme(bridge)
        bridge.set_music_skin.assert_called_once_with("capa_empilhada")
        self.assertEqual(calls, [])                       # sem 2º fade...
        skin.reload_skin_theme.assert_called_once()       # ...mas o tema continua sendo relido, como antes

    def test_the_mixer_animates_the_switch_only_when_it_is_already_on_screen(self):
        # O mixer não usa mais a foto (theme_crossfade): mola de morph / encolhe e salta (ver test_mixer_skin_transition.py)
        from app.widgets.volume_mixer import mixer_flyout as mf
        from app.widgets.volume_mixer.theme import DEFAULT_THEME
        fly = mf.VolumeMixerFlyout()
        fly._click_timer.stop()
        self.addCleanup(fly.hide)
        shaped = dataclasses.replace(DEFAULT_THEME, tilt=-6.0)
        fly._apply_theme(shaped)                                       # oculto: aplica direto
        self.assertIsNone(fly._skin_tx)
        fly._slide_t = fly._slide_target_t = 1.0
        fly.show()
        app.processEvents()
        fly._apply_theme(DEFAULT_THEME)                                # na tela: com a transição
        self.assertIsNotNone(fly._skin_tx)
        self.assertIs(fly.theme, DEFAULT_THEME)
        fly.hide()                                                     # termina a troca na hora
        self.assertIsNone(fly._skin_tx)

    def test_the_hub_light_dark_change_uses_it_without_shrinking_the_window(self):
        from app.core.config_manager import config_manager
        from app.hub import hub_window
        patches = [
            mock.patch.object(config_manager, "get_hub_accent", return_value=None),
            mock.patch.object(config_manager, "set_hub_theme"),
            mock.patch.object(hub_window.AimedgetHubWindow, "_refresh_icons"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(hub_window.QTimer, "singleShot"):
            hub = hub_window.AimedgetHubWindow()
        hub.resize(1000, 700)
        hub.show()
        app.processEvents()
        self.addCleanup(hub.tray_icon.hide)
        self.addCleanup(hub.close)
        other = "light" if hub._current_theme.is_dark else "dark"
        hub._change_theme_mode(other)
        layer = hub.shell._theme_crossfade
        self.assertIsNotNone(layer)
        self.assertEqual(layer._shrink, 0.0)
        self.assertFalse(layer.isWindow())
        layer.stop()


if __name__ == "__main__":
    unittest.main()
