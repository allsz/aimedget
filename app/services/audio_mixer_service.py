import ctypes
import os
import time
import uuid
from ctypes import HRESULT, POINTER, byref, c_float, c_int, c_void_p, wintypes
from dataclasses import dataclass
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from app.services.mixer_sessions import SessionReading, choose_primary
from app.services.win_app_icon_extractor import (
    get_app_icon,
    get_parent_process_map,
    resolve_real_app_identity,
)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, guid_str: str):
        u = uuid.UUID(guid_str)
        super().__init__(
            u.time_low,
            u.time_mid,
            u.time_hi_version,
            (ctypes.c_ubyte * 8)(*u.bytes[8:]),
        )


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioEndpointVolume = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
IID_IAudioSessionManager2 = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
IID_IAudioSessionControl2 = GUID("{bfb7ff88-7239-4fc9-8fa2-07c950be9c6d}")
IID_ISimpleAudioVolume = GUID("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
SW_HIDE = 0
SW_MINIMIZE = 6

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


if hasattr(ctypes, "windll"):
    _u32 = ctypes.windll.user32
    _u32.SetWindowsHookExW.argtypes = [c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _u32.SetWindowsHookExW.restype = c_void_p
    _u32.CallNextHookEx.argtypes = [c_void_p, c_int, wintypes.WPARAM, wintypes.LPARAM]
    _u32.CallNextHookEx.restype = LRESULT
    _u32.UnhookWindowsHookEx.argtypes = [c_void_p]
    _u32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _u32.FindWindowExW.argtypes = [c_void_p, c_void_p, wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u32.FindWindowExW.restype = c_void_p
    _u32.ShowWindow.argtypes = [c_void_p, c_int]
    _u32.ShowWindow.restype = wintypes.BOOL

# Guarda referência global ao hook ativo para garantir desregistro limpo em Live Reload
_ACTIVE_LL_HOOK: int | None = None
_ACTIVE_HOOK_PROC = None


def _vcall(obj_ptr: c_void_p, vtable_idx: int, restype, *argtypes):
    vtbl = ctypes.cast(obj_ptr, POINTER(POINTER(c_void_p))).contents
    func_ptr = vtbl[vtable_idx]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(func_ptr)


def _com_release(obj_ptr: c_void_p):
    if obj_ptr and obj_ptr.value:
        try:
            _vcall(obj_ptr, 2, wintypes.ULONG)(obj_ptr)
        except Exception:
            pass
        obj_ptr.value = None


@dataclass
class AppAudioSession:
    """Representa um aplicativo no Mixer de Volume com ícone nativo resolvido."""
    app_id: str
    name: str
    volume: int          # 0 a 100
    is_muted: bool
    icon: QImage
    is_system_sounds: bool = False


class AudioMixerService(QObject):
    """
    Serviço em background para controle de volume Master e por Aplicativo via CoreAudio (COM)
    e monitoramento de teclas multimídia de volume (VK_VOLUME_UP / DOWN / MUTE).
    Segue a diretriz anti-monolito: zero código de UI, emitindo apenas sinais Qt.
    """

    # Emite (volume_0_100: int, is_muted: bool)
    master_volume_changed = Signal(int, bool)
    # Emite lista de AppAudioSession ordenada e sem duplicatas
    sessions_updated = Signal(list)
    # Emite (volume_0_100: int, is_muted: bool) quando o OSD deve aparecer na tela
    osd_requested = Signal(int, bool)

    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ole32 = ctypes.windll.ole32 if hasattr(ctypes, "windll") else None
        self._user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

        if self._ole32:
            self._ole32.CoInitializeEx(None, 2)   # COINIT_APARTMENTTHREADED (STA): igual ao modo da thread principal do Qt

        self._ep_vol_ptr = c_void_p()      # volume geral = do dispositivo PADRÃO do Windows
        # Um app pode ter sessões em vários dispositivos (ex.: Chrome roteado para o fone): o mixer lê e altera as
        # sessões de TODOS os dispositivos de saída ativos, não só do padrão (ver mixer_sessions.py)
        self._enum_ptr = c_void_p()        # IMMDeviceEnumerator (mantido vivo)
        self._default_dev_id = ""          # id do dispositivo padrão atual, para perceber quando o usuário o troca
        self._dev_mgrs: list[tuple[str, c_void_p]] = []   # (id do dispositivo, IAudioSessionManager2)
        self._dev_mgrs_at = 0.0
        self._default_check_at = 0.0
        self._route_resolver = None        # app_id -> id do dispositivo roteado (fornecido pelo serviço de rotas)
        self._route_cache: dict[str, tuple[float, str | None]] = {}
        self._init_com_interfaces()

        self._master_vol = self.get_master_volume()
        self._master_muted = self.get_master_mute()
        self._last_internal_set_time = 0.0
        self._last_key_trigger_time = 0.0
        self._pending_vk_actions: list[int] = []

        # Ordem estável dos aplicativos para evitar que linhas pulem durante o uso
        self._app_order: list[str] = []
        self._cached_sessions: list[AppAudioSession] = []
        self._app_pids: dict[str, set[int]] = {}

        # Instala o Low-Level Keyboard Hook (WH_KEYBOARD_LL) para interceptar e suprimir
        # as teclas de volume antes que o explorer.exe exiba o OSD nativo do Windows
        self._install_volume_key_hook()
        self._suppress_native_osd_window()

        # Timer rápido (20ms) para processar teclas interceptadas e sincronizar Master Volume
        self._fast_timer = QTimer(self)
        self._fast_timer.setInterval(20)
        self._fast_timer.timeout.connect(self._poll_master_and_keys)
        self._fast_timer.start()

        # Timer moderado (450ms) para sincronizar sessões de aplicativos no mixer
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(450)
        self._session_timer.timeout.connect(self.refresh_sessions)
        self._session_timer.start()

        self.refresh_sessions()

    def _install_volume_key_hook(self):
        """
        Registra um hook global WH_KEYBOARD_LL que intercepta VK_VOLUME_UP, VK_VOLUME_DOWN e VK_VOLUME_MUTE,
        retornando 1 para impedir que o Windows Explorer desenhe o flyout nativo por cima do nosso.
        """
        global _ACTIVE_LL_HOOK, _ACTIVE_HOOK_PROC
        if not self._user32:
            return

        if _ACTIVE_LL_HOOK:
            try:
                self._user32.UnhookWindowsHookEx(_ACTIVE_LL_HOOK)
            except Exception:
                pass
            _ACTIVE_LL_HOOK = None

        def _ll_proc(n_code: int, w_param: int, l_param: int) -> int:
            try:
                if n_code >= 0 and l_param:
                    kb = ctypes.cast(l_param, POINTER(KBDLLHOOKSTRUCT)).contents
                    vk = kb.vkCode
                    if vk in (self.VK_VOLUME_UP, self.VK_VOLUME_DOWN, self.VK_VOLUME_MUTE):
                        if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            self._pending_vk_actions.append(int(vk))
                        # Retorna 1 para engolir o evento e suprimir 100% o OSD nativo do Windows!
                        return 1
            except Exception:
                pass
            return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

        _ACTIVE_HOOK_PROC = HOOKPROC(_ll_proc)
        _ACTIVE_LL_HOOK = self._user32.SetWindowsHookExW(WH_KEYBOARD_LL, _ACTIVE_HOOK_PROC, None, 0)

    def _suppress_native_osd_window(self):
        """Oculta preventivamente qualquer host NativeHWNDHost -> DirectUIHWND legado do Windows."""
        if not self._user32:
            return
        try:
            hwnd = None
            while True:
                hwnd = self._user32.FindWindowExW(None, hwnd, "NativeHWNDHost", "")
                if not hwnd:
                    break
                child = self._user32.FindWindowExW(hwnd, None, "DirectUIHWND", "")
                if child:
                    self._user32.ShowWindow(hwnd, SW_MINIMIZE)
                    self._user32.ShowWindow(hwnd, SW_HIDE)
        except Exception:
            pass

    def stop(self):
        global _ACTIVE_LL_HOOK
        self._fast_timer.stop()
        self._session_timer.stop()
        if self._user32 and _ACTIVE_LL_HOOK:
            try:
                self._user32.UnhookWindowsHookEx(_ACTIVE_LL_HOOK)
            except Exception:
                pass
            _ACTIVE_LL_HOOK = None
        self._release_device_managers()
        _com_release(self._ep_vol_ptr)
        _com_release(self._enum_ptr)

    # --- Dispositivos ------------------------------------------------------------------------

    def _ensure_enumerator(self) -> bool:
        if self._enum_ptr.value:
            return True
        if not self._ole32:
            return False
        try:
            hr = self._ole32.CoCreateInstance(
                byref(CLSID_MMDeviceEnumerator), None, 7, byref(IID_IMMDeviceEnumerator), byref(self._enum_ptr)
            )
            return hr == 0 and bool(self._enum_ptr.value)
        except Exception:
            return False

    def _device_id(self, dev_ptr: c_void_p) -> str:
        """IMMDevice::GetId (ex.: '{0.0.0.00000000}.{guid}', o mesmo formato do serviço de rotas)."""
        raw = wintypes.LPWSTR()
        try:
            if _vcall(dev_ptr, 5, HRESULT, POINTER(wintypes.LPWSTR))(dev_ptr, byref(raw)) != 0:
                return ""
            return raw.value or ""
        except Exception:
            return ""
        finally:
            if raw and self._ole32:
                self._ole32.CoTaskMemFree(raw)

    def _current_default_device_id(self) -> str:
        """Id do dispositivo de saída padrão AGORA ("" se não houver)."""
        if not self._ensure_enumerator():
            return ""
        dev_ptr = c_void_p()
        try:
            hr = _vcall(self._enum_ptr, 4, HRESULT, c_int, c_int, POINTER(c_void_p))(
                self._enum_ptr, 0, 1, byref(dev_ptr)
            )
            if hr != 0 or not dev_ptr.value:
                return ""
            return self._device_id(dev_ptr)
        except Exception:
            return ""
        finally:
            _com_release(dev_ptr)

    def _check_default_device(self, now: float):
        """O usuário trocou o dispositivo padrão do Windows? Então o volume geral passa a ser o do novo (1x por segundo)."""
        if now - self._default_check_at < 1.0:
            return
        self._default_check_at = now
        current = self._current_default_device_id()
        if current and current != self._default_dev_id:
            self._init_com_interfaces()

    def _release_device_managers(self):
        for _dev_id, mgr in self._dev_mgrs:
            _com_release(mgr)
        self._dev_mgrs = []

    def _device_managers(self) -> list[tuple[str, c_void_p]]:
        """
        (id, IAudioSessionManager2) de cada dispositivo de saída ATIVO. Reenumerado a cada 2 s (fones Bluetooth/USB
        entram e saem) ou quando o padrão muda.
        """
        now = time.perf_counter()
        if self._dev_mgrs and now - self._dev_mgrs_at < 2.0:
            return self._dev_mgrs
        self._release_device_managers()
        self._dev_mgrs_at = now
        if not self._ensure_enumerator():
            return self._dev_mgrs
        coll = c_void_p()
        try:
            # IMMDeviceEnumerator::EnumAudioEndpoints(eRender=0, DEVICE_STATE_ACTIVE=1)
            hr = _vcall(self._enum_ptr, 3, HRESULT, c_int, wintypes.DWORD, POINTER(c_void_p))(
                self._enum_ptr, 0, 1, byref(coll)
            )
            if hr != 0 or not coll.value:
                return self._dev_mgrs
            count = ctypes.c_uint()
            _vcall(coll, 3, HRESULT, POINTER(ctypes.c_uint))(coll, byref(count))
            for i in range(count.value):
                dev = c_void_p()
                try:
                    if _vcall(coll, 4, HRESULT, ctypes.c_uint, POINTER(c_void_p))(coll, i, byref(dev)) != 0 \
                            or not dev.value:
                        continue
                    dev_id = self._device_id(dev)
                    mgr = c_void_p()
                    hr = _vcall(
                        dev, 3, HRESULT, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p)
                    )(dev, byref(IID_IAudioSessionManager2), 7, None, byref(mgr))
                    if hr == 0 and mgr.value:
                        self._dev_mgrs.append((dev_id, mgr))
                finally:
                    _com_release(dev)
        except Exception:
            pass
        finally:
            _com_release(coll)
        return self._dev_mgrs

    # --- Rotas (para saber qual sessão mostrar quando o app está em vários dispositivos) ------

    def set_route_resolver(self, resolver):
        """`resolver(app_id) -> id do dispositivo de saída` (ou '__default__'): vem do serviço de rotas."""
        self._route_resolver = resolver
        self._route_cache.clear()

    def on_app_route_changed(self, app_id: str, flow: str, device_id: str):
        """O usuário trocou a saída de um app no mixer: a próxima leitura já usa a rota nova."""
        if flow == "output":
            routed = None if not device_id or device_id == "__default__" else device_id
            self._route_cache[app_id] = (time.perf_counter(), routed)

    def _routed_device(self, app_id: str, readings: list[SessionReading]) -> str | None:
        """Só consulta a rota quando ela decide algo (sessões em 2+ dispositivos e nenhuma tocando); cache de 5 s."""
        if self._route_resolver is None or any(r.active for r in readings) \
                or len({r.device_id for r in readings}) < 2:
            return None
        now = time.perf_counter()
        cached = self._route_cache.get(app_id)
        if cached is not None and now - cached[0] < 5.0:
            return cached[1]
        try:
            dev = self._route_resolver(app_id)
        except Exception:
            dev = None
        routed = None if not dev or dev == "__default__" else dev
        self._route_cache[app_id] = (now, routed)
        return routed

    def _init_com_interfaces(self):
        """(Re)abre o volume geral do dispositivo PADRÃO atual e anota qual ele é."""
        if not self._ole32:
            return
        _com_release(self._ep_vol_ptr)
        self._dev_mgrs_at = 0.0   # força reenumerar os dispositivos na próxima leitura

        dev_ptr = c_void_p()
        try:
            if not self._ensure_enumerator():
                return
            # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eMultimedia=1)
            hr = _vcall(self._enum_ptr, 4, HRESULT, c_int, c_int, POINTER(c_void_p))(
                self._enum_ptr, 0, 1, byref(dev_ptr)
            )
            if hr != 0 or not dev_ptr.value:
                _com_release(self._enum_ptr)   # enumerador inválido (ex.: serviço de áudio reiniciado): recria depois
                return
            self._default_dev_id = self._device_id(dev_ptr)

            # Ativa IAudioEndpointVolume
            _vcall(
                dev_ptr, 3, HRESULT, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p)
            )(dev_ptr, byref(IID_IAudioEndpointVolume), 7, None, byref(self._ep_vol_ptr))
            # (As sessões de áudio vêm de _device_managers(), que cobre o padrão e os demais dispositivos.)
        except Exception:
            pass
        finally:
            _com_release(dev_ptr)

    def get_master_volume(self) -> int:
        if not self._ep_vol_ptr.value:
            self._init_com_interfaces()
        if not self._ep_vol_ptr.value:
            return 50
        try:
            val = c_float()
            hr = _vcall(self._ep_vol_ptr, 9, HRESULT, POINTER(c_float))(self._ep_vol_ptr, byref(val))
            if hr == 0:
                return int(round(max(0.0, min(1.0, val.value)) * 100))
        except Exception:
            self._init_com_interfaces()
        return getattr(self, "_master_vol", 50)

    def get_master_mute(self) -> bool:
        if not self._ep_vol_ptr.value:
            return False
        try:
            muted = wintypes.BOOL()
            hr = _vcall(self._ep_vol_ptr, 15, HRESULT, POINTER(wintypes.BOOL))(
                self._ep_vol_ptr, byref(muted)
            )
            if hr == 0:
                return bool(muted.value)
        except Exception:
            pass
        return getattr(self, "_master_muted", False)

    def set_master_volume(self, volume: int, from_ui: bool = True):
        """Define o volume principal do Windows (0 a 100)."""
        vol_clamped = max(0, min(100, int(round(volume))))
        self._master_vol = vol_clamped
        if from_ui:
            self._last_internal_set_time = time.perf_counter()

        if not self._ep_vol_ptr.value:
            self._init_com_interfaces()
        if self._ep_vol_ptr.value:
            try:
                scalar = c_float(vol_clamped / 100.0)
                _vcall(self._ep_vol_ptr, 7, HRESULT, c_float, c_void_p)(
                    self._ep_vol_ptr, scalar, None
                )
                if vol_clamped > 0 and self._master_muted:
                    self._master_muted = False
                    _vcall(self._ep_vol_ptr, 14, HRESULT, wintypes.BOOL, c_void_p)(
                        self._ep_vol_ptr, wintypes.BOOL(False), None
                    )
            except Exception:
                pass
        self.master_volume_changed.emit(self._master_vol, self._master_muted)

    def toggle_master_mute(self):
        """Alterna o estado de mudo do volume principal do sistema."""
        new_mute = not self._master_muted
        self._master_muted = new_mute
        self._last_internal_set_time = time.perf_counter()
        if self._ep_vol_ptr.value:
            try:
                _vcall(self._ep_vol_ptr, 14, HRESULT, wintypes.BOOL, c_void_p)(
                    self._ep_vol_ptr, wintypes.BOOL(new_mute), None
                )
            except Exception:
                pass
        self.master_volume_changed.emit(self._master_vol, self._master_muted)

    def set_app_volume(self, app_id: str, volume: int):
        """Define o volume (0 a 100) de todas as sessões pertencentes ao aplicativo `app_id`."""
        vol_clamped = max(0, min(100, int(round(volume))))
        for s in self._cached_sessions:
            if s.app_id == app_id:
                s.volume = vol_clamped
                if vol_clamped > 0 and s.is_muted:
                    s.is_muted = False
        self._apply_to_matching_sessions(app_id, volume=vol_clamped)

    def toggle_app_mute(self, app_id: str):
        """Alterna mudo para todas as sessões de um aplicativo específico."""
        target_mute = None
        for s in self._cached_sessions:
            if s.app_id == app_id:
                s.is_muted = not s.is_muted
                target_mute = s.is_muted
                break
        if target_mute is not None:
            self._apply_to_matching_sessions(app_id, mute=target_mute)
            self.sessions_updated.emit(list(self._cached_sessions))

    def _poll_master_and_keys(self):
        now = time.perf_counter()

        # 1. Processa imediatamente teclas interceptadas pelo hook WH_KEYBOARD_LL
        if self._pending_vk_actions:
            actions = self._pending_vk_actions[:]
            self._pending_vk_actions.clear()
            for vk in actions:
                if vk == self.VK_VOLUME_MUTE:
                    self.toggle_master_mute()
                elif vk == self.VK_VOLUME_UP:
                    self.set_master_volume(min(100, self._master_vol + 2), from_ui=True)
                elif vk == self.VK_VOLUME_DOWN:
                    self.set_master_volume(max(0, self._master_vol - 2), from_ui=True)
            self._last_key_trigger_time = now
            self.osd_requested.emit(self._master_vol, self._master_muted)
            return

        # 2. Se o usuário trocou o dispositivo padrão do Windows, o volume geral passa a ser o do novo
        self._check_default_device(now)

        # 3. Sincroniza caso o volume tenha sido alterado por outro meio externo
        cur_vol = self.get_master_volume()
        cur_mute = self.get_master_mute()
        vol_changed = (cur_vol != self._master_vol) or (cur_mute != self._master_muted)

        if vol_changed:
            self._master_vol = cur_vol
            self._master_muted = cur_mute
            self.master_volume_changed.emit(cur_vol, cur_mute)
            if (now - getattr(self, "_last_internal_set_time", 0.0)) > 0.15:
                self.osd_requested.emit(cur_vol, cur_mute)
                self._last_key_trigger_time = now

    def _for_each_session(self, mgr2: c_void_p, proc_map, visit, include_expired: bool = False):
        """
        Chama `visit(app_id, exe_path, is_sys, ctrl2, svol, state)` para cada sessão do IAudioSessionManager2
        (sessões sem app identificado são puladas). Os objetos COM são liberados ao fim de cada sessão.
        """
        sess_enum = c_void_p()
        try:
            hr = _vcall(mgr2, 5, HRESULT, POINTER(c_void_p))(mgr2, byref(sess_enum))
            if hr != 0 or not sess_enum.value:
                return
            count = c_int()
            _vcall(sess_enum, 3, HRESULT, POINTER(c_int))(sess_enum, byref(count))
            for i in range(count.value):
                ctrl = c_void_p()
                ctrl2 = c_void_p()
                svol = c_void_p()
                try:
                    if _vcall(sess_enum, 4, HRESULT, c_int, POINTER(c_void_p))(
                        sess_enum, i, byref(ctrl)
                    ) != 0 or not ctrl.value:
                        continue
                    _vcall(ctrl, 0, HRESULT, POINTER(GUID), POINTER(c_void_p))(
                        ctrl, byref(IID_IAudioSessionControl2), byref(ctrl2)
                    )
                    _vcall(ctrl, 0, HRESULT, POINTER(GUID), POINTER(c_void_p))(
                        ctrl, byref(IID_ISimpleAudioVolume), byref(svol)
                    )
                    if not ctrl2.value or not svol.value:
                        continue
                    state = c_int()
                    _vcall(ctrl2, 3, HRESULT, POINTER(c_int))(ctrl2, byref(state))
                    # AudioSessionStateExpired == 2
                    if state.value == 2 and not include_expired:
                        continue
                    app_id, exe_path, is_sys = self._identify_session(ctrl2, proc_map)
                    if not app_id:
                        continue
                    visit(app_id, exe_path, is_sys, ctrl2, svol, state.value)
                except Exception:
                    continue
                finally:
                    _com_release(svol)
                    _com_release(ctrl2)
                    _com_release(ctrl)
        except Exception:
            pass
        finally:
            _com_release(sess_enum)

    def _write_session(self, svol: c_void_p, volume: int | None, mute: bool | None):
        """ISimpleAudioVolume: SetMasterVolume (3) e SetMute (5)."""
        if volume is not None:
            _vcall(svol, 3, HRESULT, c_float, c_void_p)(svol, c_float(volume / 100.0), None)
            if volume > 0:
                _vcall(svol, 5, HRESULT, wintypes.BOOL, c_void_p)(svol, wintypes.BOOL(False), None)
        if mute is not None:
            _vcall(svol, 5, HRESULT, wintypes.BOOL, c_void_p)(svol, wintypes.BOOL(mute), None)

    def _apply_to_matching_sessions(
        self, target_app_id: str, volume: int | None = None, mute: bool | None = None
    ) -> int:
        """
        Aplica volume/mudo em TODAS as sessões do app, em todos os dispositivos de saída (ex.: o Chrome nas caixas e
        no fone). Devolve quantas sessões foram alteradas.
        """
        managers = self._device_managers()
        if not managers:
            return 0
        proc_map = get_parent_process_map()
        changed = [0]

        def visit(app_id, _exe, _is_sys, _ctrl2, svol, _state):
            if app_id == target_app_id:
                self._write_session(svol, volume, mute)
                changed[0] += 1

        for _dev_id, mgr in managers:
            self._for_each_session(mgr, proc_map, visit, include_expired=True)
        return changed[0]

    def _identify_session(
        self, ctrl2: c_void_p, proc_map: dict[int, tuple[int, str]]
    ) -> tuple[str, str, bool]:
        """Retorna (app_id, exe_path, is_system_sounds) para uma sessão IAudioSessionControl2."""
        pid = wintypes.DWORD()
        _vcall(ctrl2, 14, HRESULT, POINTER(wintypes.DWORD))(ctrl2, byref(pid))
        is_sys_hr = _vcall(ctrl2, 15, HRESULT)(ctrl2)

        disp_ptr = wintypes.LPWSTR()
        _vcall(ctrl2, 4, HRESULT, POINTER(wintypes.LPWSTR))(ctrl2, byref(disp_ptr))
        disp_str = (disp_ptr.value or "") if disp_ptr else ""
        if disp_ptr and self._ole32:
            self._ole32.CoTaskMemFree(disp_ptr)

        if is_sys_hr == 0 or pid.value == 0 or "audiosrv.dll" in disp_str.lower():
            return "__system_sounds__", "", True

        app_key, best_path = resolve_real_app_identity(int(pid.value), proc_map)
        if not app_key:
            return "", "", False
        return app_key, best_path, False

    def refresh_sessions(self):
        """
        Enumera as sessões de áudio de TODOS os dispositivos de saída ativos, agrupa por aplicativo e escolhe a sessão
        que representa cada app (a que toca; senão a do dispositivo roteado; senão a do padrão: mixer_sessions.py).
        """
        if not self._ep_vol_ptr.value:
            self._init_com_interfaces()
        managers = self._device_managers()
        if not managers:
            return

        proc_map = get_parent_process_map()
        readings: dict[str, list[SessionReading]] = {}
        identity: dict[str, tuple[str, bool]] = {}     # app_id -> (exe_path, is_sys), da 1ª sessão vista
        found_pids: dict[str, set[int]] = {}

        for dev_id, mgr in managers:
            def visit(app_id, exe_path, is_sys, ctrl2, svol, state, dev_id=dev_id):
                # Mapeia os PIDs reais associados a este aplicativo
                sess_pid = wintypes.DWORD()
                _vcall(ctrl2, 14, HRESULT, POINTER(wintypes.DWORD))(ctrl2, byref(sess_pid))
                if sess_pid.value:
                    found_pids.setdefault(app_id, set()).add(int(sess_pid.value))

                vol = c_float()
                _vcall(svol, 4, HRESULT, POINTER(c_float))(svol, byref(vol))
                muted = wintypes.BOOL()
                _vcall(svol, 6, HRESULT, POINTER(wintypes.BOOL))(svol, byref(muted))
                readings.setdefault(app_id, []).append(SessionReading(
                    device_id=dev_id,
                    volume=int(round(max(0.0, min(1.0, vol.value)) * 100)),
                    muted=bool(muted.value),
                    active=(state == 1),       # AudioSessionStateActive
                ))
                identity.setdefault(app_id, (exe_path, is_sys))

            self._for_each_session(mgr, proc_map, visit)

        found_by_id: dict[str, AppAudioSession] = {}
        for app_id, app_readings in readings.items():
            primary = choose_primary(app_readings, self._default_dev_id, self._routed_device(app_id, app_readings))
            exe_path, is_sys = identity[app_id]
            friendly = "Sons do Sistema" if is_sys else os.path.splitext(os.path.basename(exe_path))[0]
            found_by_id[app_id] = AppAudioSession(
                app_id=app_id,
                name=friendly,
                volume=primary.volume,
                is_muted=primary.muted,
                icon=get_app_icon(exe_path, is_system_sounds=is_sys),
                is_system_sounds=is_sys,
            )

        self._app_pids = found_pids

        # Mantém ordem estável para os apps já conhecidos
        for app_id in found_by_id:
            if app_id not in self._app_order:
                self._app_order.append(app_id)
        self._app_order = [aid for aid in self._app_order if aid in found_by_id]

        ordered = [found_by_id[aid] for aid in self._app_order]
        self._cached_sessions = ordered
        self.sessions_updated.emit(ordered)

    def get_cached_sessions(self) -> list[AppAudioSession]:
        """Sessões de aplicativos conhecidas (atualizadas a cada ~450 ms)."""
        return list(self._cached_sessions)

    def get_app_pids(self, app_id: str) -> list[int]:
        """Retorna os PIDs ativos no Windows que possuem sessões de áudio para este aplicativo."""
        return list(self._app_pids.get(app_id, set()))
