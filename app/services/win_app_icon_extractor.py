import ctypes
import glob
import os
import winreg
import xml.etree.ElementTree as ET
from ctypes import POINTER, byref, c_int, c_uint, c_void_p, wintypes
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
gdi32 = ctypes.windll.gdi32 if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
shell32 = ctypes.windll.shell32 if hasattr(ctypes, "windll") else None

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", c_void_p),
        ("hbmColor", c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", c_void_p),
        ("iIcon", c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


if user32 and gdi32:
    user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR, c_int, c_int, c_int,
        POINTER(c_void_p), POINTER(c_uint), c_uint, c_uint,
    ]
    user32.PrivateExtractIconsW.restype = c_uint
    user32.GetIconInfo.argtypes = [c_void_p, POINTER(ICONINFO)]
    user32.GetIconInfo.restype = wintypes.BOOL
    user32.DestroyIcon.argtypes = [c_void_p]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.GetDC.argtypes = [c_void_p]
    user32.GetDC.restype = c_void_p
    user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
    user32.ReleaseDC.restype = c_int
    gdi32.GetDIBits.argtypes = [
        c_void_p, c_void_p, c_uint, c_uint,
        c_void_p, POINTER(BITMAPINFOHEADER), c_uint,
    ]
    gdi32.GetDIBits.restype = c_int
    gdi32.DeleteObject.argtypes = [c_void_p]
    gdi32.DeleteObject.restype = wintypes.BOOL

if shell32:
    shell32.SHGetFileInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, POINTER(SHFILEINFOW), c_uint, c_uint,
    ]
    shell32.SHGetFileInfoW.restype = ctypes.c_size_t

# Cache em memória para evitar re-extração de ícones a cada ciclo de polling
_ICON_CACHE: dict[str, QImage] = {}

# Processos intermediários (WebView/CEF/Subprocessos) que herdam áudio de um app pai real
_HELPER_EXES = {
    "msedgewebview2.exe",
    "steamwebhelper.exe",
    "cefsharp.browsersubprocess.exe",
    "rundll32.exe",
    "conhost.exe",
    "dllhost.exe",
}

# Processos genéricos do sistema que não devem substituir o executável do app
_SYSTEM_HOSTS = {
    "explorer.exe",
    "svchost.exe",
    "services.exe",
    "wininit.exe",
    "runtimebroker.exe",
    "sihost.exe",
    "taskhostw.exe",
    "cmd.exe",
    "powershell.exe",
}


def get_process_exe_path(pid: int) -> str:
    """Obtém o caminho completo do executável de um processo via Win32 API."""
    if not kernel32 or pid <= 4:
        return ""
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h_proc)
    return ""


