"""
ScreenWatcher - cada widget fica no monitor em que você o pôs, como uma skin do Rainmeter (`WindowX=310@1`).

O que o diagnóstico mostrou (crash_reports/screen_debug.log, troca de monitor principal):
- O Windows NÃO move as janelas quando a tela principal muda: a janela fica com os mesmos números, mas a origem
  (0, 0) passou para o canto da nova principal, então os mesmos números caem em outro monitor (o "pulo para a TV").
- O Qt continua achando que cada janela está na tela antiga (escala antiga) até ela se mexer: só então o Windows manda
  WM_DPICHANGED, o Qt muda o tamanho, e cada widget se atualiza num momento diferente. As coordenadas do Qt ficam
  erradas nesse meio tempo (400 px de diferença), e um grupo arrastado assim se desmancha.
- Os nomes dos monitores (\\\\.\\DISPLAY1, ...) não mudam entre as trocas.

Como resolve (o mesmo que o Rainmeter faz em Skin::OnDelayedMove)
- O lugar de cada widget é guardado por MONITOR: nome do dispositivo + distância do canto dele ao canto do cartão, em
  px físicos (`Placement`, gravado em settings.json). Só muda quando o lugar é escolhido (arrastar, quadrante no Hub,
  alinhar, um grupo que se refaz) e nunca enquanto o widget está num lugar provisório porque o monitor dele sumiu.
- Logo que o Qt avisa da mudança (o Windows já tem os monitores novos nesse instante), cada widget volta ao lugar no
  monitor dele, em px físicos do Windows, sem passar pelas coordenadas do Qt (que estão velhas). A janela nunca sai
  do monitor dela, então não muda de escala nem de tamanho. Volta na hora, sem animação: o certo é parecer que nada
  aconteceu.
- Enquanto a troca não assenta (SETTLE_MS sem novas mudanças), arrastes e refazer grupos ficam parados, para nada
  ser calculado com coordenadas velhas. Ao assentar: o lugar é reaplicado e quem tem o monitor ausente (ou nunca teve
  lugar e está fora das telas) vai para a tela principal, dentro da área útil, com os grupos de volta à fileira e
  movimento (desliza, ou surge de novo se estava fora das telas). Quando o monitor volta, o widget volta para ele.

Diagnóstico: AIMEDGET_SCREEN_DEBUG=1 registra tudo com a correção ligada; =observe só registra (ver screen_debug.py).
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer

from app.core.anchor_geometry import Rect

logger = logging.getLogger(__name__)

SETTLE_MS = 1200   # sem novas mudanças de tela por esse tempo = a configuração assentou
MIN_VISIBLE = 50   # px: menos que isso de um cartão dentro de uma tela conta como "fora da tela"
ADOPT_DELAY_MS = 600   # widget sem lugar guardado: grava depois de terminar de surgir (o surgir desloca a janela)


def _remembers(key: str) -> bool:
    """O widget está com "Lembrar posição" ligado? Desligado, ele abre no lugar padrão, como sempre."""
    from app.core.config_manager import config_manager

    try:
        if key == "music":
            return config_manager.is_music_position_remembered()
        if key == "timer":
            return config_manager.is_timer_position_remembered()
        return bool(getattr(config_manager, f"get_{key}")("remember_position", False))
    except Exception:
        return False


# --- Monitores do Windows (px físicos) ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Monitor:
    device: str       # \\.\DISPLAYn (estável entre trocas de principal)
    rect: Rect        # retângulo do monitor na área de trabalho
    work: Rect        # área útil
    scale: float      # DPI / 96
    primary: bool = False


@dataclass(frozen=True)
class Placement:
    """Onde o cartão fica: `dx, dy` px físicos do canto do monitor `screen` até o canto do cartão."""
    screen: str
    dx: int
    dy: int
    scale: float = 1.0   # escala do monitor ao gravar (para o lugar provisório na principal)

    def to_json(self) -> dict:
        return {"screen": self.screen, "dx": self.dx, "dy": self.dy, "scale": round(self.scale, 3)}

    @staticmethod
    def from_json(data) -> Optional["Placement"]:
        try:
            return Placement(str(data["screen"]), int(data["dx"]), int(data["dy"]), float(data.get("scale", 1.0)))
        except (KeyError, TypeError, ValueError):
            return None


def _overlap(a: Rect, b: Rect) -> float:
    w = min(a.r, b.r) - max(a.l, b.l)
    h = min(a.b, b.b) - max(a.t, b.t)
    return w * h if w > 0 and h > 0 else 0.0


def monitor_of(rect: Rect, monitors: List[Monitor]) -> Optional[Monitor]:
    """O monitor com a maior parte do retângulo (None se ele está fora de todos)."""
    best, area = None, 0.0
    for m in monitors:
        a = _overlap(rect, m.rect)
        if a > area:
            best, area = m, a
    return best


def placement_of(card: Rect, monitors: List[Monitor]) -> Optional[Placement]:
    m = monitor_of(card, monitors)
    if m is None:
        return None
    return Placement(m.device, int(round(card.l - m.rect.l)), int(round(card.t - m.rect.t)), m.scale)


def resolve(p: Placement, monitors: List[Monitor]) -> Optional[Tuple[Monitor, int, int]]:
    """Canto do cartão (px físicos) no monitor dele, ou None se o monitor não está conectado."""
    m = next((m for m in monitors if m.device == p.screen), None)
    if m is None:
        return None
    return m, int(m.rect.l + p.dx), int(m.rect.t + p.dy)


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def _r(rc) -> Rect:
    return Rect(float(rc.left), float(rc.top), float(rc.right), float(rc.bottom))


def native_monitors() -> List[Monitor]:
    if sys.platform != "win32":
        return []
    out = []
    user32 = ctypes.windll.user32
    try:
        shcore = ctypes.windll.shcore
    except OSError:
        shcore = None
    proc_t = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                wintypes.LPARAM)

    def cb(hmon, _hdc, _rc, _lp):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return 1
        scale = 1.0
        if shcore is not None:
            dx, dy = ctypes.c_uint(), ctypes.c_uint()
            if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
                scale = dx.value / 96.0
        out.append(Monitor(info.szDevice, _r(info.rcMonitor), _r(info.rcWork), scale, bool(info.dwFlags & 1)))
        return 1

    user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    return out


# --- Telas do Qt (coordenadas lógicas): o resgate e o "caber na tela" -------------------------------------------


@dataclass(frozen=True)
class ScreenInfo:
    id: str
    geo: Rect
    avail: Rect
    primary: bool = False


def is_on_screens(rect: Rect, screens: List[ScreenInfo]) -> bool:
    """Um pedaço utilizável do cartão está em alguma tela?"""
    for s in screens:
        w = min(rect.r, s.geo.r) - max(rect.l, s.geo.l)
        h = min(rect.b, s.geo.b) - max(rect.t, s.geo.t)
        if w > 0 and h > 0 and w >= min(rect.w, MIN_VISIBLE) and h >= min(rect.h, MIN_VISIBLE):
            return True
    return False


def _nearest(box: Rect, screens: List[ScreenInfo]) -> Optional[ScreenInfo]:
    best, area = None, 0.0
    for s in screens:
        a = _overlap(box, s.geo)
        if a > area:
            best, area = s, a
    if best is not None:
        return best
    cx, cy = (box.l + box.r) / 2, (box.t + box.b) / 2

    def dist(sc: ScreenInfo) -> float:
        dx = max(sc.geo.l - cx, 0.0, cx - sc.geo.r)
        dy = max(sc.geo.t - cy, 0.0, cy - sc.geo.b)
        return dx * dx + dy * dy

    return min(screens, key=dist) if screens else None


def fit_shift(box: Rect, screens: List[ScreenInfo]) -> Tuple[float, float]:
    """Deslocamento que põe `box` inteiro na área útil da tela dele (ou da mais perto). Maior que a área: canto."""
    s = _nearest(box, screens)
    if s is None:
        return 0.0, 0.0
    a = s.avail

    def axis(lo, hi, alo, ahi):
        if hi - lo > ahi - alo:
            return alo - lo
        return max(0.0, alo - lo) - max(0.0, hi - ahi)

    return axis(box.l, box.r, a.l, a.r), axis(box.t, box.b, a.t, a.b)


def _qrect(q) -> Rect:
    return Rect.of(q.x(), q.y(), q.width(), q.height())


def current_screens() -> List[ScreenInfo]:
    from PySide6.QtGui import QGuiApplication

    primary = QGuiApplication.primaryScreen()
    return [ScreenInfo(s.name(), _qrect(s.geometry()), _qrect(s.availableGeometry()), s is primary)
            for s in QGuiApplication.screens()]


# --- Janelas em px físicos ----------------------------------------------------------------------------------------


def card_native(w, monitors: List[Monitor]) -> Optional[Rect]:
    """Retângulo do cartão em px físicos, lido do Windows (o Qt pode estar com a escala velha)."""
    from app.core import desktop_layer
    from app.core.anchor_manager import _local_card

    pos = desktop_layer.native_window_rect(int(w.winId()))
    if pos is None:
        return None
    local = _local_card(w)
    probe = Rect.of(pos[0], pos[1], max(1.0, local.right()), max(1.0, local.bottom()))
    m = monitor_of(probe, monitors)
    scale = m.scale if m is not None else w.devicePixelRatioF()
    return Rect.of(pos[0] + round(local.x() * scale), pos[1] + round(local.y() * scale),
                   local.width() * scale, local.height() * scale)


def move_native(items: Iterable[Tuple[object, int, int, float]]):
    """Põe o canto do cartão de cada janela em (x, y) px físicos, todas num lote só do Windows."""
    from app.core import desktop_layer
    from app.core.anchor_manager import _local_card

    moves = []
    for w, x, y, scale in items:
        glide = getattr(w, "_position_glide", None)
        if glide is not None:
            glide.stop(settle=True)
        animator = getattr(w, "animator", None)
        if animator is not None:
            animator.settle()          # a posição de repouso passa a ser a real; o surgir/sumir não a desfaz
        local = _local_card(w)
        moves.append((int(w.winId()), x - round(local.x() * scale), y - round(local.y() * scale)))
    if moves and not desktop_layer.defer_move(moves):
        for move in moves:
            desktop_layer.defer_move([move])


# --- WM_DISPLAYCHANGE (chega a cada widget logo depois do sinal do Qt) ---

WM_DISPLAYCHANGE = 0x007E


def native_event(message):
    """Chamada no nativeEvent dos widgets: um WM_DISPLAYCHANGE dispara a volta ao monitor na hora."""
    try:
        msg = wintypes.MSG.from_address(int(message))
    except (TypeError, ValueError, OSError):
        return
    if msg.message != WM_DISPLAYCHANGE:
        return
    from app.core import anchor_manager as am

    mgr = am._manager
    if mgr is not None and am.shiboken6.isValid(mgr):
        mgr._screens.screens_changed()


# --- O vigia ------------------------------------------------------------------------------------------------------


class ScreenWatcher(QObject):
    """Vive dentro do AnchorManager, que pergunta `is_settling()` e chama `adopt`, `remember` e `user_placed`."""

    def __init__(self, manager, monitors_fn: Callable[[], List[Monitor]] = native_monitors,
                 screens_fn: Callable[[], List[ScreenInfo]] = current_screens):
        super().__init__(manager)
        self._mgr = manager
        self._monitors_fn = monitors_fn
        self._screens_fn = screens_fn
        self._placements: Dict[str, Placement] = {}
        self._provisional: set = set()    # widgets fora do lugar porque o monitor deles não está conectado
        self._settling = False
        self._restore_queued = False
        self._load()

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(SETTLE_MS)
        self._settle_timer.timeout.connect(self.settle)
        self._connect_screens()

    # --- Persistência ---

    def _load(self):
        from app.core.config_manager import config_manager

        data = config_manager.get_anchor("placements", {}) or {}
        if isinstance(data, dict):
            for k, v in data.items():
                p = Placement.from_json(v)
                if p is not None:
                    self._placements[k] = p

    def _save(self):
        from app.core.config_manager import config_manager

        config_manager.set_anchor("placements", {k: p.to_json() for k, p in self._placements.items()})

    def placement(self, key: str) -> Optional[Placement]:
        return self._placements.get(key)

    # --- Sinais do Qt ---

    def _connect_screens(self):
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is None:
            return
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self._on_screen_event)
        app.primaryScreenChanged.connect(self._on_screen_event)
        for s in app.screens():
            self._watch(s)

    def _watch(self, s):
        s.geometryChanged.connect(self._on_screen_event)

    def _on_screen_event(self, *_args):
        self.screens_changed()

    def _on_screen_added(self, s):
        self._watch(s)
        self.screens_changed()

    # --- Lembrar ---

    def remember(self, w):
        """O widget está num lugar escolhido (arraste, quadrante, grupo refeito): grava o lugar no monitor dele."""
        key = getattr(w, "ANCHOR_KEY", None)
        if key is None or self._settling or key in self._provisional or not w.isVisible():
            return
        animator = getattr(w, "animator", None)
        if animator is not None and animator.is_animating():
            return
        monitors = self._monitors_fn()
        card = card_native(w, monitors)
        p = placement_of(card, monitors) if card is not None else None
        if p is None or self._placements.get(key) == p:
            return
        self._placements[key] = p
        self._save()
        self._debug("REMEMBER", f"[{key}] {p}")

    def user_placed(self, keys: Iterable[str]):
        """Escolhido pelo usuário: deixa de ser provisório (pode ser gravado mesmo com o monitor antigo ausente)."""
        self._provisional.difference_update(keys)

    def adopt(self, w):
        """
        Primeira vez na tela nesta sessão. Com "Lembrar posição" ligado, vai para o lugar guardado no monitor dele (a
        posição absoluta da configuração aponta para outro monitor se a principal mudou com o app fechado). Sem lugar
        guardado, passa a ter um assim que terminar de surgir.
        """
        key = getattr(w, "ANCHOR_KEY", None)
        if key is None or self._settling:
            return
        p = self._placements.get(key)
        if p is None:
            QTimer.singleShot(ADOPT_DELAY_MS, lambda: self._adopt_later(w, key))
            return
        if not _remembers(key):
            return
        logical = self._logical(p)
        if logical is None:
            return                      # monitor ausente: fica onde abriu; o resgate cuida se estiver fora da tela
        from app.core.anchor_manager import move_card
        move_card(w, *logical)

    def _adopt_later(self, w, key: str):
        import shiboken6

        if key not in self._placements and shiboken6.isValid(w):
            self.remember(w)

    def _logical(self, p: Placement) -> Optional[Tuple[float, float]]:
        """O lugar em coordenadas do Qt, para quando o Qt está em dia (abertura): a tela do Qt com o mesmo canto."""
        from PySide6.QtGui import QGuiApplication

        hit = resolve(p, self._monitors_fn())
        if hit is None:
            return None
        m, _x, _y = hit
        for s in QGuiApplication.screens():
            g = s.geometry()
            if abs(g.x() - m.rect.l) <= 1 and abs(g.y() - m.rect.t) <= 1:
                return g.x() + p.dx / m.scale, g.y() + p.dy / m.scale
        return None

    # --- Troca de telas ---

    def screens_changed(self):
        """
        Chamado DENTRO do sinal do Qt (ou do WM_DISPLAYCHANGE): o Windows já tem os monitores novos nesse instante
        (medido nas 4 trocas do log). Devolver os widgets ali mesmo, e não no próximo giro do laço de eventos, evita
        meio segundo na tela errada: o próximo giro só chega depois de o Windows avisar todos os apps da mudança da
        área útil (460 a 720 ms no log). O giro seguinte confere de novo.
        """
        if not self._settling:
            self._settling = True
            logger.info("Telas mudaram: widgets voltam ao monitor deles")
            self._debug("WATCHER", "telas mudaram" + (" (só observando)" if self._observe() else ""))
        self._settle_timer.start()
        self.restore()
        if not self._restore_queued:
            self._restore_queued = True
            QTimer.singleShot(0, self._restore_now)

    def _restore_now(self):
        self._restore_queued = False
        self.restore()

    def is_settling(self) -> bool:
        return self._settling

    def restore(self) -> set:
        """Cada widget com lugar num monitor conectado volta para lá, na hora, em px físicos. Devolve os ausentes."""
        monitors = self._monitors_fn()
        missing, moves = set(), []
        for key, w in self._mgr.screen_windows():
            p = self._placements.get(key)
            if p is None:
                continue
            hit = resolve(p, monitors)
            if hit is None:
                missing.add(key)
                continue
            m, x, y = hit
            card = card_native(w, monitors)
            if card is not None and abs(card.l - x) <= 1 and abs(card.t - y) <= 1:
                continue
            moves.append((w, x, y, m.scale))
            was = f"({card.l:.0f},{card.t:.0f})" if card is not None else "?"
            self._debug("WATCHER", f"[{key}] {'faria' if self._observe() else 'volta'}: {was} -> {p.screen} ({x},{y})")
        if moves and not self._observe():
            move_native(moves)
        return missing

    def settle(self):
        """A configuração parou de mudar: reaplica os lugares e resgata quem ficou sem monitor ou fora das telas."""
        self._settle_timer.stop()
        missing = self.restore()
        self._settling = False
        self._provisional = set(missing)
        if missing:
            logger.info("Monitor ausente para %s: lugar provisório na tela principal", sorted(missing))
        self._debug("WATCHER", f"assentou; sem monitor: {sorted(missing)}")
        QTimer.singleShot(0, self._rescue)      # o Qt processa os movimentos acima antes de calcular o resgate

    def _rescue(self):
        if self._settling:
            return
        screens = self._screens_fn()
        if not screens:
            return
        primary = next((s for s in screens if s.primary), screens[0])
        provisional = set(self._provisional)

        def target_of(key: str, rect: Rect) -> Rect:
            p = self._placements.get(key)
            if key in provisional and p is not None:
                return Rect.of(primary.geo.l + p.dx / p.scale, primary.geo.t + p.dy / p.scale, rect.w, rect.h)
            return rect

        if self._observe():
            for key, _w, r in self._mgr.screen_members():
                t = target_of(key, r)
                self._debug("WATCHER", f"[{key}] resgate faria: ({r.l:.0f},{r.t:.0f}) -> ({t.l:.0f},{t.t:.0f})")
            return
        anchors = {k for k in self._placements if k not in provisional}
        self._mgr.relocate(target_of, screens, anchors=anchors)

    # --- Diagnóstico ---

    @staticmethod
    def _observe() -> bool:
        from app.core import screen_debug
        return screen_debug.observe_only()

    @staticmethod
    def _debug(event: str, text: str):
        from app.core import screen_debug
        screen_debug.log(event, text)
