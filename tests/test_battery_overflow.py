"""Testes do D-Pad de expansão, overflow entre monitores, proteção contra vazio e aviso em monitor único."""

import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.core import i18n
from app.hub.battery_page import BatteryPage
from app.hub.components.direction_pad import DirectionPad
from app.hub.components.pill_switch import PillSwitch
from app.widgets.battery import layout as lay

_app = QApplication.instance() or QApplication([])


def _click_widget(widget, pos: QPointF):
    for ev_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        ev = QMouseEvent(
            ev_type,
            pos,
            pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton if ev_type == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        if ev_type == QEvent.Type.MouseButtonPress:
            widget.mousePressEvent(ev)
        else:
            widget.mouseReleaseEvent(ev)


class BatteryExpandLayoutTests(unittest.TestCase):
    def test_normalize_axis_and_pivot(self):
        self.assertEqual(lay.normalize_expand("rL"), "lr")
        self.assertEqual(lay.normalize_expand(""), "lrud")
        self.assertEqual(lay.expand_axis("l"), "x")
        self.assertEqual(lay.expand_axis("lr"), "x")
        self.assertEqual(lay.expand_axis("d"), "y")
        self.assertEqual(lay.expand_axis("ud"), "y")
        self.assertEqual(lay.expand_axis("lru"), "both")
        self.assertEqual(lay.expand_axis("lrud"), "both")

        self.assertEqual(lay.expand_pivot("l"), (-1.0, 0.0))
        self.assertEqual(lay.expand_pivot("r"), (0.0, 0.0))
        self.assertEqual(lay.expand_pivot("lr"), (-0.5, 0.0))
        self.assertEqual(lay.expand_pivot("u"), (0.0, -1.0))
        self.assertEqual(lay.expand_pivot("d"), (0.0, 0.0))
        self.assertEqual(lay.expand_pivot("ud"), (0.0, -0.5))
        self.assertEqual(lay.expand_pivot("lru"), (-0.5, -1.0))
        self.assertEqual(lay.expand_pivot("lrud"), (-0.5, -0.5))

    def test_vertical_expand_locks_stack_width(self):
        # 7 dispositivos em 300x262: vertical deve manter largura <= 300 e crescer só na altura
        c, r, d, w, h, grown = lay.solve(7, 300.0, 262.0, expand="d")
        self.assertTrue(grown)
        self.assertEqual(w, 300.0)
        self.assertGreater(h, 262.0)

    def test_horizontal_expand_locks_height(self):
        # 7 dispositivos em 300x262: horizontal deve manter altura em 262 e crescer só na largura
        c, r, d, w, h, grown = lay.solve(7, 300.0, 262.0, expand="l")
        self.assertTrue(grown)
        self.assertEqual(h, 262.0)
        self.assertGreater(w, 300.0)

    def test_reachable_bounds_respects_void_and_adjacent_monitor(self):
        m1 = (0.0, 0.0, 1920.0, 1040.0)      # monitor 1 com barra de tarefas (1040)
        m2 = (1920.0, 0.0, 3840.0, 1040.0)   # monitor 2 à direita
        card = (1600.0, 700.0, 1900.0, 960.0)

        # Overflow desligado: fica preso no monitor 1
        self.assertEqual(lay.reachable_bounds(card, m1, [m1, m2], allow_overflow=False), m1)
        # Overflow ligado com monitor 2 à direita: estende a direita, mas topo/baixo/esquerda continuam no monitor 1
        self.assertEqual(lay.reachable_bounds(card, m1, [m1, m2], allow_overflow=True), (0.0, 0.0, 3840.0, 1040.0))
        # Overflow ligado com 1 monitor só: vazio puro é sempre parede
        self.assertEqual(lay.reachable_bounds(card, m1, [m1], allow_overflow=True), m1)

    def test_clamp_shift_pushes_inward_from_right_and_taskbar(self):
        bounds = (0.0, 0.0, 1920.0, 1040.0)
        # Ultrapassa 80px à direita e 35px abaixo da barra de tarefas
        dx, dy = lay.clamp_shift((1600.0, 800.0, 2000.0, 1075.0), bounds)
        self.assertEqual(dx, -80.0)
        self.assertEqual(dy, -35.0)


class DirectionPadAndHubGuardTests(unittest.TestCase):
    def test_direction_pad_keeps_at_least_one_and_center_toggles_auto(self):
        pad = DirectionPad(directions="l")
        emitted = []
        pad.directions_changed.connect(emitted.append)
        rects = pad._rects()

        # Tentar desligar a única direção ativa ('l') não permite
        _click_widget(pad, rects["l"].center())
        self.assertEqual(pad.directions(), "l")
        self.assertEqual(emitted, [])

        # Ligar 'r' -> 'lr'
        _click_widget(pad, rects["r"].center())
        self.assertEqual(pad.directions(), "lr")

        # Clicar no centro -> Auto ('lrud')
        _click_widget(pad, rects["all"].center())
        self.assertEqual(pad.directions(), "lrud")

    def test_single_screen_overflow_toggle_shakes_and_warns(self):
        page = BatteryPage()
        with mock.patch.object(BatteryPage, "_screen_count", return_value=1), \
             mock.patch.object(PillSwitch, "shake") as mock_shake:
            self.assertFalse(page.sw_overflow.isChecked())
            allowed = page._can_toggle_overflow(True)
            self.assertFalse(allowed)
            mock_shake.assert_called_once()
            self.assertTrue(page.fold_overflow_warn.is_open())

        with mock.patch.object(BatteryPage, "_screen_count", return_value=2):
            self.assertTrue(page._can_toggle_overflow(True))
            self.assertFalse(page.fold_overflow_warn.is_open())

    def test_i18n_keys_exist_in_pt_and_en(self):
        keys = (
            "battery_expand_title",
            "battery_expand_auto",
            "battery_expand_axis_x",
            "battery_expand_axis_y",
            "battery_expand_axis_both",
            "battery_dir_l",
            "battery_dir_r",
            "battery_dir_u",
            "battery_dir_d",
            "battery_overflow_title",
            "battery_overflow_sub",
            "battery_overflow_help",
            "battery_overflow_single_screen",
        )
        for lang in ("pt", "en"):
            for k in keys:
                self.assertIn(k, i18n.TRANSLATIONS[lang], f"Missing {k} in {lang}")
                self.assertTrue(i18n.TRANSLATIONS[lang][k])


class AnchorOverflowGlideTests(unittest.TestCase):
    def test_stack_push_uses_slide_spring_and_restores_without_breaking(self):
        from PySide6.QtCore import QPoint, QRectF
        from PySide6.QtWidgets import QWidget
        from app.core import anchor_geometry as geo
        from app.core.anchor_manager import AnchorManager, Group, card_rect

        class FakeCard(QWidget):
            def __init__(self, key: str, w: int, h: int):
                super().__init__()
                self.ANCHOR_KEY = key
                self.setFixedSize(w, h)
                self._vis = True

            def isVisible(self):
                return self._vis

            def rest_pos(self):
                return self.pos()

            def card_rect(self):
                return QRectF(0, 0, self.width(), self.height())

            def anchor_card_radius(self):
                return 24.0

            def is_scale_animating(self):
                return False

        mgr = AnchorManager()
        weather = FakeCard("weather", 300, 260)
        battery = FakeCard("battery", 300, 260)
        weather.move(1596, 100)   # 24px da borda direita (1920)
        battery.move(1596, 370)   # 10px abaixo do Clima

        mgr._windows["weather"] = weather
        mgr._windows["battery"] = battery
        mgr._sizes["weather"] = (300.0, 260.0)
        mgr._sizes["battery"] = (300.0, 260.0)
        tree = geo.Join("weather", "battery", "y", 0, 0.0, 10.0)
        g = Group(tree)
        mgr._groups["weather"] = g
        mgr._groups["battery"] = g

        bounds = (0.0, 0.0, 1920.0, 1040.0)
        with mock.patch.object(AnchorManager, "_reachable_bounds", return_value=bounds), \
             mock.patch("app.core.anchor_manager.animations_enabled", return_value=True):
            # 1. Battery cresce para 420px com D-pad = Esquerda -> Clima fica 100% parado, Battery desliza via _slide
            battery.setFixedSize(420, 260)
            mgr.member_auto_resized(battery, 300.0, 260.0, (-1.0, 0.0), allow_overflow=False)
            self.assertIsNotNone(mgr._slide)
            self.assertTrue(mgr._slide.get("overflow"))
            self.assertFalse(mgr._slide.get("persist"))
            self.assertAlmostEqual(mgr._slide["goal"]["weather"][0], 1596.0, places=1)
            self.assertAlmostEqual(mgr._slide["goal"]["battery"][0], 1476.0, places=1)

            # 2. Muda D-pad para Direita (ainda com 420px): bate na borda (com folga de 12px) e empurra A PILHA TODA
            mgr.member_auto_resized(battery, 300.0, 260.0, (0.0, 0.0), allow_overflow=False)
            self.assertAlmostEqual(mgr._slide["goal"]["battery"][0], 1488.0, places=1)   # 1920 - 12 - 420
            self.assertAlmostEqual(mgr._slide["goal"]["weather"][0], 1488.0, places=1)   # alinhado com Battery!

            # 3. Mesmo se _overflow_rest for limpo no meio (ex.: re-alinhar), reconstrói o repouso pela árvore sem quebrar
            mgr._finish_slide()
            mgr._overflow_rest.clear()
            mgr.member_auto_resized(battery, 300.0, 260.0, (-1.0, 0.0), allow_overflow=False)
            self.assertAlmostEqual(mgr._slide["goal"]["weather"][0], 1488.0, places=1)
            self.assertAlmostEqual(mgr._slide["goal"]["battery"][0], 1368.0, places=1)   # 1488 - 120

            # 4. Battery encolhe de volta para 300px -> pilha desliza de volta para o repouso
            battery.setFixedSize(300, 260)
            mgr.member_auto_resized(battery, 300.0, 260.0, (-1.0, 0.0), allow_overflow=False)
            self.assertAlmostEqual(mgr._slide["goal"]["weather"][0], 1488.0, places=1)
            self.assertAlmostEqual(mgr._slide["goal"]["battery"][0], 1488.0, places=1)

