"""
Dispensa da abertura automática do Music Widget.

Problema: com "abrir ao detectar música" ligado, esconder o widget (Win+Alt+M) enquanto a
música toca fazia o widget reaparecer no ciclo seguinte, porque a música continua tocando.

Solução: ao esconder pelo atalho com uma música em andamento, o widget lembra que você o
dispensou para esta SESSÃO DE ESCUTA e suspende a abertura automática. A preferência do usuário
não é alterada. A dispensa termina quando:
  1. a mídia some (nenhuma sessão ativa);
  2. a reprodução fica parada/pausada por 30 s ou mais;
  3. outro player começa a tocar (é uma intenção nova);
  4. o usuário abre o widget pelo atalho (quem manda é sempre o manual).
Trocar de faixa não encerra a dispensa. Nada é salvo em disco: ao reiniciar o app, vale a
abertura automática de sempre.
"""

import time
from typing import Callable

PAUSE_RESET_S = 30.0


class AutoOpenDismissal:
    def __init__(self, clock: Callable[[], float] = time.monotonic, pause_reset_s: float = PAUSE_RESET_S):
        self._clock = clock
        self._pause_reset_s = pause_reset_s
        self.active = False
        self._source = ""
        self._idle_since: float | None = None

    def dismiss(self, source: str, playing: bool):
        """O usuário escondeu o widget durante uma sessão de escuta."""
        self.active = True
        self._source = source or ""
        self._idle_since = None if playing else self._clock()

    def clear(self):
        self.active = False
        self._source = ""
        self._idle_since = None

    def observe(self, has_media: bool, is_playing: bool, source: str):
        """Atualiza a dispensa a cada notificação de mídia; pode encerrá-la."""
        if not self.active:
            return
        if not has_media:
            self.clear()                              # a sessão de escuta acabou
            return
        if is_playing:
            if self._source and source and source != self._source:
                self.clear()                          # outro player começou a tocar
                return
            self._idle_since = None
            return
        now = self._clock()
        if self._idle_since is None:
            self._idle_since = now
        elif now - self._idle_since >= self._pause_reset_s:
            self.clear()                              # parado tempo demais: sessão nova ao voltar
