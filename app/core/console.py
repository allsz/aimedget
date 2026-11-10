"""
Console à prova de caracteres que ele não sabe escrever.

O console do Windows costuma usar cp1252, que não tem japonês, aspas tipográficas nem emoji. Um `print` com o título de
uma música assim levanta UnicodeEncodeError e, numa thread (como a da mídia), mata a thread inteira. Aqui o stdout/stderr
passa a SUBSTITUIR o que não consegue escrever ("?") em vez de falhar. Deve ser chamado uma vez, no começo do programa.
"""

import sys


def make_console_safe() -> None:
    for stream in (sys.stdout, sys.stderr):
        # Sem console (app empacotado sem janela de terminal) o stream é None; streams trocados podem não ter reconfigure
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass
