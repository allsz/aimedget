"""Cor de destaque personalizável: matiz, cor digitada (hex/rgb), contraste, persistência, ícone e Hub."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.hub import hub_icon
from app.hub.components.hue_slider import HueSlider
from app.hub.theme import (
    THEME_DARK, THEME_LIGHT, THEME_TRUE_DARK, contrast_ratio, derive_accent, fit_accent, hue_of, parse_color,
    resolve_theme, with_accent,
)


class TestAccentDerivation(unittest.TestCase):
    def test_default_keeps_the_brand_palette_untouched(self):
        for theme in (THEME_LIGHT, THEME_DARK, THEME_TRUE_DARK):
            self.assertIs(with_accent(theme, None), theme)

    def test_every_hue_is_legible_in_both_modes(self):
        for hue in range(360):
            for is_dark in (True, False):
                accent, hover, ink = derive_accent(hue, is_dark)
                self.assertGreaterEqual(contrast_ratio(accent, ink), 4.5, (hue, is_dark))
                self.assertNotEqual(accent, hover)
            self.assertGreaterEqual(contrast_ratio(derive_accent(hue, False)[0], "#FFFFFF"), 3.0, hue)

    def test_with_accent_changes_only_the_accent_tokens(self):
        themed = with_accent(THEME_DARK, 220)
        self.assertNotEqual(themed.accent, THEME_DARK.accent)
        self.assertEqual((themed.bg, themed.panel, themed.text), (THEME_DARK.bg, THEME_DARK.panel, THEME_DARK.text))

    def test_resolve_theme_uses_explicit_accent_and_none_means_default(self):
        self.assertEqual(resolve_theme("dark", 220).accent, with_accent(THEME_DARK, 220).accent)
        self.assertEqual(resolve_theme("dark", "#1E90FF").accent, with_accent(THEME_DARK, "#1E90FF").accent)
        self.assertEqual(resolve_theme("dark", None).accent, THEME_DARK.accent)

    def test_resolve_theme_reads_the_saved_accent(self):
        with mock.patch.object(config_manager, "get_hub_accent", return_value=120):
            self.assertEqual(resolve_theme("light").accent, with_accent(THEME_LIGHT, 120).accent)
        with mock.patch.object(config_manager, "get_hub_accent", return_value="#1E90FF"):
            self.assertEqual(resolve_theme("dark").accent, with_accent(THEME_DARK, "#1E90FF").accent)


class TestTypedColor(unittest.TestCase):
    def test_accepted_formats(self):
        for text, expected in {
            "#FFA13D": "#FFA13D", "ffa13d": "#FFA13D", "  #ffa13d ": "#FFA13D", "#FA3": "#FFAA33",
            "#FFA13D80": "#FFA13D",                      # alfa ignorado
            "rgb(255, 161, 61)": "#FFA13D", "RGB(255 161 61)": "#FFA13D", "rgba(255,161,61,0.5)": "#FFA13D",
            "rgba(255, 161, 61, 50%)": "#FFA13D",
        }.items():
            self.assertEqual(parse_color(text), expected, text)

    def test_rejected_text(self):
        for text in ("", "   ", "laranja", "#GGGGGG", "#12345", "rgb(300, 0, 0)", "rgb(1, 2)", "#FFA13D12345"):
            self.assertIsNone(parse_color(text), text)

    def test_legible_color_is_used_as_typed(self):
        accent, _, _ = fit_accent("#1E90FF", True)
        self.assertEqual(accent, "#1E90FF")
        accent, _, _ = fit_accent("#B0431F", False)
        self.assertEqual(accent, "#B0431F")

    def test_unreadable_colors_are_adjusted_just_enough(self):
        for color, is_dark in (("#202020", True), ("#000000", True), ("#FFFFFF", False), ("#FFFF00", False)):
            accent, hover, ink = fit_accent(color, is_dark)
            panel = "#202020" if is_dark else "#FFFFFF"
            self.assertGreaterEqual(contrast_ratio(accent, panel), 3.0, (color, is_dark))
            self.assertGreaterEqual(contrast_ratio(accent, ink), 4.5, (color, is_dark))
            self.assertNotEqual(accent, color.upper())

    def test_hue_of_matches_the_color(self):
        self.assertEqual(hue_of("#FF0000"), 0)
        self.assertAlmostEqual(hue_of("#0000FF"), 240, delta=1)


class TestAccentConfig(unittest.TestCase):
    def test_round_trip_for_hue_color_and_reset(self):
        hub = config_manager._data.setdefault("hub", {})
        saved = {k: hub.get(k) for k in ("accent_hue", "accent_color")}
        try:
            with mock.patch.object(config_manager, "_save"):
                config_manager.set_hub_accent(200)
                self.assertEqual(config_manager.get_hub_accent(), 200)
                config_manager.set_hub_accent("#1e90ff")
                self.assertEqual(config_manager.get_hub_accent(), "#1E90FF")
                self.assertNotIn("accent_hue", config_manager._data["hub"])   # só um dos dois fica salvo
                config_manager.set_hub_accent(None)
                self.assertIsNone(config_manager.get_hub_accent())
                config_manager._data["hub"]["accent_color"] = "lixo"
                self.assertIsNone(config_manager.get_hub_accent())
        finally:
            for key, value in saved.items():
                if value is None:
                    config_manager._data["hub"].pop(key, None)
                else:
                    config_manager._data["hub"][key] = value


class TestAccentUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def tearDown(self):
        hub_icon.set_icon_accent(None)

    def test_icon_follows_the_hue_the_exact_color_and_resets(self):
        with mock.patch.object(config_manager, "get_hub_accent", return_value=None):
            hub_icon.set_icon_accent(None)
            default = hub_icon.create_aimedget_icon().pixmap(64, 64).toImage()
            hub_icon.set_icon_accent(220)
            blue = hub_icon.create_aimedget_icon().pixmap(64, 64).toImage()
            hub_icon.set_icon_accent("#1E90FF")
            exact = hub_icon.create_aimedget_icon().pixmap(64, 64).toImage()
            self.assertNotEqual(default, blue)
            self.assertNotEqual(blue, exact)
            hub_icon.set_icon_accent(None)
            self.assertEqual(hub_icon.create_aimedget_icon().pixmap(64, 64).toImage(), default)

    def test_slider_signals_and_keyboard(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        slider = HueSlider(hue=10)
        live, done = [], []
        slider.hueChanged.connect(live.append)
        slider.hueCommitted.connect(done.append)
        slider.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier))
        self.assertEqual((slider.hue(), live, done), (20, [20], [20]))
        slider.set_hue(300)   # programático: não emite
        self.assertEqual((live, done), ([20], [20]))

    def test_entry_row_slides_the_field_and_reveals_reset(self):
        from PySide6.QtWidgets import QLineEdit, QPushButton
        from app.hub.components.accent_entry import AccentEntryRow
        field, reset = QLineEdit(), QPushButton("Restaurar")
        field.setFixedWidth(112)
        row = AccentEntryRow(field, reset, inset=12, shown=False)
        row.resize(272, row.height())
        row.show()
        self.assertEqual(field.x(), 272 - 12 - 112)          # sozinho, encostado à direita da trilha
        self.assertFalse(reset.isVisibleTo(row))

        row.set_reset_shown(True, animated=False)
        self.assertEqual(field.x(), 12)                       # à esquerda
        self.assertEqual(reset.geometry().right() + 1, 272 - 12)
        self.assertTrue(reset.isVisibleTo(row) and reset.isEnabled())

        # Interromper no meio da animação parte do quadro atual (sem salto)
        row.set_reset_shown(False)
        row._anim.setCurrentTime(80)
        mid = row._progress
        self.assertTrue(0.0 < mid < 1.0)
        row.set_reset_shown(True)
        self.assertAlmostEqual(row._anim.startValue(), mid)
        row._anim.stop()
        row.hide()

    def test_heavy_work_waits_for_the_animation_to_finish(self):
        from PySide6.QtWidgets import QLineEdit, QPushButton
        from app.hub.components.accent_entry import AccentEntryRow
        row = AccentEntryRow(QLineEdit(), QPushButton("Restaurar"), inset=12, shown=False)
        row.resize(272, row.height())
        row.show()
        ran = []
        row.when_idle(lambda: ran.append("parado"))          # sem animação: roda já
        self.assertEqual(ran, ["parado"])

        row.set_reset_shown(True)                            # animando
        self.assertTrue(row.is_animating())
        job = lambda: ran.append("adiado")
        row.when_idle(job)
        row.when_idle(job)                                   # o mesmo pedido não se repete
        self.assertEqual(ran, ["parado"])
        row._anim.setCurrentTime(row._anim.duration())       # fim do movimento
        self.assertEqual(ran, ["parado", "adiado"])
        row.hide()

    def test_hub_applies_the_accent_and_typed_color_flow(self):
        from app.hub.hub_window import AimedgetHubWindow
        with mock.patch.object(config_manager, "get_hub_accent", return_value=None), \
                mock.patch.object(config_manager, "set_hub_accent") as save:
            hub = AimedgetHubWindow()
            try:
                hub._change_accent(220, True)
                save.assert_called_with(220)
                self.assertEqual(hub._current_theme.accent, resolve_theme(hub._theme_preference, 220).accent)

                page = hub.page_gen
                page.accent_edit.setText("rgb(30, 144, 255)")
                page._accent_text_committed()
                save.assert_called_with("#1E90FF")
                self.assertEqual(hub._current_theme.accent, resolve_theme(hub._theme_preference, "#1E90FF").accent)
                self.assertEqual(page.accent_edit.text(), "#1E90FF")
                self.assertEqual(page.hue_slider.hue(), hue_of("#1E90FF"))
                self.assertTrue(page.accent_entry.reset_shown())
                self.assertTrue(page.btn_accent_reset.isEnabled())

                # Enter com texto inválido (campo com foco): avisa e não muda nada
                with mock.patch.object(page.accent_edit, "hasFocus", return_value=True):
                    page.accent_edit.setText("laranja")
                    page._accent_text_committed()
                    self.assertTrue(page._accent_invalid)
                    self.assertEqual(page.accent_edit.text(), "laranja")
                    self.assertEqual(hub._current_theme.accent, resolve_theme(hub._theme_preference, "#1E90FF").accent)
                    page._accent_text_edited("laranja!")   # voltar a digitar limpa o aviso
                    self.assertFalse(page._accent_invalid)
                # Sair do campo com texto inválido: volta para a cor em uso
                page.accent_edit.setText("laranja")
                page._accent_text_committed()
                self.assertEqual(page.accent_edit.text(), "#1E90FF")
                self.assertFalse(page._accent_invalid)

                page._reset_accent()
                save.assert_called_with(None)
                self.assertEqual(hub._current_theme.accent, resolve_theme(hub._theme_preference, None).accent)
                self.assertFalse(page.accent_entry.reset_shown())
                self.assertFalse(page.btn_accent_reset.isEnabled())   # some: deixa de ser clicável na hora
            finally:
                hub.close()


if __name__ == "__main__":
    unittest.main()
