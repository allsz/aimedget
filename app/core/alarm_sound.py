"""
Som de fim do Timer. Toca o arquivo em assets/sounds (em vez do aviso padrão do Windows), sem travar a interface.
O arquivo está em 16 bits porque o player simples do Windows (`winsound`) não toca 24 bits.
"""

import logging
import os

from app.core.paths import ASSETS_DIR

logger = logging.getLogger(__name__)

# O nome do arquivo é mantido como veio do autor (ver assets/sounds/CREDITS.md)
ALARM_FILE = os.path.join(ASSETS_DIR, "sounds", "723169__mitchellsloan__vinnies-glock-e1.wav")


def play_alarm(path: str = ALARM_FILE) -> bool:
    """Toca o som do alarme em segundo plano. Se o arquivo faltar ou falhar, usa o aviso do Windows: o alarme não
    pode ficar mudo. Devolve True se tocou o arquivo."""
    try:
        import winsound
        if os.path.isfile(path):
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return True
        logger.warning("Som do alarme não encontrado: %s", path)
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception as exc:
        logger.warning("Não foi possível tocar o som do alarme: %s", exc)
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
    return False


def stop_alarm():
    """Interrompe o som do alarme se ainda estiver tocando (ao iniciar ou reiniciar o Timer)."""
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
