"""Seletor de atalho: avisa quando o Windows já usa a combinação e só grava depois do "Substituir"."""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.hub.components import shortcut_picker as sp
from app.services.windows_shortcuts import windows_use

WIN_ALT = Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.AltModifier


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def picker(qapp, monkeypatch):
    state = {"anim": False}
    monkeypatch.setattr(sp, "animations_enabled", lambda: state["anim"])
    p = sp.ShortcutPicker(current_shortcut="Win+Alt+E", default_shortcut="Win+Alt+E")
    p.show()
    QCoreApplication.processEvents()
    got = []
    p.shortcut_changed.connect(got.append)
    p.state, p.got = state, got
    yield p
    p.close()
    p.deleteLater()


def _press(p, key, mods=WIN_ALT):
    p.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods))


def _pump(sec, probe):
    out, end = [], time.time() + sec
    while time.time() < end:
        QCoreApplication.processEvents()
        out.append(probe())
        time.sleep(0.004)
    return out


def test_windows_shortcuts_table():
    assert windows_use("Win+Alt+B")                  # HDR
    assert windows_use("Win+Shift+S")
    assert windows_use("Win+Alt+E") is None          # o padrão novo da bateria está livre
    for free in ("Win+Alt+M", "Win+Alt+T", "Win+Alt+W", "Win+Alt+P", "Win+Alt+S", "Win+Alt+V", "Win+Alt+K"):
        assert windows_use(free) is None, free       # nenhum padrão do app dispara o aviso


def test_shortcut_used_by_windows_waits_for_override(picker):
    picker._start_recording()
    _press(picker, Qt.Key.Key_B)
    assert picker.is_pending() and picker.got == []          # ainda não gravou
    assert picker.fold_warn.is_open() and not picker.fold_hint.is_open()
    assert "HDR" in picker.lbl_warn.text()
    picker.btn_override.click()
    assert picker.got == ["Win+Alt+B"] and not picker.is_pending()
    assert not picker.fold_warn.is_open()


@pytest.mark.parametrize("how", ["button", "escape"])
def test_cancel_discards_the_pending_shortcut(picker, how):
    picker._start_recording()
    _press(picker, Qt.Key.Key_B)
    if how == "button":
        picker.btn_edit.click()
    else:
        _press(picker, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    assert not picker.is_pending() and picker.got == []
    assert picker._current_shortcut == "Win+Alt+E" and not picker.fold_warn.is_open()


def test_free_shortcut_is_saved_right_away(picker):
    picker._start_recording()
    _press(picker, Qt.Key.Key_J)
    assert picker.got == ["Win+Alt+J"] and not picker.is_pending()
    assert not picker.fold_warn.is_open() and not picker.fold_hint.is_open()


def test_rows_animate_together_and_end_clean(picker):
    picker.state["anim"] = True
    picker._start_recording()
    opening = _pump(0.4, lambda: picker.fold_hint.height())
    assert any(0 < h < max(opening) for h in opening)        # a dica abre aos poucos (não no corte)
    assert picker._rows_anim is None and not picker.fold_hint.is_animating()

    _press(picker, Qt.Key.Key_B)                              # dica fecha e aviso abre, na mesma linha do tempo
    assert picker.fold_warn.is_animating()
    total = _pump(0.4, lambda: picker.fold_hint.height() * picker.fold_hint.isVisible()
                  + picker.fold_warn.height() * picker.fold_warn.isVisible())
    assert all(b >= a - 1 for a, b in zip(total, total[1:]))  # só cresce: sem encolher e crescer de novo
    assert picker._rows_anim is None and not picker.fold_warn.is_animating()
    assert picker.fold_warn.isVisible() and picker.fold_hint.isHidden()


def test_without_animations_rows_switch_instantly(picker):
    picker._start_recording()
    assert picker._rows_anim is None and picker.fold_hint.isVisible()
    _press(picker, Qt.Key.Key_B)
    assert picker._rows_anim is None and picker.fold_warn.isVisible() and picker.fold_hint.isHidden()
