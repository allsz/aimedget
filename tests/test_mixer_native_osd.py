"""Mixer desligado: as teclas de volume não passam mais por nós e o OSD nativo do Windows volta a aparecer."""
from unittest import mock

import app.services.audio_mixer_service as ams
from test_audio_mixer_multidevice import make_service


def test_turning_the_mixer_off_removes_the_volume_key_hook_and_on_puts_it_back(monkeypatch):
    svc = make_service()
    fake_u32 = mock.Mock()
    svc._user32 = fake_u32
    monkeypatch.setattr(ams, "_ACTIVE_LL_HOOK", 1234)        # ligado: hook instalado
    installs = []
    monkeypatch.setattr(svc, "_install_volume_key_hook", lambda: installs.append(1) or setattr(ams, "_ACTIVE_LL_HOOK", 99))
    svc._pending_vk_actions.append(0xAF)

    svc.set_intercept_volume_keys(False)
    fake_u32.UnhookWindowsHookEx.assert_called_once_with(1234)
    assert not svc.is_intercepting_volume_keys()
    assert svc._pending_vk_actions == []                       # nenhuma tecla engolida fica para depois

    svc.set_intercept_volume_keys(False)                       # idempotente
    assert fake_u32.UnhookWindowsHookEx.call_count == 1

    svc.set_intercept_volume_keys(True)
    assert installs == [1] and svc.is_intercepting_volume_keys()
    svc.set_intercept_volume_keys(True)
    assert installs == [1]


def test_bridge_toggle_drives_the_hook():
    from app.hub.service_bridge import HubServiceBridge
    audio, flyout = mock.Mock(), mock.Mock()
    fake = mock.Mock(audio_service=audio, volume_flyout=flyout, _states={})
    HubServiceBridge.set_volume_mixer_enabled(fake, False)
    audio.set_intercept_volume_keys.assert_called_with(False)
    HubServiceBridge.set_volume_mixer_enabled(fake, True)
    audio.set_intercept_volume_keys.assert_called_with(True)
