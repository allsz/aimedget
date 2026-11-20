import time
import unittest

from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from app.hub.components import tab_pill as tp
from app.hub.components.sidebar import HubSidebar
from app.hub.theme import THEME_LIGHT

_app = QApplication.instance() or QApplication([])


def _run(pill, limit=3.0, each=None):
    end = time.monotonic() + limit
    while pill.is_animating() and time.monotonic() < end:
        _app.processEvents()
        if each:
            each()
        time.sleep(0.005)


class _Anim:
    def __init__(self, on: bool):
        self.on = on

    def __enter__(self):
        self.orig = tp.animations_enabled
        tp.animations_enabled = lambda: self.on

    def __exit__(self, *a):
        tp.animations_enabled = self.orig


def _group(selected="a"):
    g = tp.ChipGroup([("a", "85%"), ("b", "100%"), ("c", "120%")], lambda k: None, THEME_LIGHT, selected=selected)
    g.resize(260, 32)
    g.show()
    _app.processEvents()
    return g


class ChipGroupTests(unittest.TestCase):
    def test_slides_stretches_and_settles(self):
        with _Anim(True):
            g = _group()
            pill = g.pill()
            start = pill.rect_now()
            g.set_selected("c")
            self.assertTrue(pill.is_animating())
            self.assertAlmostEqual(pill.rect_now().x(), start.x(), delta=1.0)   # não pulou
            widths = []
            _run(pill, each=lambda: widths.append(pill.rect_now().width()))
            self.assertGreater(max(widths), start.width() + 1.0)                 # esticou no caminho
            target = g.button("c").geometry()
            self.assertAlmostEqual(pill.rect_now().x(), target.x(), delta=0.1)
            self.assertAlmostEqual(pill.rect_now().width(), target.width(), delta=0.1)
            self.assertFalse(pill.is_animating())
            g.close()

    def test_without_animations_is_instant(self):
        with _Anim(False):
            g = _group()
            g.set_selected("c")
            self.assertFalse(g.pill().is_animating())
            self.assertAlmostEqual(g.pill().rect_now().x(), g.button("c").geometry().x(), delta=0.1)
            g.close()

    def test_no_selection_fades_out_and_back_in_place(self):
        with _Anim(True):
            g = _group()
            pill = g.pill()
            g.set_selected(None)
            self.assertTrue(pill.is_animating())
            self.assertGreater(pill._alpha.x, 0.0)                              # ainda não sumiu de uma vez
            _run(pill)
            self.assertEqual(pill._alpha.x, 0.0)
            g.set_selected("b")
            self.assertAlmostEqual(pill.rect_now().x(), g.button("b").geometry().x(), delta=0.1)  # volta no lugar
            _run(pill)
            self.assertEqual(pill._alpha.x, 1.0)
            g.close()

    def test_text_color_follows_coverage(self):
        with _Anim(True):
            g = _group()
            pill = g.pill()
            self.assertAlmostEqual(pill.coverage(g.button("a")), 1.0, delta=0.01)
            self.assertAlmostEqual(pill.coverage(g.button("c")), 0.0, delta=0.01)
            g.close()


class VerticalPillTests(unittest.TestCase):
    def test_moves_on_y_axis_and_leading_edge_is_bottom_when_going_down(self):
        with _Anim(True):
            host = QWidget()
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            pill = tp.TabPill(host, vertical=True)
            btns = []
            for i in range(4):
                b = QPushButton(str(i), host)
                b.setFixedSize(120, 30)
                lay.addWidget(b)
                pill.track(i, b)
                btns.append(b)
            host.resize(120, 140)
            host.show()
            _app.processEvents()
            pill.select(0, animated=False)
            x0 = pill.rect_now().x()
            pill.select(3)
            self.assertEqual((pill._b.k, pill._b.c), tp.LEAD)
            self.assertEqual((pill._a.k, pill._a.c), tp.TRAIL)
            heights, xs, tops = [], [], []
            _run(pill, each=lambda: (heights.append(pill.rect_now().height()), xs.append(pill.rect_now().x()),
                                     tops.append(pill.rect_now().y())))
            self.assertGreater(max(heights), 31.0)                              # esticou na vertical
            self.assertTrue(all(abs(x - x0) < 0.01 for x in xs))                # X não mexe
            self.assertAlmostEqual(pill.rect_now().y(), btns[3].geometry().y(), delta=0.1)
            # indo para cima a ponta de cima é que lidera
            pill.select(1)
            self.assertEqual((pill._a.k, pill._a.c), tp.LEAD)
            _run(pill)
            host.close()

    def test_sidebar_pill_follows_selected_page(self):
        with _Anim(False):
            bar = HubSidebar(THEME_LIGHT)
            bar.resize(200, 500)
            bar.show()
            _app.processEvents()
            bar.select_page("timer")
            g = bar._buttons["timer"].geometry()
            r = bar._pill.rect_now()
            self.assertAlmostEqual(r.y(), g.y(), delta=0.1)
            self.assertAlmostEqual(r.height(), g.height(), delta=0.1)
            bar.close()



