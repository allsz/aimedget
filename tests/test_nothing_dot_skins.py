"""Testes das skins Nothing Dot para os widgets de Clima e Desempenho."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication

from app.services.performance_service import PerformanceSnapshot
from app.ui_components.dot_matrix import NOTHING_BG, draw_dot_text, draw_dot_weather_icon, measure_dot_text
from app.widgets.performance.card_painter import ND_TRIGGER_RECT, nd_dropdown_rect, paint_performance_card
from app.widgets.performance.card_state import SKIN_FLUENT, SKIN_NOTHING_DOT
from app.widgets.performance.performance_card import PerformanceCard
from app.widgets.performance.specs import init_performance_skin_specs
from app.widgets.weather import font_skins
from app.widgets.weather.card_painter import paint_card
from app.widgets.weather.specs import init_weather_skin_specs, mock_state as mock_weather_state


class TestNothingDotSkins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_dot_matrix_text_and_icons_render(self):
        w, h = measure_dot_text("24°", dot_r=3.0, gap=7.2)
        self.assertGreater(w, 40.0)
        self.assertGreater(h, 30.0)

        img = QImage(160, 80, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        draw_dot_text(p, "24°", QRectF(8, 8, 120, 60), dot_r=3.0, gap=7.2, red_degree=True)
        draw_dot_weather_icon(p, "rain", QRectF(110, 16, 40, 40))
        p.end()
        non_empty = sum(1 for x in range(160) for y in range(80) if img.pixelColor(x, y).alpha() > 0)
        self.assertGreater(non_empty, 100)

    def test_weather_nothing_dot_skin_discovered_and_renders_without_city_red_dot(self):
        ids = [s.id for s in init_weather_skin_specs()]
        self.assertIn(font_skins.DEFAULT_SKIN, ids)
        self.assertIn(font_skins.NOTHING_DOT_SKIN, ids)

        state = mock_weather_state(skin_id=font_skins.NOTHING_DOT_SKIN)
        img = QImage(300, 262, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        paint_card(p, QRectF(0, 0, 300, 262), state, 3.2)
        p.end()

        # Fundo fosco Nothing (#161616) e nenhum ponto vermelho à esquerda da cidade
        self.assertEqual(img.pixelColor(150, 70), NOTHING_BG)
        for x in range(12, 22):
            for y in range(20, 34):
                c = img.pixelColor(x, y)
                self.assertFalse(c.red() > 180 and c.green() < 60, f"ponto vermelho inesperado em ({x},{y})")

    def test_performance_nothing_dot_scroll_and_dropdown(self):
        ids = [s.id for s in init_performance_skin_specs()]
        self.assertEqual(ids, [SKIN_FLUENT, SKIN_NOTHING_DOT])

        card = PerformanceCard(fps_enabled=True, skin_id=SKIN_NOTHING_DOT)
        picked = []
        card.metric_selected.connect(lambda m: (picked.append(m), card.state.select(m, now=card.now())))
        try:
            snap = PerformanceSnapshot(cpu_pct=41.0, cpu_ghz=4.2, gpu_pct=64.0, gpu_name="RTX 4070", ram_pct=52.0)
            for _ in range(20):
                card.state.push(snap)
            card.show()

            # Scroll do mouse alterna entre categorias
            before = card.state.selected
            we = QWheelEvent(
                QPointF(150, 150),
                QPointF(150, 150),
                QPoint(0, 0),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            card.wheelEvent(we)
            self.assertNotEqual(card.state.selected, before)

            # Clicar no gatilho abre o dropdown interno; clicar em um item seleciona e fecha
            self.assertTrue(card._on_card_press(ND_TRIGGER_RECT.center()))
            self.assertTrue(card.state.dropdown_open)

            dd_r = nd_dropdown_rect(len(card.state.visible_metrics()))
            # Primeiro item do dropdown
            first_item = QPointF(dd_r.center().x(), dd_r.y() + 14.0)
            self.assertTrue(card._on_card_press(first_item))
            self.assertFalse(card.state.dropdown_open)
            self.assertEqual(card.state.selected, card.state.visible_metrics()[0])

            # Esc fecha o dropdown aberto
            card.set_dropdown_open(True)
            card.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            self.assertFalse(card.state.dropdown_open)

            # Pintura direta sem erro
            img = QImage(300, 262, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            card.state.dropdown_progress = 1.0
            from app.core.nothing_theme import DEFAULT_NOTHING_THEME   # independe do tema salvo na máquina
            paint_performance_card(p, QRectF(0, 0, 300, 262), card.state, now=card.now(),
                                   nothing_theme=DEFAULT_NOTHING_THEME)
            p.end()
            self.assertEqual(img.pixelColor(280, 20), NOTHING_BG)
        finally:
            card.close()

    def test_weather_and_performance_theme_json_validation_and_crossfade(self):
        import json
        import tempfile
        from unittest import mock
        from app.core import widget_animator
        from app.core.theme_validation import CONTAINERS, validate_theme_folder

        self.assertIn("weather", CONTAINERS)
        self.assertIn("performance", CONTAINERS)

        with tempfile.TemporaryDirectory() as tmp:
            for container in ("weather", "performance"):
                folder = Path(tmp) / container / "cyber"
                folder.mkdir(parents=True)
                (folder / "theme.json").write_text(
                    json.dumps({
                        "name": "Cyber",
                        "card_bg": "#101820",
                        "accent": "#00e5ff",
                        "dot_on": "#e0f7fa",
                        "dot_off": "#223344",
                    }),
                    encoding="utf-8",
                )
                rep = validate_theme_folder(str(folder), container)
                self.assertTrue(rep.ok, f"{container} report errors/issues: {rep.errors} {rep.issues}")
                self.assertIn("card_bg", rep.applied)
                self.assertIn("accent", rep.applied)

        # Crossfade de troca de skin em FloatingCard (PerformanceCard)
        card = PerformanceCard(skin_id=SKIN_FLUENT)
        try:
            card.show()
            with mock.patch.object(widget_animator, "animations_enabled", return_value=True):
                card.begin_skin_crossfade(duration_ms=160)
                self.assertIsNotNone(card._skin_swap_prev)
                card.set_skin(SKIN_NOTHING_DOT)
                img = QImage(card.size(), QImage.Format.Format_ARGB32)
                card.render(img)
                # Avança além da duração: libera pixmap anterior
                self.assertIsNone(card._skin_swap_progress(card._skin_swap_t0 + 1.0))
                self.assertIsNone(card._skin_swap_prev)
        finally:
            card.close()

    def test_fps_detail_without_redundant_prefix_and_animates_to_zero_on_game_close(self):
        from app.services.fps_service import FpsReading
        from app.widgets.performance.card_state import FPS_CLEAR_DUR, PerformanceState

        st = PerformanceState(fps_enabled=True, selected="fps", animated=True)
        for v in (120.0, 130.0, 140.0):
            st.push_fps(FpsReading(fps=v, app_name="Volleyball"), now=10.0)
        self.assertEqual(st.detail_text("fps"), "Volleyball")

        # Jogo fechou: inicia recolhimento suave até zero
        st.push_fps(FpsReading(fps=None), now=20.0)
        self.assertTrue(st.transitions_busy(20.1))
        mid = st.samples("fps", now=20.0 + FPS_CLEAR_DUR * 0.5)
        self.assertEqual(len(mid), 3)
        self.assertTrue(all(0.0 < m < orig for m, orig in zip(mid, (120.0, 130.0, 140.0))))

        # Ao concluir a duração, o gráfico zera e para o relógio
        self.assertEqual(st.samples("fps", now=20.0 + FPS_CLEAR_DUR + 0.05), [])
        self.assertFalse(st.transitions_busy(20.0 + FPS_CLEAR_DUR + 0.05))

    def test_nothing_dot_timer_skin_and_app_accent_theme(self):
        from app.core.theme_loader import APP_ID
        from app.hub.theme import THEME_DARK, with_accent
        from app.ui_components.dot_matrix import NOTHING_RED
        from app.widgets.timer import theme as timer_theme
        from app.widgets.timer.skins import timer_skin_classes
        from app.widgets.timer.skins.nothing_dot_skin import (
            NothingDotTimerSkin,
            _resolve_nothing_colors,
            paint_nothing_dot_timer,
        )
        from app.widgets.timer.skins.skin import TimerState
        from app.widgets.timer.skins.specs import init_timer_skin_specs

        # Skin registrada nas classes e nas specs do Hub
        self.assertIn("nothing_dot", timer_skin_classes())
        self.assertIn("nothing_dot", [s.id for s in init_timer_skin_specs()])

        # Tema embutido "Aimedget" disponível exclusivamente no loader da skin Nothing Dot (não vaza pro Windows Timer)
        ids = [info.id for info in timer_theme.nothing_loader.list_themes()]
        self.assertIn(APP_ID, ids)
        self.assertNotIn(APP_ID, [info.id for info in timer_theme.loader.list_themes()])

        # Padrão usa Nothing Red; tema embutido "Aimedget" acompanha a cor de destaque do app
        custom_hub = with_accent(THEME_DARK, "#33AAFF")
        c_default = _resolve_nothing_colors(custom_hub, timer_theme.DEFAULT_THEME)
        c_app = _resolve_nothing_colors(custom_hub, timer_theme.app_timer_theme())
        self.assertEqual(c_default["accent"].name().lower(), NOTHING_RED.name().lower())
        self.assertEqual(c_app["accent"].name().lower(), custom_hub.accent.lower())

        # Pintura direta (normal, durante pulo 360° ponto-a-ponto e durante pulso do alarme)
        img = QImage(164, 164, QImage.Format.Format_ARGB32)
        for orbit, alarming in ((-1.0, False), (0.45, False), (-1.0, True)):
            img.fill(0)
            p = QPainter(img)
            paint_nothing_dot_timer(
                p,
                QRectF(0, 0, 164, 164),
                TimerState(current_seconds=300.0, is_running=True, is_alarm_pulsing=alarming),
                THEME_DARK,
                art=timer_theme.DEFAULT_THEME,
                orbit_progress=orbit,
                alarm_phase=0.5,
            )
            p.end()

        # Instância da janela NothingDotTimerSkin cria, pinta e dispara órbita de reset sem erro
        skin = NothingDotTimerSkin()
        try:
            skin.set_time_state(180.0, False, "timer")
            skin._start_reset_orbit()
            out = QImage(skin.size(), QImage.Format.Format_ARGB32)
            skin.render(out)
        finally:
            skin.close()


    def test_performance_app_theme_follows_app_background_and_accent(self):
        from app.core.nothing_theme import APP_NOTHING_THEME, DEFAULT_NOTHING_THEME, resolve_nothing_theme
        from app.core.theme_loader import APP_ID, DEFAULT_ID
        from app.hub.theme import THEME_DARK, THEME_LIGHT, with_accent
        from app.widgets.performance import theme as perf_theme
        from app.widgets.performance.specs import mock_state

        # "Aimedget" aparece na galeria, mas o padrão continua o Nothing escuro com vermelho
        ids = [info.id for info in perf_theme.loader.list_themes()]
        self.assertEqual(ids[:2], [DEFAULT_ID, APP_ID])   # Nothing Red (clássico) primeiro, Aimedget depois
        self.assertFalse(perf_theme.loader.app_is_default)
        self.assertEqual(perf_theme.loader.fallback_id(), DEFAULT_ID)
        self.assertIs(perf_theme.loader.theme_for(APP_ID), APP_NOTHING_THEME)

        # O padrão não muda com o app; o "Aimedget" pega fundo de cartão, texto e destaque do app
        for hub in (with_accent(THEME_DARK, "#33AAFF"), with_accent(THEME_LIGHT, "#22BB66")):
            self.assertIs(resolve_nothing_theme(DEFAULT_NOTHING_THEME, hub), DEFAULT_NOTHING_THEME)
            nt = resolve_nothing_theme(APP_NOTHING_THEME, hub)
            self.assertEqual(nt.card_bg.name().lower(), hub.bg.lower())   # off-white do app no modo claro
            self.assertEqual(nt.accent.name().lower(), hub.accent.lower())
            self.assertEqual(nt.dot_on.name().lower(), hub.text.lower())

            # A miniatura pinta com o fundo do app passado pelo Hub
            img = QImage(300, 262, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            paint_performance_card(p, QRectF(0, 0, 300, 262), mock_state(skin_id=SKIN_NOTHING_DOT),
                                   nothing_theme=APP_NOTHING_THEME, hub_theme=hub)
            p.end()
            self.assertEqual(img.pixelColor(150, 200).name().lower(), hub.bg.lower())

        # O widget vivo guarda a aparência do app e relê depois de invalidar
        perf_theme.invalidate_live_hub_theme()
        first = perf_theme.live_hub_theme()
        self.assertIs(perf_theme.live_hub_theme(), first)
        perf_theme.invalidate_live_hub_theme()
        self.assertIsNotNone(perf_theme.live_hub_theme())

    def test_nothing_dot_timer_app_theme_uses_app_background(self):
        from app.core.theme_loader import DEFAULT_ID
        from app.hub.theme import THEME_DARK, THEME_LIGHT, with_accent
        from app.widgets.timer import theme as timer_theme
        from app.widgets.timer.skins.nothing_dot_skin import (
            _card_layout,
            _resolve_nothing_colors,
            paint_nothing_dot_timer,
        )
        from app.widgets.timer.skins.skin import SHADOW_PAD, TimerState

        self.assertEqual(timer_theme.nothing_loader.fallback_id(), DEFAULT_ID)   # Nothing Red segue padrão

        for hub in (with_accent(THEME_DARK, "#33AAFF"), with_accent(THEME_LIGHT, "#22BB66")):
            c_app = _resolve_nothing_colors(hub, timer_theme.app_timer_theme())
            c_def = _resolve_nothing_colors(hub, timer_theme.DEFAULT_THEME)
            self.assertEqual(c_app["card_bg"].name().lower(), hub.bg.lower())
            self.assertEqual(c_app["screen_top"].name().lower(), hub.panel.lower())   # tela branca no claro
            self.assertEqual(c_app["digit_on"].name().lower(), hub.text.lower())
            self.assertEqual(c_app["home_dot"].name().lower(), hub.text.lower())   # visível também no chassi claro
            self.assertEqual(c_def["card_bg"].name().lower(), "#141414")

            img = QImage(164, 164, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            paint_nothing_dot_timer(p, QRectF(0, 0, 164, 164), TimerState(current_seconds=300.0), hub,
                                    art=timer_theme.app_timer_theme())
            p.end()
            # Chassi: o vão entre a tela e os botões, no meio da largura
            card = QRectF(SHADOW_PAD, SHADOW_PAD, 164 - 2 * SHADOW_PAD, 164 - 2 * SHADOW_PAD)
            screen, play, _grille = _card_layout(card)
            y = int((screen.bottom() + play.top()) / 2)
            self.assertEqual(img.pixelColor(82, y).name().lower(), hub.bg.lower())
            self.assertEqual(img.pixelColor(int(screen.left() + 6), int(screen.bottom() - 6)).name().lower(),
                             hub.panel.lower())

    def test_weather_app_theme_follows_app_background_and_accent(self):
        from app.core.nothing_theme import APP_NOTHING_THEME
        from app.core.theme_loader import APP_ID, DEFAULT_ID
        from app.hub.theme import THEME_DARK, THEME_LIGHT, with_accent
        from app.widgets.weather import theme as weather_theme
        from app.widgets.weather.specs import PREVIEW_NOW

        # Nothing Red (clássico) primeiro e padrão; Aimedget logo depois
        ids = [info.id for info in weather_theme.loader.list_themes()]
        self.assertEqual(ids[:2], [DEFAULT_ID, APP_ID])
        self.assertEqual(weather_theme.loader.fallback_id(), DEFAULT_ID)
        self.assertIs(weather_theme.loader.theme_for(APP_ID), APP_NOTHING_THEME)

        for hub in (with_accent(THEME_DARK, "#33AAFF"), with_accent(THEME_LIGHT, "#22BB66")):
            img = QImage(300, 262, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            paint_card(p, QRectF(0, 0, 300, 262), mock_weather_state(skin_id=font_skins.NOTHING_DOT_SKIN),
                       PREVIEW_NOW, nothing_theme=APP_NOTHING_THEME, hub_theme=hub)
            p.end()
            # Fundo do app num canto livre do cartão
            self.assertEqual(img.pixelColor(150, 8).name().lower(), hub.bg.lower())
            # Algum ponto no tom do texto do app (ícones e temperatura legíveis também no claro)
            text = QColor(hub.text)
            found = any(
                abs(img.pixelColor(x, y).red() - text.red()) < 24 and abs(img.pixelColor(x, y).lightness() - text.lightness()) < 24
                for x in range(0, 300, 2) for y in range(40, 200, 2)
            )
            self.assertTrue(found)

    def test_dot_weather_icon_color(self):
        img = QImage(40, 40, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        draw_dot_weather_icon(p, "clear", QRectF(0, 0, 40, 40), color=QColor("#1F1E1D"))
        p.end()
        colors = {img.pixelColor(x, y).name() for x in range(40) for y in range(40) if img.pixelColor(x, y).alpha() == 255}
        self.assertIn("#1f1e1d", colors)
        self.assertNotIn("#ffffff", colors)

if __name__ == "__main__":
    unittest.main()
