"""
Configuração comum da suíte.

Os testes NÃO leem a mídia que estiver tocando no PC. Todo MusicWidgetController sem worker injetado (e a ponte
global do Hub) cria um WindowsMediaWorker real, cuja thread consulta o GSMTC do Windows a cada 0,35 s e emite a
música do momento. Essas threads ficavam vivas pela suíte inteira e entregavam mídia real (ex.: YouTube Music no
Firefox) a widgets que outros testes estavam animando ou fechando: o processo caía de forma intermitente (access
violation), e o resultado dependia do que tocava na máquina. Aqui a thread de fundo não é iniciada; o resto do
worker (classificação, posição, comandos) continua testável chamando os métodos diretamente.
"""

try:
    from app.services import media_worker as _media_worker
except ModuleNotFoundError:   # sem winrt (dependências do app não instaladas): nada a desligar
    _media_worker = None

if _media_worker is not None:
    _media_worker.WindowsMediaWorker._thread_main = lambda self: None
