import ctypes
import os
import uuid
from ctypes import HRESULT, POINTER, byref, c_int, c_ushort, c_void_p, wintypes
from dataclasses import dataclass
from PySide6.QtCore import QObject, QTimer, Signal

from app.services.win_app_icon_extractor import get_parent_process_map


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


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


PKEY_Device_FriendlyName = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", c_ushort),
        ("wReserved1", wintypes.WORD),
        ("wReserved2", wintypes.WORD),
        ("wReserved3", wintypes.WORD),
        ("pwszVal", wintypes.LPWSTR),
    ]


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioPolicyConfigFactory = GUID("{ab3d4648-e242-459f-b02f-541c70306324}")

DEVINTERFACE_AUDIO_RENDER = "#{e6327cad-dcec-4949-ae8a-991e976a79d2}"
DEVINTERFACE_AUDIO_CAPTURE = "#{2eef81be-33fa-4800-9670-1cd474972c3f}"
MMDEVAPI_TOKEN = r"\\?\SWD#MMDEVAPI#"

HSTRING = c_void_p
_combase = getattr(ctypes.windll, "combase", None) if hasattr(ctypes, "windll") else None
_WindowsCreateString = None
_WindowsDeleteString = None
_WindowsGetStringRawBuffer = None
_RoGetActivationFactory = None

if _combase:
    try:
        # RO_INIT_SINGLETHREADED (0) = STA, o mesmo modo que o Qt usa na thread principal. Com RO_INIT_MULTITHREADED (1)
        # a thread principal virava MTA ANTES do QApplication: o Qt não conseguia iniciar o OLE ("OleInitialize() failed")
        # e o seletor de arquivo nativo do Windows travava o app ao fechar.
        _combase.RoInitialize(0)
    except Exception:
        pass
    _WindowsCreateString = _combase.WindowsCreateString
    _WindowsCreateString.argtypes = [wintypes.LPCWSTR, ctypes.c_uint32, POINTER(HSTRING)]
    _WindowsCreateString.restype = c_int

    _WindowsDeleteString = _combase.WindowsDeleteString
    _WindowsDeleteString.argtypes = [HSTRING]
    _WindowsDeleteString.restype = c_int

    _WindowsGetStringRawBuffer = _combase.WindowsGetStringRawBuffer
    _WindowsGetStringRawBuffer.argtypes = [HSTRING, POINTER(ctypes.c_uint32)]
    _WindowsGetStringRawBuffer.restype = wintypes.LPCWSTR

    _RoGetActivationFactory = _combase.RoGetActivationFactory
    _RoGetActivationFactory.argtypes = [HSTRING, POINTER(GUID), POINTER(c_void_p)]
    _RoGetActivationFactory.restype = c_int


