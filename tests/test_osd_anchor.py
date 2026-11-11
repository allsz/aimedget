"""
Âncora compartilhada dos flyouts (Caps/Num Lock + Mixer), 8 posições:
- O padrão (bc) continua acima da barra de tarefas, centralizado.
- Embaixo o Caps Lock empilha acima do mixer; em cima, o espelho (mixer no topo, Caps Lock abaixo).
- No meio o par fica centralizado no eixo Y, e o mixer abre espaço quando o Caps Lock chega.
- A borda ancorada do mixer fica parada: a gaveta cresce para longe dela (nada vira de cabeça para baixo).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core import osd_anchor
from app.widgets.keylock_osd import theme as kl_theme
from app.widgets.volume_mixer import theme as mx_theme


def wait_until(condition, timeout_ms: int = 2000) -> bool:
    waited = 0
    while not condition():
        if waited >= timeout_ms:
            return False
        QTest.qWait(10)
        waited += 10
    return True


class AnchorHelpersTests(unittest.TestCase):
    def test_normalize_falls_back_to_bottom_center(self):
        self.assertEqual(osd_anchor.normalize("tl"), "tl")
        for bad in (None, "", "cc", "xx", 3, "BC"):
            self.assertEqual(osd_anchor.normalize(bad), "bc")

    def test_rows_and_columns(self):
        self.assertEqual([osd_anchor.vertical(a) for a in ("tl", "ml", "br")], ["top", "middle", "bottom"])
        self.assertEqual([osd_anchor.horizontal(a) for a in ("bl", "tc", "mr")], ["left", "center", "right"])

    def test_card_x_respects_side_gap_and_art(self):
        avail = QRect(-1920, 0, 1920, 1040)   # monitor à esquerda do primário: coordenadas negativas
        self.assertEqual(osd_anchor.card_left_x("bl", avail, 240), -1920 + osd_anchor.SIDE_GAP_PX)
        self.assertEqual(osd_anchor.card_left_x("bl", avail, 240, art_left=12), -1920 + osd_anchor.SIDE_GAP_PX + 12)
        self.assertEqual(osd_anchor.card_left_x("br", avail, 240), -osd_anchor.SIDE_GAP_PX - 240)
        self.assertEqual(osd_anchor.card_left_x("br", avail, 240, art_right=8), -osd_anchor.SIDE_GAP_PX - 8 - 240)
        self.assertEqual(osd_anchor.card_left_x("tc", avail, 240), -1920 + (1920 - 240) // 2)


class _FlyoutPair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
        from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout

        self.avail = QApplication.primaryScreen().availableGeometry()
        self.caps = KeyLockFlyout()
        self.caps.theme = kl_theme.DEFAULT_THEME
        self.caps._recalculate_size()
        self.mixer = VolumeMixerFlyout()
        self.mixer._apply_theme(mx_theme.DEFAULT_THEME)
        self.stack = osd_anchor.OsdStack(self.caps, self.mixer)

    def tearDown(self):
        self.mixer._anim_timer.stop()
        self.caps._anim_timer.stop()
        self.mixer.hide()
        self.caps.hide()

    def anchor(self, a: str, mixer: str | None = None):
        self.stack.set_anchors(a, mixer or a)

    # --- geometria em coordenadas de tela ---

    def caps_card(self) -> tuple[float, float, float, float]:
        """(esq., topo, dir., base) do card do Caps Lock na posição alvo (sem o deslize de entrada)."""
        ml, mt, _mr, _mb = self.caps._margins
        x = self.caps._get_centered_x() + ml
        top = self.caps._compute_target_win_y() + mt
        h = self.caps.card_h * self.caps._scale
        w = self.caps.card_w * self.caps._scale
        return x, top, x + w, top + h

    def mixer_card(self, card_h: float = 50.0) -> tuple[float, float, float, float]:
        self.mixer._slide_t = 1.0
        self.mixer._anim_card_h = card_h
        r = self.mixer._card_rect()
        return (self.mixer.x() + r.left(), self.mixer.y() + r.top(),
                self.mixer.x() + r.right(), self.mixer.y() + r.bottom())

    def show_mixer(self):
        """Mixer na tela, parado na posição final (sem esperar a animação de entrada)."""
        self.mixer.show()
        self.mixer._slide_t = self.mixer._slide_target_t = 1.0
        self.mixer._notify_card_top()


class DefaultAnchorTests(_FlyoutPair):
    def test_default_is_bottom_center_above_taskbar(self):
        self.assertEqual(self.caps.anchor(), "bc")
        self.assertEqual(self.mixer.anchor(), "bc")
        l, _t, r, b = self.caps_card()
        self.assertAlmostEqual((l + r) / 2, self.avail.x() + self.avail.width() / 2, delta=1.0)
        self.assertAlmostEqual(b, self.avail.bottom() + 1 - self.caps.EDGE_GAP_Y, delta=1.0)
        _l, _t, _r, mb = self.mixer_card()
        self.assertAlmostEqual(mb, self.avail.bottom() + 1 - 26, delta=1.0)   # 12 de folga + 14 de sombra

    def test_bottom_stacking_puts_caps_above_mixer(self):
        self.show_mixer()
        _l, mixer_top, _r, _b = self.mixer_card()
        _l, _t, _r, caps_bottom = self.caps_card()
        self.assertAlmostEqual(caps_bottom, mixer_top - osd_anchor.STACK_GAP_PX, delta=1.0)


class TopAnchorTests(_FlyoutPair):
    def setUp(self):
        super().setUp()
        self.anchor("tc")

    def test_both_hug_the_top_edge(self):
        _l, caps_top, _r, _b = self.caps_card()
        self.assertAlmostEqual(caps_top, self.avail.y() + self.caps.EDGE_GAP_Y, delta=1.0)
        _l, mixer_top, _r, _b = self.mixer_card()
        self.assertAlmostEqual(mixer_top, self.avail.y() + 26, delta=1.0)

    def test_drawer_grows_down_keeping_the_top_still(self):
        _l, top_collapsed, _r, _b = self.mixer_card(50.0)
        self.mixer._apply_window_canvas_size(expanded_canvas=True)
        _l, top_expanded, _r, bottom_expanded = self.mixer_card(260.0)
        self.assertAlmostEqual(top_expanded, top_collapsed, delta=1.0)
        self.assertAlmostEqual(bottom_expanded - top_expanded, 260.0, delta=1.0)
        # e o card inteiro cabe na janela (nada cortado)
        r = self.mixer._card_rect()
        self.assertGreaterEqual(r.top(), 0)
        self.assertLessEqual(r.bottom(), self.mixer.height())

    def test_caps_goes_below_the_mixer(self):
        self.show_mixer()
        _l, _t, _r, mixer_bottom = self.mixer_card()
        _l, caps_top, _r, _b = self.caps_card()
        self.assertAlmostEqual(caps_top, mixer_bottom + osd_anchor.STACK_GAP_PX, delta=1.0)

    def test_caps_follows_the_mixer_drawer_down(self):
        self.show_mixer()
        _l, first_top, _r, _b = self.caps_card()
        self.mixer._apply_window_canvas_size(expanded_canvas=True)
        self.mixer._anim_card_h = 200.0
        self.mixer._notify_card_top()
        _l, caps_top, _r, _b = self.caps_card()
        self.assertAlmostEqual(caps_top - first_top, 150.0, delta=1.0)

    def test_slides_in_from_above(self):
        ml, mt, mr, mb = self.caps._margins
        self.assertGreater(mt, mb)   # a folga do deslize mudou para cima
        self.mixer._slide_t = 0.0
        self.mixer._anim_card_h = 50.0
        hidden_top = self.mixer._card_rect().top()
        self.mixer._slide_t = 1.0
        self.assertLess(hidden_top, self.mixer._card_rect().top())   # começa acima e desce até o lugar

    def test_back_to_bottom_restores_the_original_window(self):
        self.anchor("bc")
        ml, mt, mr, mb = self.caps._margins
        self.assertEqual((mt, mb), (16.0, 12.0 + self.caps.SLIDE_TRAVEL_Y))


class MiddleAnchorTests(_FlyoutPair):
    def setUp(self):
        super().setUp()
        self.anchor("mr")
        self.center_y = self.avail.y() + self.avail.height() / 2

    def test_alone_each_is_vertically_centered(self):
        _l, t, _r, b = self.caps_card()
        self.assertAlmostEqual((t + b) / 2, self.center_y, delta=1.0)
        _l, t, _r, b = self.mixer_card()
        self.assertAlmostEqual((t + b) / 2, self.center_y, delta=1.0)

    def test_right_column_is_center_aligned(self):
        # O mixer encosta na borda; o Caps Lock (mais estreito) fica mais para dentro, alinhado pelo centro
        caps_l, _t, caps_r, _b = self.caps_card()
        mix_l, _t, mix_r, _b = self.mixer_card()
        edge = self.avail.x() + self.avail.width() - osd_anchor.SIDE_GAP_PX
        self.assertAlmostEqual(mix_r, edge, delta=1.0)
        self.assertAlmostEqual((caps_l + caps_r) / 2, (mix_l + mix_r) / 2, delta=1.0)
        self.assertLess(caps_r, edge)

    def test_pair_is_centered_with_caps_above(self):
        self.show_mixer()
        # show_osd relê o tema salvo (pode ter figurinhas): as contas abaixo usam os limites VISUAIS (card + arte)
        self.caps.show_osd("Caps Lock", True)   # o mixer recebe a presença e abre espaço (animado)
        self.assertTrue(wait_until(lambda: self.mixer._stack_offset == self.mixer._stack_offset_target))
        self.assertGreater(self.mixer._stack_offset, 0)
        _l, caps_top, _r, caps_bottom = self.caps_card()
        caps_top -= self.caps._art_top
        caps_bottom += self.caps._art_bottom
        _l, mixer_top, _r, mixer_bottom = self.mixer_card()
        self.assertAlmostEqual(caps_bottom, mixer_top - osd_anchor.STACK_GAP_PX, delta=1.0)
        self.assertAlmostEqual((caps_top + mixer_bottom) / 2, self.center_y, delta=1.5)

    def test_caps_leaving_recenters_the_mixer(self):
        self.show_mixer()
        self.caps.show_osd("Caps Lock", True)
        self.assertTrue(wait_until(lambda: self.mixer._stack_offset == self.mixer._stack_offset_target))
        self.caps._start_fade_out()
        self.assertTrue(wait_until(lambda: self.mixer._stack_offset == 0.0))
        _l, t, _r, b = self.mixer_card()
        self.assertAlmostEqual((t + b) / 2, self.center_y, delta=1.0)

    def test_drawer_grows_both_ways(self):
        self.mixer._apply_window_canvas_size(expanded_canvas=True)
        _l, t, _r, b = self.mixer_card(300.0)
        self.assertAlmostEqual((t + b) / 2, self.center_y, delta=1.0)


class IndependentAnchorsTests(_FlyoutPair):
    def test_different_anchors_never_stack(self):
        self.anchor("tr", mixer="bl")
        self.show_mixer()
        self.assertFalse(self.caps._mixer_active)
        caps_l, caps_t, _r, _b = self.caps_card()
        self.assertAlmostEqual(caps_t, self.avail.y() + self.caps.EDGE_GAP_Y, delta=1.0)   # continua no topo
        mix_l, _t, _r, _b = self.mixer_card()
        self.assertAlmostEqual(mix_l, self.avail.x() + osd_anchor.SIDE_GAP_PX, delta=1.0)

    def test_caps_on_another_anchor_does_not_push_the_mixer(self):
        self.anchor("ml", mixer="mr")
        self.show_mixer()
        self.caps.show_osd("Caps Lock", True)
        self.assertEqual(self.mixer._stack_offset_target, 0.0)

    def test_own_column_when_alone_on_a_side(self):
        self.anchor("bl", mixer="bc")
        caps_l, _t, _r, _b = self.caps_card()
        self.assertAlmostEqual(caps_l, self.avail.x() + osd_anchor.SIDE_GAP_PX + self.caps._art_left, delta=1.0)

    def test_moving_mixer_onto_caps_anchor_stacks_immediately(self):
        self.anchor("tc", mixer="bc")
        self.show_mixer()
        self.assertFalse(self.caps._mixer_active)
        self.anchor("tc")
        self.assertTrue(self.caps._mixer_active)


class MixerHideReleasesCapsTests(_FlyoutPair):
    def test_direct_hide_unstacks_caps(self):
        self.show_mixer()
        self.assertTrue(self.caps._mixer_active)
        self.mixer.hide()   # atalho que alterna o mixer chama hide() direto, sem animação de saída
        self.assertFalse(self.caps._mixer_active)


class PositionPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_eight_positions_and_silent_select(self):
        from app.hub.components.position_picker import PositionPicker

        p = PositionPicker(current_pos="bc", with_middle_row=True)
        self.assertEqual(set(p.positions()), set(osd_anchor.ANCHORS))
        got = []
        p.position_changed.connect(got.append)
        p.select("ml")
        self.assertEqual((p.get_position(), got), ("ml", []))
        p.set_position("tr")
        self.assertEqual(got, ["tr"])

    def test_widgets_keep_six_positions(self):
        from app.hub.components.position_picker import PositionPicker

        self.assertEqual(set(PositionPicker().positions()), {"tl", "tc", "tr", "bl", "bc", "br"})

    def test_click_picks_the_nearest_position(self):
        from PySide6.QtCore import QPoint
        from app.hub.components.position_picker import PositionPicker

        p = PositionPicker(current_pos="bc", with_middle_row=True)
        got = []
        p.position_changed.connect(got.append)
        QTest.mouseClick(p, Qt.MouseButton.LeftButton, pos=QPoint(4, p.height() // 2 - 4))   # meio da borda esquerda
        QTest.mouseClick(p, Qt.MouseButton.LeftButton, pos=QPoint(p.width() - 3, 3))         # canto superior direito
        self.assertEqual(got, ["ml", "tr"])

    def test_pills_stay_inside_the_screen_above_the_taskbar(self):
        from app.hub.components.position_picker import PositionPicker

        p = PositionPicker(with_middle_row=True)
        screen = p._screen_rect()
        for k in p.positions():
            r = p._pill_rect(k)
            self.assertTrue(screen.contains(r), k)
            self.assertLessEqual(r.bottom(), screen.bottom() - p.TASKBAR_H, k)


if __name__ == "__main__":
    unittest.main()