class SnappyTests(unittest.TestCase):
    def test_pill_settles_visibly_within_about_180ms(self):
        with _Anim(True):
            g = _group()
            pill = g.pill()
            g.set_selected("c")
            target = g.button("c").geometry()
            t0 = time.monotonic()
            visible_done = None
            while pill.is_animating() and time.monotonic() - t0 < 1.0:
                _app.processEvents()
                r = pill.rect_now()
                if visible_done is None and abs(r.x() - target.x()) < 0.5 and abs(r.width() - target.width()) < 0.5:
                    visible_done = time.monotonic() - t0
                time.sleep(0.002)
            self.assertIsNotNone(visible_done)
            self.assertLess(visible_done, 0.30)    # curto salto, com folga para o timer do teste
            g.close()

    def test_container_height_never_changes(self):
        with _Anim(True):
            g = _group()
            h0 = g.height()
            g.set_selected("c")
            heights = []
            _run(g.pill(), each=lambda: heights.append(g.height()))
            self.assertTrue(all(h == h0 for h in heights))
            g.close()


class PositionPickerMotionTests(unittest.TestCase):
    def test_highlight_slides_and_settles(self):
        from app.hub.components.position_picker import PositionPicker
        with _Anim(True):
            pk = PositionPicker("tl", THEME_LIGHT)
            pk.show()
            _app.processEvents()
            pk.set_position("br")
            self.assertTrue(pk.is_animating())
            start = pk._pill_rect("tl")
            self.assertAlmostEqual(pk.highlight_rect().x(), start.x(), delta=2.0)     # nao pulou
            end = time.monotonic() + 2.0
            while pk.is_animating() and time.monotonic() < end:
                _app.processEvents()
                time.sleep(0.004)
            self.assertFalse(pk.is_animating())
            self.assertEqual(pk.get_position(), "br")
            self.assertAlmostEqual(pk.highlight_rect().x(), pk._pill_rect("br").x(), delta=0.05)
            pk.close()

    def test_without_animations_is_instant(self):
        from app.hub.components.position_picker import PositionPicker
        with _Anim(False):
            pk = PositionPicker("tl", THEME_LIGHT)
            pk.show()
            pk.select("br")
            self.assertFalse(pk.is_animating())
            self.assertAlmostEqual(pk.highlight_rect().y(), pk._pill_rect("br").y(), delta=0.05)
            pk.close()


class PreviewCardSelectionTests(unittest.TestCase):
    def test_selection_blends_instead_of_jumping(self):
        from app.core.preview_registry import WidgetSpec  # noqa: F401  (garante o registro importado)
        from app.core.preview_card import PreviewCard
        from app.widgets.timer import init_timer_skin_specs
        spec = init_timer_skin_specs()[0]
        with _Anim(True):
            card = PreviewCard(spec=spec, theme=THEME_LIGHT, is_selected=False)
            card.resize(190, 170)
            card.show()
            _app.processEvents()
            card.set_selected(True)
            self.assertLess(card._sel.value, 1.0)
            end = time.monotonic() + 1.5
            while card._sel.is_animating() and time.monotonic() < end:
                _app.processEvents()
                time.sleep(0.004)
            self.assertEqual(card._sel.value, 1.0)
            card.close()


class PageTransitionTests(unittest.TestCase):
    def test_overlay_fades_out_and_hides_in_180ms(self):
        from PySide6.QtGui import QPixmap
        from app.hub.components import page_transition as pt
        host = QWidget()
        host.resize(200, 120)
        host.show()
        layer = pt.PageTransition(host)
        pm = QPixmap(200, 120)
        pm.fill()
        t0 = time.monotonic()
        layer.start(pm, 1)
        self.assertTrue(layer.isVisible())
        _app.processEvents()
        self.assertLess(layer.progress(), 1.0)
        while layer.is_running() and time.monotonic() - t0 < 1.0:
            _app.processEvents()
            time.sleep(0.004)
        elapsed = time.monotonic() - t0
        self.assertFalse(layer.isVisible())
        self.assertGreater(elapsed, 0.15)
        self.assertLess(elapsed, 0.40)
        host.close()

    def test_ease_is_monotonic_and_bounded(self):
        from app.hub.components import page_transition as pt
        vals = [pt.ease_out(i / 20) for i in range(21)]
        self.assertEqual(vals[0], 0.0)
        self.assertEqual(vals[-1], 1.0)
        self.assertEqual(vals, sorted(vals))


if __name__ == "__main__":
    unittest.main()
