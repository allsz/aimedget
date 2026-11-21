"""
Estado do Battery Widget: dispositivos, opções e todas as molas (sem Qt, testável).

Molas no modelo do app (massa 1, Euler semi-implícito, 4 subpassos). Valores escolhidos no protótipo
`mockups/battery-layout-v3.html`:
- células deslizam com a mola "Soft" (MORPH 320/20);
- o cartão (largura/altura) e o anel usam a do tamanho (320/30): assentam sem passar do alvo, então o contorno da
  janela não treme e a altura do cartão não faz "dente";
- entrar/sair (opacidade e escala) com SETTLE 380/30; o arco enche com 200/26; a face (ícone <-> porcentagem) 520/30.

Sem animações do Windows (`animated=False`), tudo vai direto ao alvo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services.battery.models import BatteryDevice
from app.widgets.battery import layout as lay

SUBSTEPS = 4
CELL_SPRING = (320.0, 20.0)
SIZE_SPRING = (320.0, 30.0)
FADE_SPRING = (380.0, 30.0)
FILL_SPRING = (200.0, 26.0)
FACE_SPRING = (520.0, 30.0)
CHARGE_SPRING = (280.0, 34.0)   # CLOSE (amortecimento crítico): a bolinha entra/sai sem passar do ponto, discreta
RISE = 12.0                 # o anel novo sobe estes px enquanto aparece

FACE_HOVER = "hover"        # ícone; passar o mouse no cartão mostra a porcentagem
FACE_ICON = "icon"
FACE_PERCENT = "percent"
FACE_BOTH = "both"
FACES = (FACE_HOVER, FACE_ICON, FACE_PERCENT, FACE_BOTH)

LABEL_NAME = "name"
LABEL_TYPE = "type"
LABELS = (LABEL_NAME, LABEL_TYPE)

SHOW_ALL = "all"            # cabeçalho e nomes
SHOW_NAMES = "names"        # só os nomes (sem cabeçalho)
SHOW_HEADER = "header"      # só o cabeçalho (sem nomes)
SHOW_NONE = "none"
SHOWS = (SHOW_ALL, SHOW_NAMES, SHOW_HEADER, SHOW_NONE)

ODDS = (lay.ODD_CENTER, lay.ODD_LEFT)


class Spring:
    def __init__(self, x: float, kc: tuple, tol: float = 0.05):
        self.x = self.t = float(x)
        self.v = 0.0
        self.k, self.c = kc
        self.tol = tol

    def step(self, dt: float):
        h = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            a = -self.k * (self.x - self.t) - self.c * self.v
            self.v += a * h
            self.x += self.v * h

    def snap(self, value: Optional[float] = None):
        if value is not None:
            self.t = float(value)
        self.x = self.t
        self.v = 0.0

    def settled(self) -> bool:
        return abs(self.x - self.t) < self.tol and abs(self.v) < self.tol * 20


@dataclass
class Options:
    face: str = FACE_HOVER
    label: str = LABEL_NAME
    show: str = SHOW_ALL
    odd: str = lay.ODD_CENTER
    count: bool = True          # "X dispositivos" ao lado do título (some junto com o título)

    @property
    def header(self) -> bool:
        return self.show in (SHOW_ALL, SHOW_HEADER)

    @property
    def names(self) -> bool:
        return self.show in (SHOW_ALL, SHOW_NAMES)

    @staticmethod
    def from_config(get) -> "Options":
        o = Options()
        face, label, show, odd = get("face", o.face), get("label", o.label), get("show", o.show), get("odd", o.odd)
        o.face = face if face in FACES else FACE_HOVER
        o.label = label if label in LABELS else LABEL_NAME
        o.show = show if show in SHOWS else SHOW_ALL
        o.odd = odd if odd in ODDS else lay.ODD_CENTER
        o.count = bool(get("count", True))
        return o


@dataclass
class Cell:
    device: BatteryDevice
    x: Spring
    y: Spring
    alpha: Spring
    scale: Spring
    fill: Spring
    leaving: bool = False
    charge: Optional[Spring] = None     # 0..1: bolinha de carregando (cresce/aparece e abre espaço; o nome desliza)

    def __post_init__(self):
        if self.charge is None:
            self.charge = Spring(1.0 if self.device.charging else 0.0, CHARGE_SPRING, tol=0.004)

    def springs(self):
        return (self.x, self.y, self.alpha, self.scale, self.fill, self.charge)


@dataclass
class BatteryState:
    base_w: float = lay.DEFAULT_SIZE[0]
    base_h: float = lay.DEFAULT_SIZE[1]
    options: Options = field(default_factory=Options)
    animated: bool = True
    scanned: bool = False              # já houve uma leitura (antes disso: "procurando")
    hovered: bool = False
    order: list = field(default_factory=list)      # ids na ordem do cartão
    cells: dict = field(default_factory=dict)      # id -> Cell (inclui as que estão saindo)
    layout: Optional[lay.Layout] = None

    def __post_init__(self):
        self.W = Spring(self.base_w, SIZE_SPRING, tol=0.2)
        self.H = Spring(self.base_h, SIZE_SPRING, tol=0.2)
        self.D = Spring(lay.D_MIN, SIZE_SPRING, tol=0.05)
        self.face_pct = Spring(self._face_targets()[0], FACE_SPRING, tol=0.004)
        self.face_both = Spring(self._face_targets()[1], FACE_SPRING, tol=0.004)
        self.count_alpha = Spring(1.0 if self.options.count else 0.0, FADE_SPRING, tol=0.004)
        self.relayout(snap=True)

    # --- Consultas ---

    def devices(self) -> list[BatteryDevice]:
        return [self.cells[i].device for i in self.order]

    def visible_cells(self) -> list[Cell]:
        """As que estão no layout e as que ainda saem (estas por baixo)."""
        out = [c for c in self.cells.values() if c.leaving]
        out += [self.cells[i] for i in self.order]
        return out

    def any_charging(self) -> bool:
        return any(self.cells[i].device.charging for i in self.order)

    def card_size(self) -> tuple[float, float]:
        return self.W.x, self.H.x

    # --- Mudanças ---

    def set_devices(self, devices: list[BatteryDevice]) -> bool:
        """Aplica uma leitura. Novos entram (sobem e aparecem), os que sumiram saem; retorna se algo mudou."""
        self.scanned = True
        new_ids = [d.id for d in devices]
        changed = False
        for dev_id in list(self.order):
            if dev_id not in new_ids:
                cell = self.cells[dev_id]
                cell.leaving = True
                cell.alpha.t = 0.0
                cell.scale.t = 0.88
                self.order.remove(dev_id)
                if not self.animated:
                    del self.cells[dev_id]
                changed = True
        entering = []
        for dev in devices:
            cell = self.cells.get(dev.id)
            if cell is None or cell.leaving:
                cell = Cell(dev, Spring(0, CELL_SPRING), Spring(0, CELL_SPRING), Spring(0, FADE_SPRING, 0.004),
                            Spring(0.9, FADE_SPRING, 0.002), Spring(0, FILL_SPRING, 0.05))
                cell.alpha.t, cell.scale.t = 1.0, 1.0
                self.cells[dev.id] = cell
                entering.append(dev.id)
                changed = True
            elif cell.device != dev:
                cell.device = dev
                changed = True
            cell.fill.t = float(dev.percent) if dev.percent is not None else 0.0
            cell.charge.t = 1.0 if dev.charging else 0.0
            if not self.animated:
                cell.charge.snap()
        if new_ids != self.order:
            changed = True
        self.order = new_ids
        self.relayout(entering=entering)
        return changed

    def set_options(self, options: Options):
        self.options = options
        self._retarget_face()
        self.count_alpha.t = 1.0 if options.count else 0.0
        if not self.animated:
            self.count_alpha.snap()
        self.relayout()

    def set_base_size(self, w: float, h: float, direct: bool = False):
        """Tamanho escolhido pelo usuário (canto). `direct`: o cartão segue o ponteiro sem mola."""
        self.base_w = lay.clamp(float(w), lay.MIN_SIZE[0], lay.MAX_SIZE[0])
        self.base_h = lay.clamp(float(h), lay.MIN_SIZE[1], lay.MAX_SIZE[1])
        self.relayout(direct_size=direct)

    def set_hovered(self, hovered: bool):
        if hovered != self.hovered:
            self.hovered = bool(hovered)
            self._retarget_face()

    def _face_targets(self) -> tuple[float, float]:
        face = self.options.face
        if face == FACE_BOTH:
            return 0.0, 1.0
        if face == FACE_PERCENT:
            return 1.0, 0.0
        if face == FACE_HOVER:
            return (1.0 if self.hovered else 0.0), 0.0
        return 0.0, 0.0

    def _retarget_face(self):
        pct, both = self._face_targets()
        self.face_pct.t, self.face_both.t = pct, both
        if not self.animated:
            self.face_pct.snap()
            self.face_both.snap()

    def relayout(self, entering=(), snap: bool = False, direct_size: bool = False):
        o = self.options
        L = lay.compute(len(self.order), self.base_w, self.base_h, header=o.header, names=o.names, odd=o.odd)
        self.layout = L
        self.W.t, self.H.t, self.D.t = L.W, L.H, L.d
        instant = snap or not self.animated
        if instant or direct_size:
            self.W.snap()
            self.H.snap()
        if instant:
            self.D.snap()
        for i, dev_id in enumerate(self.order):
            cell = self.cells[dev_id]
            x, y = L.cells[i]
            cell.x.t, cell.y.t = x, y
            if dev_id in entering or instant:
                cell.x.snap()
                cell.y.snap()
                if dev_id in entering and not instant:
                    cell.y.x = y + RISE
            if instant:
                for s in (cell.alpha, cell.scale, cell.fill, cell.charge):
                    s.snap()

    # --- Relógio ---

    def step(self, dt: float) -> bool:
        """Avança as molas; retorna True enquanto algo se move."""
        dt = max(0.0, min(0.05, dt))
        if not self.animated:
            self._settle_all()
            return False
        busy = False
        for s in (self.W, self.H, self.D, self.face_pct, self.face_both, self.count_alpha):
            s.step(dt)
            busy = busy or not s.settled()
        for dev_id, cell in list(self.cells.items()):
            for s in cell.springs():
                s.step(dt)
                if s.settled():
                    s.snap()            # termina exatamente no alvo
                else:
                    busy = True
            if cell.leaving and cell.alpha.x < 0.02:
                del self.cells[dev_id]
        for s in (self.W, self.H, self.D, self.face_pct, self.face_both, self.count_alpha):
            if s.settled():
                s.snap()
        return busy or any(c.leaving for c in self.cells.values())

    def busy(self) -> bool:
        if any(c.leaving for c in self.cells.values()):
            return True
        springs = [self.W, self.H, self.D, self.face_pct, self.face_both, self.count_alpha]
        for c in self.cells.values():
            springs += list(c.springs())
        return not all(s.settled() for s in springs)

    def _settle_all(self):
        for s in (self.W, self.H, self.D, self.face_pct, self.face_both, self.count_alpha):
            s.snap()
        for dev_id, cell in list(self.cells.items()):
            if cell.leaving:
                del self.cells[dev_id]
                continue
            for s in cell.springs():
                s.snap()
