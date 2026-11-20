"""Indicador de Lock Keys desligado: o serviço para de consultar o teclado (nada de acordar 40x/s à toa)."""
import sys

from PySide6.QtCore import QCoreApplication

from app.services.keylock_service import KeyLockService


def test_stop_pauses_polling_and_start_resyncs_without_a_stale_event():
    QCoreApplication.instance() or QCoreApplication(sys.argv)
    svc = KeyLockService()
    caps = {"on": False}
    svc.is_caps_lock_on = lambda: caps["on"]
    svc.is_num_lock_on = lambda: False
    svc._caps_on = False
    seen = []
    svc.keylock_changed.connect(lambda k, v: seen.append((k, v)))
    assert svc.is_active()

    svc.stop()
    assert not svc.is_active()
    caps["on"] = True                 # mudou com o indicador desligado
    svc.start()
    assert svc.is_active()
    svc._poll_keys()
    assert seen == []                 # ao religar, não "avisa" uma troca que ninguém viu

    caps["on"] = False
    svc._poll_keys()
    assert seen == [("Caps Lock", False)]
    svc.stop()
