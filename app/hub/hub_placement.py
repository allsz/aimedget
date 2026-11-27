"""
Posição do Hub ao abrir: garante que a janela apareça numa tela que existe AGORA.

A geometria salva pode apontar para um monitor que saiu (desligado, desconectado, rearranjado no Windows). Sem esta
checagem o Hub abria fora de todas as telas: o ícone ficava na barra de tarefas e nada aparecia (hotfix da 1.1.3).

Regra: a faixa da barra de título precisa ter um pedaço "pegável" dentro da área útil de alguma tela. Se não tiver,
o Hub volta centralizado na tela principal, encolhido se não couber.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

RectT = Tuple[int, int, int, int]   # x, y, w, h

TITLE_STRIP_H = 32        # altura da faixa da barra de título que precisa ficar visível
MIN_GRAB_W = 160          # largura mínima dessa faixa dentro de uma tela para dar para arrastar a janela


def _intersect(a: RectT, b: RectT) -> RectT:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return (x1, y1, max(0, x2 - x1), max(0, y2 - y1))


def is_reachable(rect: RectT, screens: Iterable[RectT]) -> bool:
    """True se a barra de título de `rect` tem um pedaço pegável dentro de alguma das áreas `screens`."""
    x, y, w, _h = rect
    strip = (x, y, w, TITLE_STRIP_H)
    for s in screens:
        ix = _intersect(strip, s)
        if ix[2] >= min(MIN_GRAB_W, w) and ix[3] >= TITLE_STRIP_H // 2:
            return True
    return False


def centered_in(screen: RectT, w: int, h: int) -> RectT:
    """`w`×`h` centralizado em `screen`, encolhido para caber."""
    sx, sy, sw, sh = screen
    w, h = min(w, sw), min(h, sh)
    return (sx + (sw - w) // 2, sy + (sh - h) // 2, w, h)


def fit_to_screens(rect: RectT, screens: list[RectT], primary: Optional[RectT]) -> RectT:
    """Devolve `rect` se já está alcançável; senão, o mesmo tamanho centralizado na tela principal."""
    if not screens or is_reachable(rect, screens):
        return rect
    target = primary or screens[0]
    return centered_in(target, rect[2], rect[3])


def current_screens() -> tuple[list[RectT], Optional[RectT]]:
    """Áreas úteis (sem a barra de tarefas) das telas conectadas e a da tela principal."""
    from PySide6.QtGui import QGuiApplication

    def r(q) -> RectT:
        return (q.x(), q.y(), q.width(), q.height())

    screens = [r(s.availableGeometry()) for s in QGuiApplication.screens()]
    primary = QGuiApplication.primaryScreen()
    return screens, (r(primary.availableGeometry()) if primary else None)
