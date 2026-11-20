"""
Estado puro do Performance Widget: histórico de 60 segundos por métrica, métrica selecionada,
transição suave entre abas (respeitando as animações do Windows) e texto de detalhe.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from app.core.i18n import t
from app.services.fps_service import FpsReading
from app.services.performance_service import PerformanceSnapshot

BASE_METRICS = ("cpu", "gpu", "vram", "ram")
ALL_METRICS = ("fps", "cpu", "gpu", "vram", "ram")
METRICS = BASE_METRICS
HISTORY_LEN = 60
PAST = -1e9
SELECT_DUR = 0.240   # s: deslize da pílula e morph ponto <-> barra

METRIC_LABELS = {
    "fps": "FPS",
    "cpu": "CPU",
    "gpu": "GPU",
    "vram": "VRAM",
    "ram": "RAM",
}

# Cores de destaque distintas e legíveis no vidro escuro
METRIC_COLORS = {
    "fps": "#fb7185",    # coral vibrante
    "cpu": "#38bdf8",    # azul ciano (estilo Task Manager / Game Bar)
    "gpu": "#34d399",    # esmeralda suave
    "vram": "#fbbf24",   # âmbar
    "ram": "#c084fc",    # violeta suave
}

_FPS_CEILINGS = (60.0, 120.0, 144.0, 165.0, 240.0, 360.0, 500.0)


def ease_out_cubic(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    inv = 1.0 - x
    return 1.0 - inv * inv * inv


@dataclass
class PerformanceState:
    selected: str = "cpu"
    prev_selected: str = "cpu"
    select_t0: float = PAST
    animated: bool = True
    fps_enabled: bool = False
    hovered_pill: int = -1
    pressed_pill: int = -1
    latest: PerformanceSnapshot = field(default_factory=PerformanceSnapshot)
    fps_reading: FpsReading = field(default_factory=FpsReading)
    history: dict[str, deque[float]] = field(
        default_factory=lambda: {m: deque(maxlen=HISTORY_LEN) for m in ALL_METRICS}
    )

    def visible_metrics(self) -> tuple[str, ...]:
        return ALL_METRICS if self.fps_enabled else BASE_METRICS

    def set_fps_enabled(self, enabled: bool):
        self.fps_enabled = bool(enabled)
        if not self.fps_enabled and self.selected == "fps":
            self.selected = "cpu"
            self.prev_selected = "cpu"
            self.select_t0 = PAST

    def push(self, snap: PerformanceSnapshot):
        self.latest = snap
        values = {
            "cpu": snap.cpu_pct,
            "gpu": snap.gpu_pct,
            "vram": snap.vram_pct,
            "ram": snap.ram_pct,
        }
        for key, val in values.items():
            if val is not None:
                self.history[key].append(min(100.0, max(0.0, float(val))))

    def push_fps(self, reading: FpsReading):
        self.fps_reading = reading
        if reading.fps is not None:
            self.history["fps"].append(max(0.0, float(reading.fps)))

    def select(self, metric: str, now: Optional[float] = None) -> bool:
        visible = self.visible_metrics()
        if metric in visible and metric != self.selected:
            if self.animated and now is not None:
                self.prev_selected = self.selected
                self.select_t0 = float(now)
            else:
                self.prev_selected = metric
                self.select_t0 = PAST
            self.selected = metric
            return True
        return False

    def transition_progress(self, now: float) -> float:
        if not self.animated or self.select_t0 <= PAST / 2.0:
            return 1.0
        raw = (now - self.select_t0) / SELECT_DUR if SELECT_DUR > 0 else 1.0
        return ease_out_cubic(raw)

    def transitions_busy(self, now: float) -> bool:
        return self.animated and self.select_t0 > PAST / 2.0 and (now - self.select_t0) < SELECT_DUR

    def pill_active_weight(self, metric: str, now: float) -> float:
        """Peso 0..1 de cada pílula (0 = ponto inativo, 1 = barra vertical ativa)."""
        e = self.transition_progress(now)
        if metric == self.selected:
            return 1.0 if self.prev_selected == self.selected else e
        if metric == self.prev_selected:
            return 1.0 - e
        return 0.0

    def select_index(self, index: int, now: Optional[float] = None) -> bool:
        visible = self.visible_metrics()
        if 0 <= index < len(visible):
            return self.select(visible[index], now=now)
        return False

    def selected_index(self) -> int:
        visible = self.visible_metrics()
        return visible.index(self.selected) if self.selected in visible else 0

    def current_pct(self, metric: str) -> Optional[float]:
        if metric == "fps":
            return self.fps_reading.fps
        snap = self.latest
        return {
            "cpu": snap.cpu_pct,
            "gpu": snap.gpu_pct,
            "vram": snap.vram_pct,
            "ram": snap.ram_pct,
        }.get(metric)

    def pct_text(self, metric: str) -> str:
        if metric == "fps":
            r = self.fps_reading
            if r.fps is None:
                return "--"
            if r.is_lossless_scaling and r.base_fps is not None:
                return f"{int(round(r.base_fps))}/{int(round(r.fps))}"
            return str(int(round(r.fps)))
        val = self.current_pct(metric)
        if val is None:
            return "--"
        return f"{int(round(val))}%"

    def hero_text(self, metric: str) -> str:
        if metric == "fps":
            return "--" if self.fps_reading.fps is None else str(int(round(self.fps_reading.fps)))
        return self.pct_text(metric)

    def detail_text(self, metric: str) -> str:
        snap = self.latest
        if metric == "cpu":
            return f"{snap.cpu_ghz:.2f} GHz" if snap.cpu_ghz is not None else ""
        if metric == "gpu":
            return snap.gpu_name
        if metric == "vram":
            if snap.vram_used_gb is not None and snap.vram_total_gb is not None:
                return f"{snap.vram_used_gb:.1f} / {snap.vram_total_gb:.1f} GB"
            return ""
        if metric == "ram":
            if snap.ram_used_gb is not None and snap.ram_total_gb is not None:
                return f"{snap.ram_used_gb:.1f} / {snap.ram_total_gb:.1f} GB"
            return ""
        if metric == "fps":
            r = self.fps_reading
            if r.fps is None:
                return t("perf_fps_waiting")
            if r.is_lossless_scaling and r.base_fps is not None:
                return f"{int(round(r.base_fps))} → {int(round(r.fps))} FPS · LSFG"
            if r.is_lossless_scaling:
                return "FPS · LSFG"
            return f"FPS · {r.app_name}" if r.app_name else "FPS"
        return ""

    def chart_ceiling(self, metric: str) -> float:
        if metric != "fps":
            return 100.0
        samples = self.history.get("fps")
        peak = max(samples, default=0.0) if samples else 0.0
        for cap in _FPS_CEILINGS:
            if peak <= cap:
                return cap
        return float(((int(peak) // 100) + 1) * 100)

    def samples(self, metric: str) -> list[float]:
        return list(self.history.get(metric, ()))
