"""
Mede o custo de arrastar o slider "Distância da borda" com o flyout do Caps Lock acompanhando ao vivo.

Abre o flyout de verdade na tela (por ~alguns segundos), simula um arraste 0 -> 120 -> 0 px e cronometra cada quadro:
  - "chamada": só preview_edge_offset (cálculo + move() da janela translúcida);
  - "quadro":  chamada + processEvents (inclui o repaint/atualização da janela em camadas que o move() dispara).
Compara com a versão sem o atalho "só move quando o pixel muda" e com o orçamento por quadro a 60/144/240 Hz.

Não grava nada na config. Uso:
  .venv\\Scripts\\python.exe tools\\bench_keylock_live_offset.py [--frames 600] [--anchor bc] [--theme-default]
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication


def percentile(data, q):
    s = sorted(data)
    if not s:
        return 0.0
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def sweep(frames):
    """Valores de um arraste ida e volta, com quadros fracionários como os da mola."""
    half = frames // 2
    up = [120.0 * i / half for i in range(half)]
    return up + [120.0 - v for v in up]


def run(fly, app, values, skip_same_pixel=True):
    calls, framed = [], []
    moves = 0
    real_move = fly.move

    def counting_move(*a):
        nonlocal moves
        moves += 1
        real_move(*a)

    fly.move = counting_move
    try:
        if not skip_same_pixel:   # linha de base: move() a cada quadro, mesmo sem mudar de pixel
            def always_move(px, _f=fly):
                _f._edge_offset = max(0.0, min(120.0, float(px)))
                _f._target_win_y = _f._current_win_y = _f._compute_target_win_y()
                _f.move(_f._get_centered_x(), int(round(_f._current_win_y)))
            preview = always_move
        else:
            preview = fly.preview_edge_offset
        for v in values:
            t0 = time.perf_counter()
            preview(v)
            t1 = time.perf_counter()
            app.processEvents()
            t2 = time.perf_counter()
            calls.append((t1 - t0) * 1000.0)
            framed.append((t2 - t0) * 1000.0)
    finally:
        del fly.move   # volta ao método da classe
    return calls, framed, moves


def report(title, calls, framed, moves, n):
    print(f"\n== {title} ==")
    print(f"quadros: {n}   move() de verdade: {moves} ({moves / n:.0%} dos quadros)")
    for name, data in (("chamada", calls), ("quadro ", framed)):
        print(f"  {name}  média {statistics.fmean(data):6.3f} ms   p50 {percentile(data, .5):6.3f}   "
              f"p95 {percentile(data, .95):6.3f}   p99 {percentile(data, .99):6.3f}   máx {max(data):6.3f}")
    p95 = percentile(framed, .95)
    for hz in (60, 144, 240):
        budget = 1000.0 / hz
        over = sum(1 for d in framed if d > budget)
        print(f"  {hz:3d} Hz (orçamento {budget:5.2f} ms): p95 usa {p95 / budget:6.1%}   "
              f"quadros acima do orçamento: {over} ({over / n:.1%})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=int, default=600, help="quadros por passada (padrão 600)")
    ap.add_argument("--anchor", default="bc", help="âncora do flyout (bc, bl, tc, ml, ...)")
    ap.add_argument("--theme-default", action="store_true", help="usa o tema padrão em vez do tema do usuário")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    from app.core.typography import init_app_font
    from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
    from app.widgets.keylock_osd.theme import DEFAULT_THEME
    init_app_font()

    fly = KeyLockFlyout()
    fly.set_anchor(args.anchor, force=True)
    fly.begin_live_adjust()
    if args.theme_default:
        fly.theme = DEFAULT_THEME
        fly._recalculate_size()
    # deixa a entrada terminar para medir só o arraste
    end = time.perf_counter() + 0.5
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.004)

    w, h = fly.width(), fly.height()
    print(f"Janela do flyout: {w}x{h} px   tela: {fly.screen().name()} @ {fly.screen().refreshRate():.0f} Hz   "
          f"âncora: {args.anchor}")

    values = sweep(args.frames)
    run(fly, app, values[:60])   # aquece
    report("ao vivo (como no app: só move quando o pixel muda)", *run(fly, app, values), len(values))
    report("linha de base (move a cada quadro)", *run(fly, app, values, skip_same_pixel=False), len(values))

    fly.end_live_adjust()
    end = time.perf_counter() + 0.4
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.004)
    fly.deleteLater()


if __name__ == "__main__":
    main()
