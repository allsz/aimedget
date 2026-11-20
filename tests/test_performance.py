import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.services.fps_service import (
    FpsReading,
    FpsService,
    compute_rolling_fps,
    detect_game_target,
    parse_presentmon_header,
    parse_presentmon_row,
)
from app.services.performance_service import (
    PerformanceService,
    PerformanceSnapshot,
    aggregate_gpu_utilization,
    compute_cpu_percent,
    extract_pid_3d_utilization,
    match_vram_usage,
    shorten_gpu_name,
)
from app.ui_components.floating_card import CARD_H, CARD_W, FloatingCard
from app.widgets.performance.card_painter import paint_performance_card, pill_at, pill_rect
from app.widgets.performance.card_state import HISTORY_LEN, METRICS, PerformanceState
from app.widgets.performance.performance_card import PerformanceCard
from app.widgets.performance.performance_controller import PerformanceWidgetController
from app.widgets.performance.specs import init_performance_spec, mock_state, paint_performance


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_compute_cpu_percent():
    assert compute_cpu_percent(None, (10, 20, 30)) is None
    # total = 100, idle = 75 -> 25% busy
    assert compute_cpu_percent((100, 200, 100), (175, 250, 150)) == pytest.approx(25.0)
    # 0 total delta -> 0%
    assert compute_cpu_percent((10, 20, 30), (10, 20, 30)) == 0.0


def test_shorten_gpu_name():
    assert shorten_gpu_name("NVIDIA GeForce RTX 3080 Ti") == "RTX 3080 Ti"
    assert shorten_gpu_name("AMD Radeon(TM) RX 7900 XTX") == "RX 7900 XTX"
    assert shorten_gpu_name("Intel(R) Arc(TM) A770") == "Arc A770"


def test_aggregate_gpu_utilization_filters_luid_and_peaks_engine():
    items = [
        ("pid_1_luid_0x00000000_0x000101B6_phys_0_eng_0_engtype_3D", 15.0),
        ("pid_2_luid_0x00000000_0x000101B6_phys_0_eng_0_engtype_3D", 22.5),
        ("pid_3_luid_0x00000000_0x000101B6_phys_0_eng_1_engtype_VideoEncode", 48.0),
        ("pid_4_luid_0x00000000_0x99999999_phys_0_eng_0_engtype_3D", 99.0),
    ]
    assert aggregate_gpu_utilization(items, "luid_0x00000000_0x000101B6") == pytest.approx(48.0)
    assert aggregate_gpu_utilization([], "luid_0x00000000_0x000101B6") is None


def test_match_vram_usage():
    items = [
        ("luid_0x00000000_0x000101B6_phys_0", 2_500_000_000.0),
        ("luid_0x00000000_0x00014268_phys_0", 0.0),
    ]
    assert match_vram_usage(items, "luid_0x00000000_0x000101B6") == pytest.approx(2_500_000_000.0)
    assert match_vram_usage([], "") is None


def test_performance_state_history_and_formatting():
    state = PerformanceState()
    assert state.pct_text("cpu") == "--"
    assert state.detail_text("cpu") == ""

    for i in range(HISTORY_LEN + 15):
        state.push(
            PerformanceSnapshot(
                cpu_pct=float(i % 101),
                cpu_ghz=3.75,
                gpu_pct=64.4,
                gpu_name="RTX 3080 Ti",
                vram_pct=25.0,
                vram_used_gb=3.0,
                vram_total_gb=12.0,
                ram_pct=50.0,
                ram_used_gb=16.0,
                ram_total_gb=32.0,
            )
        )

    assert len(state.samples("cpu")) == HISTORY_LEN
    assert state.pct_text("gpu") == "64%"
    assert state.detail_text("cpu") == "3.75 GHz"
    assert state.detail_text("gpu") == "RTX 3080 Ti"
    assert state.detail_text("vram") == "3.0 / 12.0 GB"
    assert state.detail_text("ram") == "16.0 / 32.0 GB"
    assert state.select("ram") is True
    assert state.select("ram") is False
    assert state.selected == "ram"