def get_parent_process_map() -> dict[int, tuple[int, str]]:
    """Retorna mapa pid -> (parent_pid, exe_name) de todos os processos ativos."""
    result: dict[int, tuple[int, str]] = {}
    if not kernel32:
        return result
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == -1:
        return result
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, byref(pe)):
            while True:
                result[int(pe.th32ProcessID)] = (int(pe.th32ParentProcessID), pe.szExeFile)
                if not kernel32.Process32NextW(snap, byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return result


def resolve_real_app_identity(pid: int, proc_map: dict[int, tuple[int, str]]) -> tuple[str, str]:
    """
    Resolve a verdadeira identidade do aplicativo (chave única + caminho do executável principal).
    Se o áudio vier de um subprocesso como msedgewebview2.exe ou steamwebhelper.exe,
    sobe na árvore de processos até encontrar o aplicativo hospedeiro (ex: WhatsApp, Steam).
    """
    exe_path = get_process_exe_path(pid)
    if not exe_path:
        return "", ""

    cur_pid = pid
    best_path = exe_path
    for _ in range(5):
        base_lower = os.path.basename(best_path).lower()
        if base_lower not in _HELPER_EXES:
            break
        if cur_pid not in proc_map:
            break
        ppid, pname = proc_map[cur_pid]
        if ppid <= 4 or ppid == cur_pid or pname.lower() in _SYSTEM_HOSTS:
            break
        parent_path = get_process_exe_path(ppid)
        if not parent_path:
            break
        best_path = parent_path
        cur_pid = ppid

    app_key = best_path.lower()
    friendly_name = os.path.splitext(os.path.basename(best_path))[0]
    for suffix in (".Root", "WebHelper", "Container"):
        if friendly_name.endswith(suffix) and len(friendly_name) > len(suffix):
            friendly_name = friendly_name[: -len(suffix)]
    return app_key, best_path


def _hicon_to_qimage(hicon: int, size: int = 64) -> QImage:
    if not user32 or not gdi32 or not hicon:
        return QImage()
    ii = ICONINFO()
    if not user32.GetIconInfo(hicon, byref(ii)):
        return QImage()
    try:
        if not ii.hbmColor:
            return QImage()
        hdc = user32.GetDC(None)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = size
        bmi.biHeight = -size
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        buf = (ctypes.c_ubyte * (size * size * 4))()
        lines = gdi32.GetDIBits(hdc, ii.hbmColor, 0, size, buf, byref(bmi), 0)
        if lines > 0:
            raw = bytearray(buf)
            # Se o HICON usa máscara 1-bit (hbmMask) em vez de canal Alpha 32-bit, reconstrói o Alpha
            has_alpha = any(raw[i] > 0 for i in range(3, len(raw), 4))
            if not has_alpha and ii.hbmMask:
                mask_buf = (ctypes.c_ubyte * (size * size * 4))()
                mask_lines = gdi32.GetDIBits(hdc, ii.hbmMask, 0, size, mask_buf, byref(bmi), 0)
                if mask_lines > 0:
                    for i in range(0, len(raw), 4):
                        raw[i + 3] = 0 if mask_buf[i] > 128 else 255
                else:
                    for i in range(0, len(raw), 4):
                        if raw[i] or raw[i + 1] or raw[i + 2]:
                            raw[i + 3] = 255
            user32.ReleaseDC(None, hdc)
            img = QImage(bytes(raw), size, size, size * 4, QImage.Format.Format_ARGB32).copy()
            if not img.isNull():
                return img
        else:
            user32.ReleaseDC(None, hdc)
    finally:
        if ii.hbmMask:
            gdi32.DeleteObject(ii.hbmMask)
        if ii.hbmColor:
            gdi32.DeleteObject(ii.hbmColor)
    return QImage()


def _extract_pe_icon(file_path: str, icon_index: int = 0, size: int = 64) -> QImage:
    if not user32 or not file_path or not os.path.exists(file_path):
        return QImage()
    hicon = c_void_p()
    cnt = user32.PrivateExtractIconsW(file_path, icon_index, size, size, byref(hicon), None, 1, 0)
    if cnt > 0 and hicon.value and hicon.value != 0xFFFFFFFFFFFFFFFF:
        img = _hicon_to_qimage(hicon.value, size)
        user32.DestroyIcon(hicon.value)
        return img
    return QImage()


def _find_matching_uwp_package_dir(exe_path: str) -> str:
    """
    Quando um serviço em background roda fora de WindowsApps (ex: C:\\Program Files (x86)\\MSI\\MSI Center\\...\\LEDKeeper2.exe),
    consulta o registro de pacotes MSIX/UWP do usuário para localizar o pacote principal (ex: MSICenter) e extrair seu ícone oficial.
    """
    norm_parts = [
        p.replace(" ", "").replace("-", "").replace("_", "").lower()
        for p in exe_path.split(os.sep)
        if len(p) >= 4
    ]
    key_path = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            i = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(k, i)
                    i += 1
                    sub_clean = sub_name.replace(" ", "").replace("-", "").replace("_", "").lower()
                    if any(tok in sub_clean for tok in norm_parts if tok not in ("programfiles", "programfiles(x86)", "windows", "system32", "users", "appdata", "local", "programs")):
                        with winreg.OpenKey(k, sub_name) as sk:
                            root, _ = winreg.QueryValueEx(sk, "PackageRootFolder")
                            if root and os.path.exists(root):
                                return str(root)
                except OSError:
                    break
    except Exception:
        pass
    return ""


def _extract_uwp_or_folder_icon(exe_path: str, size: int = 64) -> QImage:
    """
    Busca ícones de aplicativos UWP/MSIX (WindowsApps como WhatsApp, Spotify Store, MSI Center, etc.)
    ou serviços em subpastas (como LEDKeeper2.exe) que não embutem recurso PE no .exe.
    """
    if not exe_path:
        return QImage()
    exe_dir = os.path.dirname(exe_path)
    parent_dir = os.path.dirname(exe_dir)
    search_dirs = [exe_dir, parent_dir]
    uwp_match_dir = _find_matching_uwp_package_dir(exe_path)
    if uwp_match_dir and uwp_match_dir not in search_dirs:
        search_dirs.insert(0, uwp_match_dir)

    # 1. Procura AppxManifest.xml (padrão UWP / WindowsApps)
    for d in search_dirs:
        manifest_path = os.path.join(d, "AppxManifest.xml")
        if os.path.exists(manifest_path):
            try:
                tree = ET.parse(manifest_path)
                root = tree.getroot()
                candidates: list[str] = []
                for elem in root.iter():
                    for attr in ("Square44x44Logo", "Square150x150Logo", "SmallTile", "Logo"):
                        val = elem.attrib.get(attr)
                        if val:
                            candidates.append(val)
                    if elem.tag.endswith("Logo") and elem.text:
                        candidates.append(elem.text.strip())
                for rel_logo in candidates:
                    full_base = os.path.join(d, rel_logo)
                    if os.path.exists(full_base):
                        img = QImage(full_base)
                        if not img.isNull():
                            return img
                    stem, ext = os.path.splitext(full_base)
                    matches = sorted(glob.glob(f"{stem}*{ext}"), key=len)
                    for m in matches:
                        m_low = os.path.basename(m).lower()
                        if "contrast" not in m_low and "unplated" in m_low:
                            img = QImage(m)
                            if not img.isNull():
                                return img
                    for m in matches:
                        if "contrast" not in os.path.basename(m).lower():
                            img = QImage(m)
                            if not img.isNull():
                                return img
            except Exception:
                pass

    # 2. Procura arquivos .ico ou Assets/*Logo*.png na pasta do app ou pasta pai
    for d in search_dirs:
        if not d or not os.path.exists(d):
            continue
        ico_files = glob.glob(os.path.join(d, "*.ico")) + glob.glob(os.path.join(d, "Assets", "*.ico"))
        for ico in ico_files:
            if "unins" not in os.path.basename(ico).lower():
                qimg = QImage(ico)
                if not qimg.isNull():
                    return qimg
                img = _extract_pe_icon(ico, 0, size)
                if not img.isNull():
                    return img

        png_logos = glob.glob(os.path.join(d, "Assets", "*Logo*.png"))
        for png in sorted(png_logos, reverse=True):
            if "contrast" not in os.path.basename(png).lower():
                qimg = QImage(png)
                if not qimg.isNull():
                    return qimg

        # 3. Procura executáveis irmãos na pasta ou pasta pai que possuam ícone (ex: MSI.ToastServer.exe)
        for sib_exe in glob.glob(os.path.join(d, "*.exe")):
            sib_name = os.path.basename(sib_exe).lower()
            if sib_name != os.path.basename(exe_path).lower() and not sib_name.startswith("unins"):
                img = _extract_pe_icon(sib_exe, 0, size)
                if not img.isNull():
                    return img

    return QImage()


def create_system_sounds_icon(size: int = 64) -> QImage:
    """Renderiza o ícone vetorial nítido de Sons do Sistema (Monitor + Alto-falante estilo Windows 11)."""
    if "__system_sounds__" in _ICON_CACHE:
        return _ICON_CACHE["__system_sounds__"]

    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    s = size / 16.0
    pen = QPen(QColor(245, 245, 245), 1.35 * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Corpo do monitor com recorte no canto superior direito para o speaker
    mon_path = QPainterPath()
    mon_path.moveTo(9.0 * s, 3.0 * s)
    mon_path.lineTo(2.6 * s, 3.0 * s)
    mon_path.quadTo(1.5 * s, 3.0 * s, 1.5 * s, 4.1 * s)
    mon_path.lineTo(1.5 * s, 10.4 * s)
    mon_path.quadTo(1.5 * s, 11.5 * s, 2.6 * s, 11.5 * s)
    mon_path.lineTo(12.4 * s, 11.5 * s)
    mon_path.quadTo(13.5 * s, 11.5 * s, 13.5 * s, 10.4 * s)
    mon_path.lineTo(13.5 * s, 8.2 * s)
    p.drawPath(mon_path)

    # Base do monitor
    p.drawLine(QPointF(7.5 * s, 11.5 * s), QPointF(7.5 * s, 14.0 * s))
    p.drawLine(QPointF(4.8 * s, 14.0 * s), QPointF(10.2 * s, 14.0 * s))

    # Mini speaker no canto superior direito
    spk = QPainterPath()
    spk.moveTo(10.5 * s, 3.6 * s)
    spk.lineTo(11.6 * s, 3.6 * s)
    spk.lineTo(13.1 * s, 2.2 * s)
    spk.lineTo(13.1 * s, 6.4 * s)
    spk.lineTo(11.6 * s, 5.0 * s)
    spk.lineTo(10.5 * s, 5.0 * s)
    spk.closeSubpath()
    p.fillPath(spk, QColor(245, 245, 245))

    wave_pen = QPen(QColor(245, 245, 245), 1.15 * s)
    wave_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(wave_pen)
    p.drawArc(QRectF(12.6 * s, 2.7 * s, 2.4 * s, 3.2 * s), -55 * 16, 110 * 16)

    p.end()
    _ICON_CACHE["__system_sounds__"] = img
    return img


def get_app_icon(exe_path: str, is_system_sounds: bool = False) -> QImage:
    """
    Pipeline completo de extração de ícone em alta resolução (64x64 ARGB):
    1. Sons do Sistema -> Ícone vetorial dedicado.
    2. Recurso PE nativo via PrivateExtractIconsW (64x64 32-bit).
    3. Manifesto UWP/MSIX (AppxManifest.xml) + Assets/*.ico / *Logo*.png + Executáveis irmãos.
    4. Fallback via SHGetFileInfoW do Windows Shell.
    """
    if is_system_sounds or not exe_path:
        return create_system_sounds_icon()

    cache_key = exe_path.lower()
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    # Etapa 1: Extração direta de alta resolução do PE (.exe)
    img = _extract_pe_icon(exe_path, 0, 64)

    # Etapa 2: Resolução profunda para apps UWP/WindowsApps (ex: WhatsApp) e serviços (ex: MSI LEDKeeper2)
    if img.isNull():
        img = _extract_uwp_or_folder_icon(exe_path, 64)

    # Etapa 3: SHGetFileInfoW como fallback do Shell
    if img.isNull() and shell32 and user32:
        sfi = SHFILEINFOW()
        res = shell32.SHGetFileInfoW(exe_path, 0, byref(sfi), ctypes.sizeof(SHFILEINFOW), SHGFI_ICON | SHGFI_LARGEICON)
        if res and sfi.hIcon:
            img = _hicon_to_qimage(sfi.hIcon, 64)
            user32.DestroyIcon(sfi.hIcon)

    if img.isNull():
        img = create_system_sounds_icon()

    _ICON_CACHE[cache_key] = img
    return img
