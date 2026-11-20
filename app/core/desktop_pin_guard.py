"""
DesktopPinGuard - mantém um widget "fixado na área de trabalho" no lugar mesmo depois do Win+D.

Mesma estratégia do Rainmeter (lida no código dele): a janela continua sendo uma janela comum de primeiro nível (nada
de pendurar no Explorer) e é recolocada logo acima do desktop quando sai do lugar. Dois gatilhos:
- aviso do Windows quando o primeiro plano muda (o Win+D muda), com novas checagens logo depois, porque o desktop
  termina de subir alguns milissegundos após o aviso;
- uma checagem a cada 250 ms como rede de segurança (o Rainmeter usa o mesmo intervalo). Ela só lê a ordem das
  janelas: custo desprezível, e só roda com o widget fixado e na tela.
"""

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QWidget

from app.core import desktop_layer

POLL_MS = 250
RECHECK_MS = (0, 40, 120, 300)   # depois de uma troca de primeiro plano


class DesktopPinGuard(QObject):
    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self._widget = widget
        self._hook: desktop_layer.ForegroundHook | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self.check)
        self.replacements = 0   # quantas vezes recolocou (para testes e diagnóstico)

    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self):
        if not desktop_layer.IS_WINDOWS or self._timer.isActive():
            return
        hwnd = self._hwnd()
        desktop_layer.set_excluded_from_peek(hwnd, True)
        self._hook = desktop_layer.ForegroundHook(self._on_foreground_changed)
        self._timer.start()
        self.check()

    def stop(self):
        if not self._timer.isActive():
            return
        self._timer.stop()
        if self._hook is not None:
            self._hook.close()
            self._hook = None
        desktop_layer.set_excluded_from_peek(self._hwnd(), False)

    def check(self):
        """Se o widget saiu do lugar (atrás do desktop, ou por cima de um app), volta para logo acima do desktop."""
        # Rechecagens agendadas antes de soltar o cartão ainda chegam aqui: sem esta guarda, uma delas devolvia o
        # cartão (já "sempre no topo") ao nível do desktop.
        if not self._timer.isActive() or not self._widget.isVisible():
            return
        hwnd = self._hwnd()
        if desktop_layer.needs_replace(hwnd):
            desktop_layer.send_to_desktop_layer(hwnd)
            self.replacements += 1

    def _on_foreground_changed(self):
        for ms in RECHECK_MS:
            QTimer.singleShot(ms, self, self.check)

    def _hwnd(self) -> int:
        return int(self._widget.winId())
