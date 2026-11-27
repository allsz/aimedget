"""Partida rápida: registro de tempo, Hub montado sob demanda e gravações que não repetem nada à toa."""
import sys
from unittest import mock

from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.core import startup_trace
from app.core.config_manager import config_manager
from app.hub import hub_window as hw


def _fresh_trace(monkeypatch, tmp_path):
    monkeypatch.setattr(startup_trace, "_log_path", lambda: str(tmp_path / "startup_timing.log"))
    monkeypatch.setattr(startup_trace, "_marks", [])
    monkeypatch.setattr(startup_trace, "_extras", [])
    monkeypatch.setattr(startup_trace, "_finished", False)


def test_trace_writes_one_line_per_start_with_marks(monkeypatch, tmp_path):
    _fresh_trace(monkeypatch, tmp_path)
    startup_trace.mark("qapplication")
    startup_trace.mark("ready")
    line = startup_trace.finish("minimized")
    assert line is not None and "minimized" in line and "qapplication=" in line and "ready=" in line
    assert startup_trace.finish("again") is None   # só a primeira chamada vale
    assert (tmp_path / "startup_timing.log").read_text(encoding="utf-8").count("\n") == 1


def test_trace_amend_after_finish_extends_the_same_line(monkeypatch, tmp_path):
    _fresh_trace(monkeypatch, tmp_path)
    startup_trace.mark("ready")
    startup_trace.finish("minimized")
    startup_trace.amend("hub_ui_cost", 640.4)
    lines = (tmp_path / "startup_timing.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].endswith("hub_ui_cost=640")


def test_trace_keeps_only_the_last_lines(monkeypatch, tmp_path):
    _fresh_trace(monkeypatch, tmp_path)
    log = tmp_path / "startup_timing.log"
    log.write_text("\n".join(f"old {i}" for i in range(100)) + "\n", encoding="utf-8")
    startup_trace.finish("normal")
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == startup_trace._KEEP_LINES and lines[0] == "old 61"


def test_config_does_not_rewrite_the_file_for_an_unchanged_value():
    with mock.patch.object(type(config_manager), "_save") as save:
        config_manager.set_active_skin(config_manager.get_active_skin())
        config_manager.set_timer_active_skin(config_manager.get_timer_active_skin())
        value = config_manager.get_weather("units", "c")
        config_manager.set_weather("units", value)
    save.assert_not_called()


class _WindowSpy(QObject):
    def __init__(self):
        super().__init__()
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.windows.append(type(obj).__name__)
        return False


def test_deferred_hub_builds_nothing_until_needed():
    app = QApplication.instance() or QApplication(sys.argv)
    with mock.patch.object(hw.QTimer, "singleShot"):
        hub = hw.AimedgetHubWindow(defer_ui=True)
    try:
        assert hub._ui_built is False
        assert not hasattr(hub, "sidebar") and not hasattr(hub, "page_gen")
        assert hub.tray_icon is not None          # a bandeja já existe: é o que o usuário usa para abrir o Hub
        # Seguir o Windows (claro/escuro) enquanto o Hub não existe não pode montá-lo
        hub._on_system_color_scheme_changed()
        hub.retranslate_ui()
        assert hub._ui_built is False
        # Abrir pela bandeja monta, uma vez
        with mock.patch.object(hw.AimedgetHubWindow, "_bring_to_front"):
            hub.show_and_activate()
        app.processEvents()
        assert hub._ui_built is True and hub.sidebar is not None and hub.page_gen is not None
        sidebar = hub.sidebar
        hub.prebuild_ui()
        assert hub.sidebar is sidebar             # não monta duas vezes
    finally:
        hub.close()
        hub.deleteLater()


def test_prebuild_builds_hidden_without_stray_windows():
    app = QApplication.instance() or QApplication(sys.argv)
    spy = _WindowSpy()
    app.installEventFilter(spy)
    with mock.patch.object(hw.QTimer, "singleShot"):
        hub = hw.AimedgetHubWindow(defer_ui=True)
    try:
        hub.prebuild_ui()
        assert hub._ui_built is False             # 1ª etapa só importa; as páginas sobem depois do respiro
        QTest.qWait(hw.PREBUILD_STEP_GAP_MS + 1500)
        assert hub._ui_built is True and not hub.isVisible()
        assert spy.windows == [], spy.windows
    finally:
        app.removeEventFilter(spy)
        hub.close()
        hub.deleteLater()


def test_eager_hub_is_unchanged():
    app = QApplication.instance() or QApplication(sys.argv)
    with mock.patch.object(hw.QTimer, "singleShot"):
        hub = hw.AimedgetHubWindow()
    try:
        assert hub._ui_built is True and hub.sidebar is not None
    finally:
        hub.close()
        hub.deleteLater()


# --- Espera pela CPU calma (app/core/idle_gate.py) ---

class _FakeCpu:
    def __init__(self, readings):
        self.readings = list(readings)

    def busy(self):
        return self.readings.pop(0) if self.readings else 0.0


def _gate(cpu, **kw):
    from app.core.idle_gate import IdleGate
    calls = []
    kw.setdefault("first_delay_ms", 10)
    kw.setdefault("poll_ms", 10)
    gate = IdleGate(lambda: calls.append(1), sampler=cpu, **kw)
    return gate, calls


def test_idle_gate_waits_for_consecutive_calm_samples():
    QApplication.instance() or QApplication(sys.argv)
    # prime, ocupada, calma, ocupada (zera), calma, calma -> dispara na última
    gate, calls = _gate(_FakeCpu([None, 0.9, 0.1, 0.8, 0.1, 0.1]))
    gate.start()
    QTest.qWait(40)
    assert calls == [] and not gate.fired
    QTest.qWait(150)
    assert calls == [1] and gate.fired


def test_idle_gate_fires_once_and_gives_up_on_a_busy_machine():
    QApplication.instance() or QApplication(sys.argv)
    gate, calls = _gate(_FakeCpu([None] + [0.95] * 500), give_up_ms=120)
    gate.start()
    QTest.qWait(400)
    assert calls == [] and gate.cancelled and not gate.fired


def test_idle_gate_stop_cancels():
    QApplication.instance() or QApplication(sys.argv)
    gate, calls = _gate(_FakeCpu([None, 0.0, 0.0, 0.0]), first_delay_ms=50)
    gate.start()
    gate.stop()
    QTest.qWait(200)
    assert calls == []


def test_cpu_sampler_reports_a_fraction_on_windows():
    from app.core.idle_gate import CpuSampler
    s = CpuSampler()
    assert s.busy() is None   # a 1ª leitura só marca o ponto de partida
    QTest.qWait(50)
    value = s.busy()
    assert value is None or 0.0 <= value <= 1.0


def test_trace_line_carries_logon_and_boot(monkeypatch, tmp_path):
    _fresh_trace(monkeypatch, tmp_path)
    monkeypatch.setattr(startup_trace, "_since_logon_s", lambda: 12)
    monkeypatch.setattr(startup_trace, "_uptime_s", lambda: 53)
    line = startup_trace.finish("minimized")
    assert "boot+53s logon+12s" in line