def _vcall(obj_ptr: c_void_p, vtable_idx: int, restype, *argtypes):
    vtbl = ctypes.cast(obj_ptr, POINTER(POINTER(c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(vtbl[vtable_idx])


def _com_release(obj_ptr: c_void_p):
    if obj_ptr and obj_ptr.value:
        try:
            _vcall(obj_ptr, 2, wintypes.ULONG)(obj_ptr)
        except Exception:
            pass
        obj_ptr.value = None


@dataclass
class AudioEndpoint:
    """Representa um dispositivo de áudio (Saída ou Entrada)."""
    device_id: str
    name: str
    flow: str  # "output" ou "input"
    is_default: bool = False


class AudioEndpointService(QObject):
    """
    Serviço modular para enumeração de dispositivos de áudio físicos (Saída/Entrada)
    e gerenciamento do roteamento nativo de áudio por aplicativo no Windows (CoreAudio / WinRT).
    Segue a regra de arquitetura: zero código de UI, focado em dispositivos.
    """

    endpoints_updated = Signal()
    app_routing_changed = Signal(str, str, str)  # (app_id, flow, device_id)

    DEFAULT_ID = "__default__"

    def __init__(self, mixer_service: QObject | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._mixer_service = mixer_service
        self._policy_factory = c_void_p()

        self._ole32 = ctypes.windll.ole32 if hasattr(ctypes, "windll") else None
        if self._ole32:
            self._ole32.CoInitializeEx(None, 2)   # COINIT_APARTMENTTHREADED (STA): igual ao modo da thread principal do Qt

        self._init_winrt_policy()

        # Mapeamento em memória do roteamento por aplicativo:
        # { app_id: { "output": device_id, "input": device_id } }
        self._app_routing_map: dict[str, dict[str, str]] = {}

        self._cached_outputs: list[AudioEndpoint] = []
        self._cached_inputs: list[AudioEndpoint] = []

        self.refresh_endpoints()

        # Polling moderado (2.5s) para detectar se fones Bluetooth/USB foram conectados/desconectados
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2500)
        self._poll_timer.timeout.connect(self.refresh_endpoints)
        self._poll_timer.start()

    def set_mixer_service(self, mixer_service: QObject | None):
        """Atualiza a referência ao AudioMixerService para obter PIDs ativos."""
        self._mixer_service = mixer_service

    def _init_winrt_policy(self):
        """Inicializa a fábrica IAudioPolicyConfigFactory via WinRT RoGetActivationFactory."""
        if not _RoGetActivationFactory or not _WindowsCreateString:
            return
        h_class = HSTRING()
        class_name = "Windows.Media.Internal.AudioPolicyConfig"
        try:
            if _WindowsCreateString(class_name, len(class_name), byref(h_class)) == 0 and h_class.value:
                factory = c_void_p()
                hr = _RoGetActivationFactory(h_class, byref(IID_IAudioPolicyConfigFactory), byref(factory))
                if hr == 0 and factory.value:
                    self._policy_factory = factory
        except Exception:
            pass
        finally:
            if h_class.value and _WindowsDeleteString:
                _WindowsDeleteString(h_class)

    def _set_persisted_endpoint(self, pid: int, flow_idx: int, role: int, device_id: str | None) -> bool:
        """Aplica a rota de áudio no Windows para um PID específico via IAudioPolicyConfigFactory."""
        if not self._policy_factory or not self._policy_factory.value:
            self._init_winrt_policy()
        if not self._policy_factory or not self._policy_factory.value:
            return False

        try:
            vtbl = ctypes.cast(self._policy_factory, POINTER(POINTER(c_void_p))).contents
            # Slot 25: SetPersistedDefaultAudioEndpoint(uint32 processId, int flow, int role, HSTRING deviceId)
            proto_set = ctypes.WINFUNCTYPE(c_int, c_void_p, wintypes.DWORD, c_int, c_int, HSTRING)
            set_func = proto_set(vtbl[25])

            if not device_id or device_id == self.DEFAULT_ID:
                hr = set_func(self._policy_factory, wintypes.DWORD(pid), c_int(flow_idx), c_int(role), HSTRING(None))
                return hr == 0
            else:
                suffix = DEVINTERFACE_AUDIO_RENDER if flow_idx == 0 else DEVINTERFACE_AUDIO_CAPTURE
                formatted = f"{MMDEVAPI_TOKEN}{device_id}{suffix}"
                h_dev = HSTRING()
                if _WindowsCreateString(formatted, len(formatted), byref(h_dev)) == 0 and h_dev.value:
                    hr = set_func(self._policy_factory, wintypes.DWORD(pid), c_int(flow_idx), c_int(role), h_dev)
                    _WindowsDeleteString(h_dev)
                    return hr == 0
        except Exception:
            pass
        return False

    def get_persisted_endpoint(self, pid: int, flow_idx: int = 0, role: int = 1) -> str:
        """Consulta o dispositivo atualmente persistido para o PID no Windows."""
        if not self._policy_factory or not self._policy_factory.value:
            self._init_winrt_policy()
        if not self._policy_factory or not self._policy_factory.value:
            return self.DEFAULT_ID

        try:
            vtbl = ctypes.cast(self._policy_factory, POINTER(POINTER(c_void_p))).contents
            # Slot 26: GetPersistedDefaultAudioEndpoint(uint32 processId, int flow, int role, POINTER(HSTRING))
            proto_get = ctypes.WINFUNCTYPE(c_int, c_void_p, wintypes.DWORD, c_int, c_int, POINTER(HSTRING))
            get_func = proto_get(vtbl[26])

            h_res = HSTRING()
            hr = get_func(self._policy_factory, wintypes.DWORD(pid), c_int(flow_idx), c_int(role), byref(h_res))
            if hr == 0 and h_res.value:
                raw_str = _WindowsGetStringRawBuffer(h_res, None)
                _WindowsDeleteString(h_res)
                if raw_str:
                    s = str(raw_str).replace(MMDEVAPI_TOKEN, "")
                    return s.split("#")[0]
        except Exception:
            pass
        return self.DEFAULT_ID

    def _find_all_pids_for_app(self, app_id: str) -> list[int]:
        """Obtém todos os PIDs ativos associados ao aplicativo (sessões ativas + processos em execução)."""
        pids: set[int] = set()
        if self._mixer_service and hasattr(self._mixer_service, "get_app_pids"):
            pids.update(self._mixer_service.get_app_pids(app_id))

        try:
            target_name = os.path.basename(app_id).lower()
            proc_map = get_parent_process_map()
            for pid, (_, exe_name) in proc_map.items():
                if exe_name.lower() == target_name:
                    pids.add(pid)
        except Exception:
            pass

        return list(pids)

    def get_endpoints(self, flow: str = "output") -> list[AudioEndpoint]:
        """Retorna a lista de dispositivos de Saída ou Entrada, com o Padrão do Windows sempre no topo."""
        if flow == "output":
            return list(self._cached_outputs)
        return list(self._cached_inputs)

    def get_app_device(self, app_id: str, flow: str = "output") -> str:
        """Retorna o device_id ativo para o aplicativo. Se não definido, consulta o Windows ou retorna DEFAULT_ID."""
        if app_id in self._app_routing_map and flow in self._app_routing_map[app_id]:
            return self._app_routing_map[app_id][flow]

        # Tenta sincronizar a partir das configurações salvas no próprio Windows
        pids = self._find_all_pids_for_app(app_id)
        flow_idx = 0 if flow == "output" else 1
        for pid in pids:
            dev = self.get_persisted_endpoint(pid, flow_idx, role=1)
            if dev and dev != self.DEFAULT_ID:
                if app_id not in self._app_routing_map:
                    self._app_routing_map[app_id] = {
                        "output": self.DEFAULT_ID,
                        "input": self.DEFAULT_ID,
                    }
                self._app_routing_map[app_id][flow] = dev
                return dev

        return self.DEFAULT_ID

    def set_app_device(
        self,
        app_id: str,
        flow: str,
        device_id: str,
        pids: list[int] | None = None,
    ):
        """Define e persiste o dispositivo para o aplicativo no Windows e emite sinal de atualização."""
        if app_id not in self._app_routing_map:
            self._app_routing_map[app_id] = {
                "output": self.DEFAULT_ID,
                "input": self.DEFAULT_ID,
            }

        self._app_routing_map[app_id][flow] = device_id

        # Aplica a rota real no Windows via IAudioPolicyConfigFactory
        target_pids = pids if pids is not None else self._find_all_pids_for_app(app_id)
        flow_idx = 0 if flow == "output" else 1

        for pid in target_pids:
            # Aplica para os papéis eMultimedia (1) e eConsole (0) do Windows
            self._set_persisted_endpoint(pid, flow_idx, role=1, device_id=device_id)
            self._set_persisted_endpoint(pid, flow_idx, role=0, device_id=device_id)
            if flow == "input":
                # Para microfone, aplica também a eCommunications (2)
                self._set_persisted_endpoint(pid, flow_idx, role=2, device_id=device_id)

        self.app_routing_changed.emit(app_id, flow, device_id)

    def refresh_endpoints(self):
        """Enumera os dispositivos de áudio ativos via CoreAudio IMMDeviceEnumerator."""
        if not self._ole32:
            return

        enum_ptr = c_void_p()
        try:
            hr = self._ole32.CoCreateInstance(
                byref(CLSID_MMDeviceEnumerator),
                None,
                7,
                byref(IID_IMMDeviceEnumerator),
                byref(enum_ptr),
            )
            if hr != 0 or not enum_ptr.value:
                return

            new_outputs = self._enum_flow(enum_ptr, flow_idx=0, flow_name="output")
            new_inputs = self._enum_flow(enum_ptr, flow_idx=1, flow_name="input")

            # Verifica se houve alteração na lista de dispositivos
            out_ids = [d.device_id for d in new_outputs]
            cur_out_ids = [d.device_id for d in self._cached_outputs]
            in_ids = [d.device_id for d in new_inputs]
            cur_in_ids = [d.device_id for d in self._cached_inputs]

            if out_ids != cur_out_ids or in_ids != cur_in_ids:
                self._cached_outputs = new_outputs
                self._cached_inputs = new_inputs
                self.endpoints_updated.emit()
        except Exception:
            pass
        finally:
            _com_release(enum_ptr)

    def _enum_flow(self, enum_ptr: c_void_p, flow_idx: int, flow_name: str) -> list[AudioEndpoint]:
        devices: list[AudioEndpoint] = [
            AudioEndpoint(
                device_id=self.DEFAULT_ID,
                name="Padrão do Windows",
                flow=flow_name,
                is_default=True,
            )
        ]

        # Obtém o ID do dispositivo padrão atual do sistema
        default_sys_id = ""
        def_dev = c_void_p()
        try:
            hr = _vcall(enum_ptr, 4, HRESULT, c_int, c_int, POINTER(c_void_p))(
                enum_ptr, flow_idx, 1, byref(def_dev)
            )
            if hr == 0 and def_dev.value:
                id_ptr = wintypes.LPWSTR()
                _vcall(def_dev, 5, HRESULT, POINTER(wintypes.LPWSTR))(def_dev, byref(id_ptr))
                default_sys_id = id_ptr.value or ""
                self._ole32.CoTaskMemFree(id_ptr)
        except Exception:
            pass
        finally:
            _com_release(def_dev)

        coll_ptr = c_void_p()
        try:
            hr = _vcall(enum_ptr, 3, HRESULT, c_int, wintypes.DWORD, POINTER(c_void_p))(
                enum_ptr, flow_idx, 1, byref(coll_ptr)
            )
            if hr != 0 or not coll_ptr.value:
                return devices

            count = c_int()
            _vcall(coll_ptr, 3, HRESULT, POINTER(c_int))(coll_ptr, byref(count))

            for i in range(count.value):
                dev_ptr = c_void_p()
                store_ptr = c_void_p()
                try:
                    if _vcall(coll_ptr, 4, HRESULT, wintypes.UINT, POINTER(c_void_p))(
                        coll_ptr, i, byref(dev_ptr)
                    ) != 0 or not dev_ptr.value:
                        continue

                    id_ptr = wintypes.LPWSTR()
                    _vcall(dev_ptr, 5, HRESULT, POINTER(wintypes.LPWSTR))(dev_ptr, byref(id_ptr))
                    dev_id = id_ptr.value or ""
                    self._ole32.CoTaskMemFree(id_ptr)

                    # IPropertyStore::GetValue para pegar o nome amigável
                    friendly_name = "Dispositivo de Áudio"
                    if _vcall(dev_ptr, 4, HRESULT, wintypes.DWORD, POINTER(c_void_p))(
                        dev_ptr, 0, byref(store_ptr)
                    ) == 0 and store_ptr.value:
                        pv = PROPVARIANT()
                        if _vcall(
                            store_ptr, 5, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT)
                        )(store_ptr, byref(PKEY_Device_FriendlyName), byref(pv)) == 0:
                            if pv.pwszVal:
                                friendly_name = pv.pwszVal

                    # Encurta nomes muito longos removendo sufixos redundantes
                    cleaned_name = self._clean_device_name(friendly_name)
                    is_sys_def = (dev_id == default_sys_id)

                    devices.append(
                        AudioEndpoint(
                            device_id=dev_id,
                            name=cleaned_name,
                            flow=flow_name,
                            is_default=is_sys_def,
                        )
                    )
                finally:
                    _com_release(store_ptr)
                    _com_release(dev_ptr)
        finally:
            _com_release(coll_ptr)

        return devices

    @staticmethod
    def _clean_device_name(raw_name: str) -> str:
        """Limpa o nome do dispositivo para caber elegantemente na interface compacta de 240px."""
        name = raw_name.strip()
        for noise in ["(Realtek High Definition Audio)", "(High Definition Audio Device)"]:
            if noise in name and len(name) > len(noise):
                name = name.replace(noise, "(Realtek)").strip()
        return name