def test_performance_card_reuses_floating_card_container(qapp):
    card = PerformanceCard(scale=1.0, desktop_mode=False)
    try:
        assert isinstance(card, FloatingCard)
        assert card.card_size() == (int(CARD_W), int(CARD_H))
        assert card._card_needs_frames(card.now()) is False

        card.set_scale(1.2)
        assert card.card_size() == (int(round(CARD_W * 1.2)), int(round(CARD_H * 1.2)))

        # Hit-testing das 4 pílulas
        for i in range(len(METRICS)):
            assert pill_at(pill_rect(i).center()) == i
        assert pill_at(QPointF(250, 200)) == -1
    finally:
        card.close()
        card.deleteLater()


def test_paint_performance_card_and_hub_preview(qapp):
    img = QImage(320, 280, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    paint_performance_card(p, QRectF(10, 9, CARD_W, CARD_H), PerformanceState(), pinned=False)
    paint_performance_card(p, QRectF(10, 9, CARD_W, CARD_H), mock_state(), pinned=True)
    paint_performance(p, QRectF(0, 0, 240, 200), None)
    p.end()

    spec = init_performance_spec()
    assert spec.id == "performance"


class _FakePerfService(PerformanceService):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def test_controller_lifecycle_and_config(qapp, monkeypatch):
    store: dict = {}
    monkeypatch.setattr(config_manager, "get_performance", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(config_manager, "set_performance", lambda k, v: store.__setitem__(k, v))

    svc = _FakePerfService()
    ctrl = PerformanceWidgetController(service=svc)
    try:
        ctrl.show()
        assert svc.started == 1

        ctrl.select_metric("gpu")
        assert ctrl.skin.state.selected == "gpu"
        assert store["selected_metric"] == "gpu"

        ctrl.set_scale(0.85)
        assert store["scale"] == pytest.approx(0.85, abs=1e-3)

        ctrl.set_desktop_mode(True)
        assert store["desktop_mode"] is True

        seen_remember: list[bool] = []
        ctrl.remember_position_changed.connect(seen_remember.append)
        ctrl.skin.remember_position_changed.emit(True)
        assert store["remember_position"] is True
        assert isinstance(store["position"], list) and len(store["position"]) == 2
        assert seen_remember == [True]

        ctrl.hide()
        assert svc.stopped >= 1
    finally:
        ctrl.skin.close()
        ctrl.skin.deleteLater()


def test_extract_pid_3d_utilization():
    items = [
        ("pid_100_luid_0x00000000_0x000101B6_phys_0_eng_0_engtype_3D", 42.5),
        ("pid_100_luid_0x00000000_0x000101B6_phys_0_eng_1_engtype_Copy", 10.0),
        ("pid_200_luid_0x00000000_0x000101B6_phys_0_eng_0_engtype_3D", 0.2),
        ("pid_300_luid_0x00000000_0x000101B6_phys_0_eng_0_engtype_3D", 18.0),
    ]
    res = extract_pid_3d_utilization(items, "luid_0x00000000_0x000101B6")
    assert res == {100: pytest.approx(42.5), 300: pytest.approx(18.0)}


def test_detect_game_target_normal_ignored_and_lossless_scaling():
    pid_3d = {111: 65.0, 222: 12.0, 333: 40.0, 444: 8.0}
    pid_exes = {
        111: "Cyberpunk2077.exe",
        222: "LosslessScaling.exe",
        333: "chrome.exe",
        444: "wallpaper64.exe",
    }

    # Normal fullscreen 3D game
    t_game = detect_game_target(111, "Cyberpunk2077.exe", True, pid_3d, pid_exes=pid_exes)
    assert t_game is not None and t_game.pid == 111 and not t_game.is_lossless_scaling

    # Windowed 3D game is also detected
    t_win = detect_game_target(111, "Cyberpunk2077.exe", False, pid_3d, pid_exes=pid_exes)
    assert t_win is not None and t_win.pid == 111

    # Clicking our own widget keeps tracking the active game
    t_own = detect_game_target(999, "python.exe", False, pid_3d, pid_exes=pid_exes, own_pid=999, prev_target=t_game)
    assert t_own is not None and t_own.pid == 111

    # Clicking a desktop app (e.g. second monitor) still detects the 3D game running on GPU
    t_bg = detect_game_target(333, "chrome.exe", True, pid_3d, pid_exes=pid_exes)
    assert t_bg is not None and t_bg.pid == 111

    # Clicking an Electron IDE on monitor 2 still tracks the game on monitor 1
    t_ide = detect_game_target(
        555, "Antigravity IDE.exe", False, {111: 55.0, 555: 4.0},
        pid_exes={111: "JustVolleyball.exe", 555: "Antigravity IDE.exe"},
    )
    assert t_ide is not None and t_ide.pid == 111

    # Clicking an unlisted lightweight windowed app on monitor 2 still prefers the heavy 3D game on monitor 1
    t_other = detect_game_target(
        556, "SomeApp.exe", False, {111: 55.0, 556: 6.0},
        pid_exes={111: "JustVolleyball.exe", 556: "SomeApp.exe"},
    )
    assert t_other is not None and t_other.pid == 111

    # Only browser + wallpaper engine running (no game) -> None
    assert detect_game_target(
        333, "chrome.exe", True, {333: 40.0, 444: 8.0}, pid_exes={333: "chrome.exe", 444: "wallpaper64.exe"}
    ) is None

    # Fullscreen indie / OpenGL game with 0% PDH 3D usage is still detected (foreground or on another monitor)
    t_indie_fg = detect_game_target(777, "JustVolleyball.exe", True, {})
    assert t_indie_fg is not None and t_indie_fg.pid == 777

    t_indie_mon1 = detect_game_target(
        555, "Antigravity IDE.exe", False, {},
        fullscreen_windows=[(777, "JustVolleyball.exe")],
    )
    assert t_indie_mon1 is not None and t_indie_mon1.pid == 777

    # Lossless Scaling in foreground picks itself + highest 3D base game PID
    t_ls = detect_game_target(222, "LosslessScaling.exe", True, pid_3d, pid_exes=pid_exes)
    assert t_ls is not None and t_ls.is_lossless_scaling is True and t_ls.base_pid == 111


def test_presentmon_csv_parsing_and_fps_math():
    hdr_v2 = parse_presentmon_header("Application,ProcessID,SwapChainAddress,FrameTime,MsBetweenDisplayChange")
    row = parse_presentmon_row("Cyberpunk2077.exe,1234,0x1,8.33,8.35", hdr_v2)
    assert row == (1234, "Cyberpunk2077.exe", pytest.approx(8.33), pytest.approx(8.35))

    hdr_v1 = parse_presentmon_header("Application,ProcessID,msBetweenPresents,msBetweenDisplayChange")
    row_v1 = parse_presentmon_row("LosslessScaling.exe,5678,16.67,8.33", hdr_v1)
    assert row_v1 == (5678, "LosslessScaling.exe", pytest.approx(16.67), pytest.approx(8.33))

    assert compute_rolling_fps([16.6667, 16.6667]) == pytest.approx(60.0, abs=0.1)
    assert compute_rolling_fps([]) is None


def test_performance_state_and_paint_with_fps_and_lossless_scaling(qapp):
    state = PerformanceState(fps_enabled=True, animated=True)
    assert state.visible_metrics() == ("fps", "cpu", "gpu", "vram", "ram")
    assert state.select("fps", now=10.0) is True
    assert state.transitions_busy(10.05) is True
    assert 0.0 < state.pill_active_weight("fps", 10.05) < 1.0
    assert 0.0 < state.pill_active_weight("cpu", 10.05) < 1.0
    assert state.transitions_busy(10.5) is False
    assert state.pill_active_weight("fps", 10.5) == pytest.approx(1.0)
    assert state.pct_text("fps") == "--"

    state.push_fps(FpsReading(fps=120.0, base_fps=60.0, app_name="EldenRing", is_lossless_scaling=True))
    assert state.pct_text("fps") == "60/120"
    assert state.hero_text("fps") == "120"
    assert "60 → 120 · LSFG" in state.detail_text("fps")
    assert state.chart_ceiling("fps") == 120.0

    # Paint 5-pill card mid-transition and settled without error
    img = QImage(320, 280, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    paint_performance_card(p, QRectF(10, 9, CARD_W, CARD_H), state, pinned=False, now=10.08)
    paint_performance_card(p, QRectF(10, 9, CARD_W, CARD_H), state, pinned=False, now=10.5)
    p.end()

    # With Windows animations disabled, switching is instant (zero frames)
    state.animated = False
    assert state.select("gpu", now=20.0) is True
    assert state.transitions_busy(20.05) is False
    assert state.pill_active_weight("gpu", 20.0) == pytest.approx(1.0)
    assert state.pill_active_weight("fps", 20.0) == pytest.approx(0.0)

    # Disabling FPS switches selection back to cpu
    state.select("fps", now=21.0)
    state.set_fps_enabled(False)
    assert len(state.visible_metrics()) == 4
    assert state.selected == "cpu"
