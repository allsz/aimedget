"""
StorageService - Monitoramento leve de volume de pastas e discos no Windows (zero código de UI).

Precauções de hardware e sistema:
- Varredura recursiva em thread daemon via `os.scandir` com `follow_symlinks=False` (evita loops em junctions/symlinks
  e contagem duplicada).
- Ignora placeholders somente-nuvem do OneDrive (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS / FILE_ATTRIBUTE_OFFLINE) para
  não inflar o espaço local ocupado no SSD.
- Trata `PermissionError` e `OSError` sem travar nem abortar a varredura.
- Pausa re-escaneamentos automáticos quando há jogo/app em tela cheia (SHQueryUserNotificationState).
- Observa raízes das pastas via `QFileSystemWatcher` com debounce longo (6 s) e para totalmente quando o widget está
  oculto (custo zero em segundo plano).
- Resolve pastas conhecidas do Windows (Downloads, Imagens, Vídeos, Documentos) via `SHGetKnownFolderPath`.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from app.core.config_manager import config_manager
from app.services.game_library_scanner import scan_official_game_libraries

logger = logging.getLogger(__name__)

# Constantes de atributos de arquivo do Windows (WinNT)
_FILE_ATTR_OFFLINE = 0x00001000
_FILE_ATTR_RECALL_ON_OPEN = 0x00040000
_FILE_ATTR_RECALL_ON_DATA_ACCESS = 0x00400000
_CLOUD_ONLY_MASK = _FILE_ATTR_OFFLINE | _FILE_ATTR_RECALL_ON_OPEN | _FILE_ATTR_RECALL_ON_DATA_ACCESS

# GUIDs das pastas conhecidas do Windows (KnownFolderId)
_KNOWN_FOLDER_GUIDS = (
    ("Downloads", "{374DE290-123F-4565-9164-39C4925E467B}"),
    ("Pictures", "{33E28130-4E1E-4676-835A-98395C3BC3BB}"),
    ("Videos", "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}"),
    ("Documents", "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"),
)

RESCAN_INTERVAL_MS = 10 * 60 * 1000   # re-escaneamento periódico suave (10 min)
WATCH_DEBOUNCE_MS = 6000              # debounce após alterações de disco (evita pico durante downloads)
MAX_FOLDERS = 12


@dataclass
class FolderUsage:
    name: str
    path: str
    drive: str              # ex.: "C:", "D:"
    size_bytes: int = 0
    file_count: int = 0
    accessible: bool = True
    is_game_library: bool = False

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024.0 ** 3)


@dataclass
class DriveUsage:
    drive: str              # ex.: "C:"
    label: str              # ex.: "System (C:)" ou nome do volume
    total_bytes: int = 0
    used_bytes: int = 0
    folders: list[FolderUsage] = field(default_factory=list)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024.0 ** 3)

    @property
    def used_gb(self) -> float:
        return self.used_bytes / (1024.0 ** 3)

    @property
    def other_gb(self) -> float:
        tracked = sum(f.size_gb for f in self.folders)
        return max(0.0, self.used_gb - tracked)


@dataclass
class StorageSnapshot:
    drives: list[DriveUsage] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Optional["StorageSnapshot"]:
        if not isinstance(data, dict):
            return None
        try:
            drives = []
            for d in data.get("drives") or []:
                folders = [
                    FolderUsage(
                        name=str(f["name"]),
                        path=str(f["path"]),
                        drive=str(f["drive"]),
                        size_bytes=int(f.get("size_bytes", 0)),
                        file_count=int(f.get("file_count", 0)),
                        accessible=bool(f.get("accessible", True)),
                        is_game_library=bool(f.get("is_game_library", False)),
                    )
                    for f in (d.get("folders") or [])
                ]
                drives.append(DriveUsage(
                    drive=str(d["drive"]),
                    label=str(d.get("label", d["drive"])),
                    total_bytes=int(d.get("total_bytes", 0)),
                    used_bytes=int(d.get("used_bytes", 0)),
                    folders=folders,
                ))
            return cls(drives=drives, updated_at=float(data.get("updated_at", 0.0)))
        except (KeyError, TypeError, ValueError):
            return None


def is_fullscreen_busy() -> bool:
    """True quando há jogo D3D ou aplicativo em tela cheia no Windows (pausa varredura automática)."""
    if sys.platform != "win32":
        return False
    try:
        state = ctypes.c_int(0)
        res = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        if res == 0:
            # 2 = QUNS_BUSY, 3 = QUNS_RUNNING_D3D_FULL_SCREEN, 4 = QUNS_PRESENTATION_MODE
            return state.value in (2, 3, 4)
    except Exception:
        pass
    return False


def _known_folder_path(guid_str: str) -> Optional[str]:
    """Resolve uma pasta conhecida do Windows via SHGetKnownFolderPath."""
    if sys.platform != "win32":
        return None
    try:
        import uuid

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        u = uuid.UUID(guid_str)
        b = u.bytes_le
        g = _GUID.from_buffer_copy(b)
        p_path = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p_path))
        if hr == 0 and p_path.value:
            out = str(p_path.value)
            ctypes.windll.ole32.CoTaskMemFree(p_path)
            return out
    except Exception:
        pass
    return None


def default_windows_folders() -> list[dict]:
    """Pastas padrão do Windows (respeitando realocação de Downloads/Imagens/Vídeos para outro disco)."""
    home = os.path.expanduser("~")
    result = []
    seen = set()
    for fallback_name, guid in _KNOWN_FOLDER_GUIDS:
        path = _known_folder_path(guid) or os.path.join(home, fallback_name)
        norm = os.path.normpath(path)
        key = norm.lower()
        if key in seen:
            continue
        if os.path.isdir(norm):
            seen.add(key)
            name = os.path.basename(norm) or fallback_name
            result.append({"name": name, "path": norm})
    return result


def drive_of(path: str) -> str:
    """Retorna a letra do disco normalizada ('C:', 'D:') ou '/' fora do Windows."""
    drv, _ = os.path.splitdrive(os.path.abspath(path))
    return drv.upper() if drv else "/"


def volume_label(drive: str) -> str:
    """Nome amigável do volume no Windows (ex.: 'Secondary SSD (D:)'), com fallback seguro."""
    if sys.platform == "win32" and len(drive) == 2 and drive[1] == ":":
        try:
            buf = ctypes.create_unicode_buffer(261)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                f"{drive}\\", buf, 261, None, None, None, None, 0
            )
            if ok and buf.value.strip():
                return f"{buf.value.strip()} ({drive})"
        except Exception:
            pass
    return f"Local Disk ({drive})"


def scan_folder_usage(path: str, cancel_event: Optional[threading.Event] = None) -> tuple[int, int, bool]:
    """
    Calcula (bytes_locais, total_arquivos, acessivel) usando pilha iterativa + os.scandir.
    Nunca segue symlinks/junctions e desconsidera arquivos somente-nuvem do OneDrive.
    """
    if not os.path.isdir(path):
        return 0, 0, False

    total_bytes = 0
    file_count = 0
    stack = [path]

    while stack:
        if cancel_event is not None and cancel_event.is_set():
            return total_bytes, file_count, True
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel_event is not None and cancel_event.is_set():
                        return total_bytes, file_count, True
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            attrs = getattr(st, "st_file_attributes", 0)
                            if attrs & _CLOUD_ONLY_MASK:
                                continue
                            total_bytes += int(st.st_size)
                            file_count += 1
                    except OSError:
                        continue
        except OSError:
            continue

    return total_bytes, file_count, True


def compute_snapshot(
    folder_entries: list[dict],
    cancel_event: Optional[threading.Event] = None,
    include_games: bool = False,
) -> StorageSnapshot:
    """Agrupa pastas (e bibliotecas oficiais de jogos, se ativado) por disco, ordenando do maior para o menor."""
    by_drive: dict[str, list[FolderUsage]] = {}
    drive_order: list[str] = []
    seen_paths: set[str] = set()

    for item in folder_entries:
        if cancel_event is not None and cancel_event.is_set():
            break
        raw_path = str(item.get("path", "")).strip()
        if not raw_path:
            continue
        norm = os.path.normpath(raw_path)
        seen_paths.add(norm.lower())
        name = str(item.get("name") or os.path.basename(norm) or norm)
        drv = drive_of(norm)
        size_b, count, accessible = scan_folder_usage(norm, cancel_event=cancel_event)
        if drv not in by_drive:
            by_drive[drv] = []
            drive_order.append(drv)
        by_drive[drv].append(FolderUsage(
            name=name,
            path=norm,
            drive=drv,
            size_bytes=size_b,
            file_count=count,
            accessible=accessible,
            is_game_library=False,
        ))

    if include_games and not (cancel_event is not None and cancel_event.is_set()):
        for lib in scan_official_game_libraries(scan_folder_usage, cancel_event=cancel_event):
            norm = os.path.normpath(lib.path)
            if norm.lower() in seen_paths:
                continue
            seen_paths.add(norm.lower())
            if lib.drive not in by_drive:
                by_drive[lib.drive] = []
                drive_order.append(lib.drive)
            by_drive[lib.drive].append(FolderUsage(
                name=lib.store,
                path=norm,
                drive=lib.drive,
                size_bytes=lib.size_bytes,
                file_count=lib.game_count,
                accessible=True,
                is_game_library=True,
            ))

    drives: list[DriveUsage] = []
    for drv in drive_order:
        root = f"{drv}\\" if (len(drv) == 2 and drv[1] == ":") else drv
        try:
            du = shutil.disk_usage(root)
            total_b, used_b = int(du.total), int(du.used)
        except OSError:
            total_b, used_b = 0, 0
        sorted_folders = sorted(by_drive[drv], key=lambda f: f.size_bytes, reverse=True)
        drives.append(DriveUsage(
            drive=drv,
            label=volume_label(drv),
            total_bytes=total_b,
            used_bytes=used_b,
            folders=sorted_folders,
        ))

    return StorageSnapshot(drives=drives, updated_at=time.time())


class _Relay(QObject):
    done = Signal(object)


class StorageService(QObject):
    snapshot_ready = Signal(object)   # StorageSnapshot
    folders_changed = Signal()
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._relay = _Relay()
        self._relay.done.connect(self._on_scan_done)
        self._running = False
        self._busy = False
        self._pending = False
        self._cancel = threading.Event()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(WATCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(lambda: self.refresh(force=False))

        self._periodic = QTimer(self)
        self._periodic.setInterval(RESCAN_INTERVAL_MS)
        self._periodic.timeout.connect(lambda: self.refresh(force=False))

    # --- Pastas configuradas ---

    @staticmethod
    def folders() -> list[dict]:
        raw = config_manager.get_storage("folders", None)
        if isinstance(raw, list):
            out = []
            seen = set()
            for item in raw:
                if not isinstance(item, dict) or not item.get("path"):
                    continue
                norm = os.path.normpath(str(item["path"]))
                key = norm.lower()
                if key in seen:
                    continue
                seen.add(key)
                name = str(item.get("name") or os.path.basename(norm) or norm)
                out.append({"name": name, "path": norm})
                if len(out) >= MAX_FOLDERS:
                    break
            return out
        defaults = default_windows_folders()
        config_manager.set_storage("folders", defaults)
        return defaults

    def add_folder(self, path: str, name: Optional[str] = None) -> bool:
        norm = os.path.normpath(path.strip())
        if not norm or not os.path.isdir(norm):
            return False
        current = self.folders()
        if len(current) >= MAX_FOLDERS:
            return False
        if any(f["path"].lower() == norm.lower() for f in current):
            return False
        label = (name or os.path.basename(norm) or norm).strip()
        current.append({"name": label, "path": norm})
        config_manager.set_storage("folders", current)
        self._sync_watcher()
        self.folders_changed.emit()
        if self._running:
            self.refresh(force=True)
        return True

    def remove_folder(self, path: str) -> bool:
        norm_l = os.path.normpath(path).lower()
        current = self.folders()
        updated = [f for f in current if f["path"].lower() != norm_l]
        if len(updated) == len(current):
            return False
        config_manager.set_storage("folders", updated)
        self._sync_watcher()
        self.folders_changed.emit()
        if self._running:
            self.refresh(force=True)
        return True

    def move_folder(self, from_idx: int, to_idx: int) -> bool:
        current = self.folders()
        if not (0 <= from_idx < len(current) and 0 <= to_idx < len(current)) or from_idx == to_idx:
            return False
        item = current.pop(from_idx)
        current.insert(to_idx, item)
        config_manager.set_storage("folders", current)
        self.folders_changed.emit()
        return True

    def restore_defaults(self):
        defaults = default_windows_folders()
        config_manager.set_storage("folders", defaults)
        self._sync_watcher()
        self.folders_changed.emit()
        if self._running:
            self.refresh(force=True)

    @staticmethod
    def cached_snapshot() -> Optional[StorageSnapshot]:
        return StorageSnapshot.from_dict(config_manager.get_storage("cache", None))

    # --- Ciclo de vida ---

    def start(self):
        if self._running:
            return
        self._running = True
        self._cancel.clear()
        self._sync_watcher()
        self._periodic.start()
        self.refresh(force=True)

    def stop(self):
        self._running = False
        self._cancel.set()
        self._debounce.stop()
        self._periodic.stop()
        self._clear_watcher()

    def _clear_watcher(self):
        dirs = self._watcher.directories()
        if dirs:
            self._watcher.removePaths(dirs)

    def _sync_watcher(self):
        self._clear_watcher()
        if not self._running:
            return
        paths = [f["path"] for f in self.folders() if os.path.isdir(f["path"])]
        if paths:
            self._watcher.addPaths(paths)

    def _on_dir_changed(self, _path: str):
        if self._running:
            self._debounce.start()

    def refresh(self, force: bool = False):
        if not force and is_fullscreen_busy():
            return
        if self._busy:
            self._pending = True
            return
        self._busy = True
        self._pending = False
        self._cancel.clear()
        self.busy_changed.emit(True)
        entries = self.folders()
        include_games = bool(config_manager.get_storage("scan_games", True))

        def _worker():
            snap = compute_snapshot(entries, cancel_event=self._cancel, include_games=include_games)
            if not self._cancel.is_set():
                self._relay.done.emit(snap)
            else:
                self._relay.done.emit(None)

        threading.Thread(target=_worker, name="AimedgetStorageScan", daemon=True).start()

    def _on_scan_done(self, snap: Optional[StorageSnapshot]):
        self._busy = False
        self.busy_changed.emit(False)
        if snap is not None:
            config_manager.set_storage("cache", snap.to_dict())
            self.snapshot_ready.emit(snap)
        if self._pending and self._running:
            self._pending = False
            self.refresh(force=True)
