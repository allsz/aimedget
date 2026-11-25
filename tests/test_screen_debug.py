"""Diagnóstico de troca de monitores: desligado não grava nada; ligado registra telas, widgets e mensagens nativas."""
import ctypes
from ctypes import wintypes

import pytest
from PySide6.QtWidgets import QApplication

from app.core import screen_debug as sd
from test_anchor import env, qapp  # noqa: F401  (fixtures)


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "screen_debug.log"
    monkeypatch.setattr(sd, "_path", lambda: str(path))
    monkeypatch.setattr(sd, "_file", None)
    monkeypatch.setattr(sd, "_burst_until", 0.0)
    monkeypatch.setattr(sd, "_last_widgets", {})
    sd._buffer.clear()
    yield path
    if sd._file is not None:
        sd._file.close()
        sd._file = None


def _pos_msg(card, x, y):
    wp = sd.WINDOWPOS(int(card.winId()), None, x, y, 300, 200, 0x4)
    msg = wintypes.MSG(int(card.winId()), sd.WM_WINDOWPOSCHANGING, 0, ctypes.addressof(wp))
    return msg, wp


def test_disabled_writes_nothing(env, log_file, monkeypatch):
    monkeypatch.delenv(sd.ENV, raising=False)
    card = env.make("weather", 100, 100)
    msg, _wp = _pos_msg(card, 1, 2)
    sd.native(card, ctypes.addressof(msg))
    sd.screen_event("primaryScreenChanged")
    assert not log_file.exists()


def test_enabled_logs_screens_widgets_and_buffered_moves(env, log_file, monkeypatch):
    monkeypatch.setenv(sd.ENV, "1")
    card = env.make("weather", 100, 100)
    msg, _wp = _pos_msg(card, 11, 22)
    sd.native(card, ctypes.addressof(msg))          # antes da troca: fica no buffer
    assert not log_file.exists()

    sd.screen_event("primaryScreenChanged -> 'TV'")
    msg2, _wp2 = _pos_msg(card, 33, 44)
    sd.native(card, ctypes.addressof(msg2))         # durante a janela de observação: direto no arquivo
    card.move_card_to(260, 240)                     # um movimento de verdade, feito pelo app
    QApplication.processEvents()
    text = log_file.read_text(encoding="utf-8")

    assert "BUFFER" in text and "x=11 y=22" in text
    assert "x=33 y=44" in text and "origem=FORA" in text  # sem arquivos do app na pilha (este teste)
    assert "origem=APP" in text and "floating_card.py" in text
    assert "primaryScreenChanged -> 'TV'" in text
    assert "SCREENS" in text and "PRIMARY" in text
    assert "[weather]" in text or "  weather" in text
