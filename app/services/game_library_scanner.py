"""
GameLibraryScanner - Detecção leve de bibliotecas oficiais de jogos no Windows (Steam, Epic, GOG, Amazon).

Usa apenas fontes oficiais locais (manifestos VDF/ACF, JSON da Epic, registro do GOG e banco SQLite da Amazon):
- Steam e Epic leem o tamanho diretamente dos manifestos oficiais (zero varredura de disco).
- GOG e Amazon usam `scan_folder_usage` apenas nos diretórios de instalação encontrados.
- Agrupa cada loja por disco (ex.: Steam em C:, Steam em D:).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Optional

_VDF_KV_RE = re.compile(r'"([^"]+)"\s+"([^"]*)"')


@dataclass
class GameLibraryUsage:
    store: str          # "Steam", "Epic Games", "GOG", "Amazon Games"
    path: str           # diretório principal da biblioteca naquele disco
    drive: str          # "C:", "D:"
    size_bytes: int
    game_count: int


def _drive_of(path: str) -> str:
    drv, _ = os.path.splitdrive(os.path.abspath(path))
    return drv.upper() if drv else "/"


# --- Steam (VDF + ACF: instantâneo, sem varrer arquivos) ---

def _steam_root() -> Optional[str]:
    if sys.platform == "win32":
        try:
            import winreg
            for hive, sub in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        val, _ = winreg.QueryValueEx(k, "SteamPath")
                        if val and os.path.isdir(val):
                            return os.path.normpath(val)
                except OSError:
                    continue
        except Exception:
            pass
    default = r"C:\Program Files (x86)\Steam"
    return default if os.path.isdir(default) else None


def parse_steam_library_paths(vdf_text: str) -> list[str]:
    """Extrai os caminhos de bibliotecas do `libraryfolders.vdf`."""
    paths: list[str] = []
    seen = set()
    for key, val in _VDF_KV_RE.findall(vdf_text):
        if key.lower() == "path" and val:
            norm = os.path.normpath(val.replace("\\\\", "\\"))
            if norm.lower() not in seen:
                seen.add(norm.lower())
                paths.append(norm)
    return paths


def parse_steam_acf_size(acf_text: str) -> Optional[int]:
    """Lê `SizeOnDisk` de um arquivo `appmanifest_*.acf`."""
    for key, val in _VDF_KV_RE.findall(acf_text):
        if key == "SizeOnDisk":
            try:
                return max(0, int(val))
            except ValueError:
                return None
    return None


def scan_steam_libraries(steam_root: Optional[str] = None) -> list[GameLibraryUsage]:
    root = steam_root or _steam_root()
    if not root or not os.path.isdir(root):
        return []

    libs = [root]
    vdf_path = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf_path):
        try:
            with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
                for p in parse_steam_library_paths(f.read()):
                    if p.lower() != root.lower() and os.path.isdir(p):
                        libs.append(p)
        except OSError:
            pass

    by_drive: dict[str, GameLibraryUsage] = {}
    for lib in libs:
        steamapps = os.path.join(lib, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        drv = _drive_of(lib)
        common_dir = os.path.join(steamapps, "common")
        open_path = common_dir if os.path.isdir(common_dir) else steamapps
        try:
            with os.scandir(steamapps) as it:
                for entry in it:
                    if not (entry.is_file() and entry.name.startswith("appmanifest_") and entry.name.endswith(".acf")):
                        continue
                    try:
                        with open(entry.path, "r", encoding="utf-8", errors="ignore") as f:
                            sz = parse_steam_acf_size(f.read())
                    except OSError:
                        continue
                    if sz is None or sz <= 0:
                        continue
                    cur = by_drive.get(drv)
                    if cur is None:
                        by_drive[drv] = GameLibraryUsage("Steam", open_path, drv, sz, 1)
                    else:
                        cur.size_bytes += sz
                        cur.game_count += 1
        except OSError:
            continue

    return list(by_drive.values())


# --- Epic Games (Manifests/*.item: instantâneo, sem varrer arquivos) ---

def scan_epic_libraries(manifests_dir: Optional[str] = None) -> list[GameLibraryUsage]:
    if manifests_dir is None:
        prog_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        manifests_dir = os.path.join(prog_data, "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if not os.path.isdir(manifests_dir):
        return []

    by_drive: dict[str, GameLibraryUsage] = {}
    try:
        with os.scandir(manifests_dir) as it:
            for entry in it:
                if not (entry.is_file() and entry.name.lower().endswith(".item")):
                    continue
                try:
                    with open(entry.path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict) or data.get("bIsIncompleteInstall"):
                    continue
                install_loc = str(data.get("InstallLocation") or "").strip()
                if not install_loc or not os.path.isdir(install_loc):
                    continue
                try:
                    sz = max(0, int(data.get("InstallSize") or 0))
                except (TypeError, ValueError):
                    sz = 0
                if sz <= 0:
                    continue
                norm = os.path.normpath(install_loc)
                drv = _drive_of(norm)
                parent_dir = os.path.dirname(norm) or norm
                cur = by_drive.get(drv)
                if cur is None:
                    by_drive[drv] = GameLibraryUsage("Epic Games", parent_dir, drv, sz, 1)
                else:
                    cur.size_bytes += sz
                    cur.game_count += 1
    except OSError:
        pass

    return list(by_drive.values())


# --- GOG Galaxy (Registro oficial) ---

def scan_gog_libraries(
    size_fn: Callable[[str, Optional[threading.Event]], tuple[int, int, bool]],
    cancel_event: Optional[threading.Event] = None,
) -> list[GameLibraryUsage]:
    if sys.platform != "win32":
        return []
    game_paths: list[str] = []
    seen = set()
    try:
        import winreg
        for sub in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub) as root:
                    idx = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(root, idx)
                            idx += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(root, sub_name) as gk:
                                path_val, _ = winreg.QueryValueEx(gk, "path")
                                if path_val and os.path.isdir(path_val):
                                    norm = os.path.normpath(str(path_val))
                                    if norm.lower() not in seen:
                                        seen.add(norm.lower())
                                        game_paths.append(norm)
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        return []

    by_drive: dict[str, GameLibraryUsage] = {}
    for p in game_paths:
        if cancel_event is not None and cancel_event.is_set():
            break
        sz, _cnt, ok = size_fn(p, cancel_event)
        if not ok or sz <= 0:
            continue
        drv = _drive_of(p)
        parent_dir = os.path.dirname(p) or p
        cur = by_drive.get(drv)
        if cur is None:
            by_drive[drv] = GameLibraryUsage("GOG", parent_dir, drv, sz, 1)
        else:
            cur.size_bytes += sz
            cur.game_count += 1
    return list(by_drive.values())


# --- Amazon Games (SQLite oficial) ---

def scan_amazon_libraries(
    size_fn: Callable[[str, Optional[threading.Event]], tuple[int, int, bool]],
    cancel_event: Optional[threading.Event] = None,
    db_path: Optional[str] = None,
) -> list[GameLibraryUsage]:
    if db_path is None:
        local = os.environ.get("LOCALAPPDATA", "")
        db_path = os.path.join(local, "Amazon Games", "Data", "Games", "Sql", "GameInstallInfo.sqlite")
    if not db_path or not os.path.isfile(db_path):
        return []

    game_paths: list[str] = []
    seen = set()
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cur = conn.execute("SELECT InstallDirectory FROM DbSet WHERE Installed = 1")
            for (raw_dir,) in cur.fetchall():
                if raw_dir and os.path.isdir(raw_dir):
                    norm = os.path.normpath(str(raw_dir))
                    if norm.lower() not in seen:
                        seen.add(norm.lower())
                        game_paths.append(norm)
        finally:
            conn.close()
    except Exception:
        return []

    by_drive: dict[str, GameLibraryUsage] = {}
    for p in game_paths:
        if cancel_event is not None and cancel_event.is_set():
            break
        sz, _cnt, ok = size_fn(p, cancel_event)
        if not ok or sz <= 0:
            continue
        drv = _drive_of(p)
        parent_dir = os.path.dirname(p) or p
        cur = by_drive.get(drv)
        if cur is None:
            by_drive[drv] = GameLibraryUsage("Amazon Games", parent_dir, drv, sz, 1)
        else:
            cur.size_bytes += sz
            cur.game_count += 1
    return list(by_drive.values())


def scan_official_game_libraries(
    size_fn: Callable[[str, Optional[threading.Event]], tuple[int, int, bool]],
    cancel_event: Optional[threading.Event] = None,
) -> list[GameLibraryUsage]:
    """Escaneia Steam, Epic Games, GOG e Amazon Games (somente fontes oficiais)."""
    results: list[GameLibraryUsage] = []
    results.extend(scan_steam_libraries())
    if cancel_event is not None and cancel_event.is_set():
        return results
    results.extend(scan_epic_libraries())
    if cancel_event is not None and cancel_event.is_set():
        return results
    results.extend(scan_gog_libraries(size_fn, cancel_event))
    if cancel_event is not None and cancel_event.is_set():
        return results
    results.extend(scan_amazon_libraries(size_fn, cancel_event))
    return results
