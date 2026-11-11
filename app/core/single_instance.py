"""
Instância única do Aimedget (por usuário do Windows).

A primeira cópia abre um canal local (QLocalServer, um named pipe que só existe nesta máquina e nesta sessão).
Uma segunda cópia se conecta a ele, pede para a primeira mostrar o Hub (ou nada, se ela foi aberta minimizada,
como no login do Windows) e encerra. Assim nunca há widgets e ícones de tray duplicados.

O canal só transporta uma palavra fixa ("show" ou "quiet"); nada mais é lido ou enviado.
"""

import getpass
import hashlib

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_CONNECT_TIMEOUT_MS = 300


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "default"
    return "aimedget-single-instance-" + hashlib.sha1(user.encode("utf-8")).hexdigest()[:12]


class SingleInstance(QObject):
    show_requested = Signal()   # outra cópia foi aberta normalmente: mostrar o Hub

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = _server_name()
        self._server: QLocalServer | None = None

    def notify_running(self, show: bool) -> bool:
        """True se já existe uma cópia rodando (e ela foi avisada). Nesse caso esta cópia deve encerrar."""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(_CONNECT_TIMEOUT_MS):
            return False
        sock.write(b"show" if show else b"quiet")
        sock.flush()
        sock.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
        sock.disconnectFromServer()
        return True

    def listen(self) -> bool:
        """Esta é a cópia principal: passa a ouvir as próximas."""
        QLocalServer.removeServer(self._name)   # resto de uma cópia que caiu sem fechar o canal
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        return self._server.listen(self._name)

    def _on_connection(self):
        while self._server and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._on_message(s))
            sock.disconnected.connect(sock.deleteLater)

    def _on_message(self, sock: QLocalSocket):
        if bytes(sock.readAll()).strip() == b"show":
            self.show_requested.emit()
