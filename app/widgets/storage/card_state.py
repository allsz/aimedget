"""
StorageState - Estado e física de molas do Storage Widget (zero Win32, testável sem janela).

Molas amortecidas no padrão DesignBookmark (massa 1, Euler semi-implícito, 4 subpassos):
- Altura do cartão (262 px ancorado <-> expandido com todas as pastas e detalhe da linha).
- Largura, realce vertical (pop) e opacidade dos segmentos da barra de volume.
- Pílula de destaque deslizante (.hl) e altura/opacidade do painel de detalhes.
- Tambor de dígitos rolantes para o total usado em GB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services.storage_service import DriveUsage, FolderUsage, StorageSnapshot

CARD_W = 300.0
COMPACT_H = 262.0
ROW_H = 41.0
PAN_H = 48.0
CHROME_H = 138.0   # cabeçalho + total + subtítulo + barra + paddings

SPRING_SOFT = (260.0, 24.0)
SPRING_POP = (520.0, 16.0)
SPRING_FADE = (420.0, 32.0)
SPRING_HL_Y = (300.0, 26.0)
SUBSTEPS = 4


class Spring:
    """Mola amortecida (massa 1, Euler semi-implícito)."""

    def __init__(self, x: float, k_c: tuple[float, float] = SPRING_SOFT):
        self.x = float(x)
        self.t = float(x)
        self.v = 0.0
        self.k, self.c = float(k_c[0]), float(k_c[1])

    def snap(self, target: float):
        self.x = self.t = float(target)
        self.v = 0.0

    def step(self, dt: float):
        a = -self.k * (self.x - self.t) - self.c * self.v
        self.v += a * dt
        self.x += self.v * dt

    def settled(self, tol: float = 0.015) -> bool:
        return abs(self.x - self.t) < tol and abs(self.v) < tol * 20.0


class DigitRoller:
    """Tambor rolante de 4 dígitos ('ddd.d', suporta até 999.9 GB)."""

    def __init__(self, initial: float = 0.0):
        self.cols = [Spring(0.0, (260.0, 22.0 + i * 2.0)) for i in range(4)]
        self.value = 0.0
        self.set_value(initial, animate=False)

    def set_value(self, value: float, animate: bool = True):
        clamped = min(999.9, max(0.0, float(value)))
        self.value = clamped
        digits = f"{clamped:05.1f}".replace(".", "")
        for i, col in enumerate(self.cols):
            d = float(int(digits[i]))
            if animate:
                col.t = d
            else:
                col.snap(d)

    def step(self, dt: float):
        for col in self.cols:
            col.step(dt)

    def busy(self) -> bool:
        return any(not col.settled(0.008) for col in self.cols)

    @property
    def show_hundreds(self) -> bool:
        return self.value >= 100.0


@dataclass
class RowAnim:
    folder: FolderUsage
    w: Spring = field(default_factory=lambda: Spring(0.0, SPRING_SOFT))
    h: Spring = field(default_factory=lambda: Spring(1.0, SPRING_POP))
    o: Spring = field(default_factory=lambda: Spring(1.0, SPRING_FADE))
    p: Spring = field(default_factory=lambda: Spring(0.0, SPRING_SOFT))
    dot: Spring = field(default_factory=lambda: Spring(1.0, SPRING_POP))

    def step(self, dt: float):
        self.w.step(dt)
        self.h.step(dt)
        self.o.step(dt)
        self.p.step(dt)
        self.dot.step(dt)

    def busy(self) -> bool:
        return (
            not self.w.settled(0.05)
            or not self.h.settled(0.008)
            or not self.o.settled(0.008)
            or not self.p.settled(0.008)
            or not self.dot.settled(0.008)
        )


class StorageState:
    """Estado animado do StorageCard."""

    def __init__(self, animated: bool = True, always_expanded: bool = False):
        self.animated = bool(animated)
        self.always_expanded = bool(always_expanded)
        self.expanded = bool(always_expanded)

        self.drives: list[DriveUsage] = []
        self.active_drive_index: int = 0
        self.selected_row: int = 0
        self.hovered_row: int = -1
        self.hovered_drive: int = -1
        self.hovered_expand: bool = False
        self.hovered_open: bool = False
        self.scanning: bool = False

        self.rows: list[RowAnim] = []
        self.total_roller = DigitRoller(0.0)
        self.other_w = Spring(0.0, SPRING_SOFT)
        self.card_h = Spring(COMPACT_H, SPRING_SOFT)
        self.hl_y = Spring(0.0, SPRING_HL_Y)
        self.hl_h = Spring(ROW_H, SPRING_SOFT)
        self.hl_o = Spring(0.0, SPRING_FADE)

    @property
    def active_drive(self) -> Optional[DriveUsage]:
        if 0 <= self.active_drive_index < len(self.drives):
            return self.drives[self.active_drive_index]
        return None

    def target_card_height(self) -> float:
        drv = self.active_drive
        if not self.expanded or drv is None:
            return COMPACT_H
        n = len(drv.folders)
        if n == 0:
            return COMPACT_H
        return max(COMPACT_H, CHROME_H + n * ROW_H + PAN_H)

    def apply_snapshot(self, snapshot: StorageSnapshot, animate: bool = True):
        prev_drive_key = self.active_drive.drive if self.active_drive else None
        self.drives = list(snapshot.drives)
        if not self.drives:
            self.active_drive_index = 0
            self.rows = []
            self.total_roller.set_value(0.0, animate=animate and self.animated)
            self._sync_targets(animate=animate)
            return

        new_idx = 0
        if prev_drive_key is not None:
            for i, d in enumerate(self.drives):
                if d.drive == prev_drive_key:
                    new_idx = i
                    break
        self.active_drive_index = new_idx
        self._rebuild_rows(animate=animate, from_zero=not self.rows)

    def select_drive(self, index: int, animate: bool = True) -> bool:
        if not 0 <= index < len(self.drives) or index == self.active_drive_index:
            return False
        self.active_drive_index = index
        self.selected_row = 0
        self._rebuild_rows(animate=animate, from_zero=True)
        return True

    def set_expanded(self, expanded: bool, animate: bool = True) -> bool:
        target = True if self.always_expanded else bool(expanded)
        if target == self.expanded:
            return False
        self.expanded = target
        self._sync_targets(animate=animate)
        return True

    def set_always_expanded(self, enabled: bool, animate: bool = True):
        self.always_expanded = bool(enabled)
        if self.always_expanded and not self.expanded:
            self.expanded = True
            self._sync_targets(animate=animate)

    def select_row(self, index: int, animate: bool = True) -> bool:
        if not 0 <= index < len(self.rows):
            return False
        changed = (index != self.selected_row) or (not self.expanded)
        self.selected_row = index
        if not self.expanded:
            self.expanded = True
        self._sync_targets(animate=animate, pop_selected=True)
        return changed

    def _rebuild_rows(self, animate: bool = True, from_zero: bool = False):
        drv = self.active_drive
        if drv is None:
            self.rows = []
            return
        old_by_path = {r.folder.path.lower(): r for r in self.rows}
        new_rows: list[RowAnim] = []
        for f in drv.folders:
            prev = old_by_path.get(f.path.lower())
            if prev is not None and not from_zero:
                prev.folder = f
                new_rows.append(prev)
            else:
                ra = RowAnim(folder=f)
                if not (animate and self.animated) or not from_zero:
                    ra.w.snap(f.size_gb)
                new_rows.append(ra)
        self.rows = new_rows
        if self.selected_row >= len(self.rows):
            self.selected_row = max(0, len(self.rows) - 1)
        self._sync_targets(animate=animate, from_zero=from_zero)

    def _sync_targets(self, animate: bool = True, from_zero: bool = False, pop_selected: bool = False):
        use_anim = bool(animate and self.animated)
        drv = self.active_drive
        target_h = self.target_card_height()
        if use_anim:
            self.card_h.t = target_h
        else:
            self.card_h.snap(target_h)

        if drv is None:
            if use_anim:
                self.other_w.t = 0.0
                self.hl_o.t = 0.0
            else:
                self.other_w.snap(0.0)
                self.hl_o.snap(0.0)
            return

        self.total_roller.set_value(drv.used_gb, animate=use_anim)
        if use_anim:
            if from_zero:
                self.other_w.snap(0.0)
            self.other_w.t = drv.other_gb
        else:
            self.other_w.snap(drv.other_gb)

        hl_y_t = self.selected_row * ROW_H
        hl_h_t = (ROW_H + PAN_H) if self.expanded else ROW_H
        hl_o_t = 1.0 if (self.expanded and self.rows) else 0.0
        if use_anim:
            self.hl_y.t = hl_y_t
            self.hl_h.t = hl_h_t
            self.hl_o.t = hl_o_t
        else:
            self.hl_y.snap(hl_y_t)
            self.hl_h.snap(hl_h_t)
            self.hl_o.snap(hl_o_t)

        for i, r in enumerate(self.rows):
            on = self.expanded and i == self.selected_row
            w_t = r.folder.size_gb
            p_t = 1.0 if on else 0.0
            o_t = 1.0 if (not self.expanded or i == self.selected_row) else 0.35
            if use_anim:
                if from_zero:
                    r.w.snap(0.0)
                r.w.t = w_t
                r.p.t = p_t
                r.o.t = o_t
                r.h.t = 1.0
                r.dot.t = 1.0
                if pop_selected and on:
                    r.dot.x = 0.5
                    r.h.x = min(r.h.x, 0.55)
            else:
                r.w.snap(w_t)
                r.p.snap(p_t)
                r.o.snap(o_t)
                r.h.snap(1.0)
                r.dot.snap(1.0)

    def step(self, dt: float):
        if dt <= 0.0:
            return
        clamped_dt = min(dt, 1.0 / 30.0)
        sub_dt = clamped_dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            self.total_roller.step(sub_dt)
            self.other_w.step(sub_dt)
            self.card_h.step(sub_dt)
            self.hl_y.step(sub_dt)
            self.hl_h.step(sub_dt)
            self.hl_o.step(sub_dt)
            for r in self.rows:
                r.step(sub_dt)

    def busy(self) -> bool:
        if not self.animated:
            return False
        if (
            self.total_roller.busy()
            or not self.other_w.settled(0.05)
            or not self.card_h.settled(0.15)
            or not self.hl_y.settled(0.1)
            or not self.hl_h.settled(0.1)
            or not self.hl_o.settled(0.01)
        ):
            return True
        return any(r.busy() for r in self.rows)
