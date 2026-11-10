"""
Os serviços de áudio não podem prender a thread principal em COM multithread (MTA) ao serem importados:
o Qt precisa iniciar o OLE em STA, e o seletor de arquivo nativo do Windows trava o app em MTA.
  python tests/test_com_apartment.py
"""

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CODE = textwrap.dedent("""
    import ctypes, sys
    sys.path.insert(0, {root!r})
    import app.services.audio_endpoint_service, app.services.audio_mixer_service   # como o app, antes do QApplication
    ole = ctypes.windll.ole32
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    hr = ole.CoInitializeEx(None, 2) & 0xFFFFFFFF       # pede STA: 0/1 = livre; 0x80010106 = já está em MTA
    print("STA_LIVRE" if hr in (0, 1) else "OCUPADA_POR_OUTRO_MODO:" + hex(hr))
""")


@unittest.skipUnless(sys.platform == "win32", "COM é coisa do Windows")
class ComApartmentTests(unittest.TestCase):
    def test_importing_audio_services_leaves_the_main_thread_free_for_qt_sta(self):
        r = subprocess.run([sys.executable, "-c", CODE.format(root=str(ROOT))], capture_output=True, text=True,
                           timeout=60)
        self.assertIn("STA_LIVRE", r.stdout, r.stdout + r.stderr)

    def test_no_service_asks_for_multithreaded_com(self):
        """Barato e direto: ninguém volta a pedir RoInitialize(1) / CoInitializeEx(..., 0)."""
        for name in ("audio_endpoint_service.py", "audio_mixer_service.py"):
            src = (ROOT / "app" / "services" / name).read_text(encoding="utf-8")
            self.assertNotIn("RoInitialize(1)", src, name)
            self.assertNotIn("CoInitializeEx(None, 0)", src, name)


if __name__ == "__main__":
    unittest.main()
