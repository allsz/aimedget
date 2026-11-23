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
SKIN_FLUENT = "fluent"
SKIN_NOTHING_DOT = "nothing_dot"
PERFORMANCE_SKINS = (SKIN_FLUENT, SKIN_NOTHING_DOT)
HISTORY_LEN = 60
PAST = -1e9
SELECT_DUR = 0.240   # s: deslize da pílula e morph ponto <-> barra
FPS_CLEAR_DUR = 0.420  # s: recolhimento suave do gráfico de FPS até zero ao fechar o jogo

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


def normalize_metric_order(order) -> tuple[str, ...]:
    """Valida uma ordem salva de métricas: preserva chaves válidas sem duplicatas e completa o que faltar."""
    seen: list[str] = []
    if isinstance(order, (list, tuple)):
        for m in order:
            if isinstance(m, str) and m in ALL_METRICS and m not in seen:
                seen.append(m)
    for m in ALL_METRICS:
        if m not in seen:
            seen.append(m)
    return tuple(seen)


@dataclass
class PerformanceState:
    selected: str = "cpu"
    prev_selected: str = "cpu"
    select_t0: float = PAST
    animated: bool = True
    fps_enabled: bool = False
    skin_id: str = SKIN_FLUENT
    metric_order: tuple[str, ...] = ALL_METRICS
    hovered_pill: int = -1
    pressed_pill: int = -1
    reorder_mode: bool = False
    reorder_t0: float = PAST
    drag_metric: Optional[str] = None
    drag_y: float = 0.0
    pill_y_offsets: dict[str, float] = field(default_factory=dict)
    done_hovered: bool = False
    done_pressed: bool = False
    dropdown_open: bool = False
    dropdown_progress: float = 0.0
    dropdown_hovered: int = -1
    trigger_hovered: bool = False
    fps_clear_t0: float = PAST
    fps_clear_samples: list[float] = field(default_factory=list)
    latest: PerformanceSnapshot = field(default_factory=PerformanceSnapshot)
    fps_reading: FpsReading = field(default_factory=FpsReading)
    history: dict[str, deque[float]] = field(
        default_factory=lambda: {m: deque(maxlen=HISTORY_LEN) for m in ALL_METRICS}
    )

    def __post_init__(self):
        self.metric_order = normalize_metric_order(self.metric_order)

    def visible_metrics(self) -> tuple[str, ...]:
        if self.fps_enabled:
            return self.metric_order
        return tuple(m for m in self.metric_order if m != "fps")

    def set_metric_order(self, order) -> tuple[str, ...]:
        self.metric_order = normalize_metric_order(order)
        return self.metric_order

    def move_visible_metric(self, from_idx: int, to_idx: int) -> bool:
        """Move uma métrica visível de `from_idx` para `to_idx`, preservando a posição relativa de FPS se oculto."""
        visible = list(self.visible_metrics())
        if not (0 <= from_idx < len(visible) and 0 <= to_idx < len(visible)) or from_idx == to_idx:
            return False
        moved = visible.pop(from_idx)
        visible.insert(to_idx, moved)
        if self.fps_enabled:
            self.metric_order = tuple(visible)
        else:
            fps_pos = self.metric_order.index("fps") if "fps" in self.metric_order else 0
            new_order = list(visible)
            new_order.insert(min(fps_pos, len(new_order)), "fps")
            self.metric_order = tuple(new_order)
        return True

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

    def push_fps(self, reading: FpsReading, now: Optional[float] = None):
        self.fps_reading = reading
        if reading.fps is not None:
            self.fps_clear_t0 = PAST
            self.fps_clear_samples.clear()
            self.history["fps"].append(max(0.0, float(reading.fps)))
        elif self.history["fps"]:
            if self.animated and now is not None:
                self.fps_clear_samples = list(self.history["fps"])
                self.fps_clear_t0 = float(now)
            else:
                self.fps_clear_samples.clear()
                self.fps_clear_t0 = PAST
            self.history["fps"].clear()

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
        if self.reorder_mode and self.animated:
            return True
        if self.drag_metric is not None:
            return True
        if any(abs(v) > 0.25 for v in self.pill_y_offsets.values()):
            return True
        dd_target = 1.0 if self.dropdown_open else 0.0
        if self.animated and abs(self.dropdown_progress - dd_target) > 0.01:
            return True
        if self.fps_clear_samples and self.animated and (now - self.fps_clear_t0) < FPS_CLEAR_DUR:
            return True
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
                return f"{int(round(r.base_fps))} → {int(round(r.fps))} · LSFG"
            if r.is_lossless_scaling:
                return "LSFG"
            return r.app_name or ""
        return ""

    def chart_ceiling(self, metric: str, window: Optional[int] = None) -> float:
        """Teto do gráfico; `window` limita o pico às últimas N amostras (as que estão na tela)."""
        if metric != "fps":
            return 100.0
        samples = list(self.history.get("fps") or self.fps_clear_samples)
        if window is not None:
            samples = samples[-window:]
        peak = max(samples, default=0.0)
        for cap in _FPS_CEILINGS:
            if peak <= cap:
                return cap
        return float(((int(peak) // 100) + 1) * 100)

    def samples(self, metric: str, now: Optional[float] = None) -> list[float]:
        if metric == "fps" and self.fps_clear_samples:
            if not self.animated or now is None:
                self.fps_clear_samples.clear()
                self.fps_clear_t0 = PAST
                return []
            raw = (now - self.fps_clear_t0) / FPS_CLEAR_DUR if FPS_CLEAR_DUR > 0 else 1.0
            if raw >= 1.0:
                self.fps_clear_samples.clear()
                self.fps_clear_t0 = PAST
                return []
            k = 1.0 - ease_out_cubic(raw)
            return [v * k for v in self.fps_clear_samples]
        return list(self.history.get(metric, ()))
