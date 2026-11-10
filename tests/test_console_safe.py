"""
O console não pode derrubar uma thread por causa de um caractere que o cp1252 não escreve
(caso real: título de música em print na thread da mídia).
  python tests/test_console_safe.py
"""

import io
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.console import make_console_safe

SNIPPET = textwrap.dedent("""
    import sys, threading
    sys.path.insert(0, {root!r})
    {setup}
    errors = []
    def worker():
        try:
            print("[MediaWorker] Capa para: '東京 – Give Up’ 🖼️'")
            print("segundo print", file=sys.stderr)
        except Exception as exc:
            errors.append(repr(exc))
    t = threading.Thread(target=worker); t.start(); t.join()
    sys.stdout.flush()
    print("RESULT:" + ("ERRO " + errors[0][:40] if errors else "ok"), file=sys.stderr)
""")


def run(setup: str) -> str:
    code = SNIPPET.format(root=str(ROOT), setup=setup)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="cp1252",
                       errors="replace", env={**os.environ, "PYTHONIOENCODING": "cp1252"}, timeout=60)
    return r.stderr


class ConsoleSafeTests(unittest.TestCase):
    def test_without_the_fix_a_cp1252_console_raises_in_the_thread(self):
        """Documenta o bug original: sem o helper, o print falha."""
        self.assertIn("RESULT:ERRO UnicodeEncodeError", run("pass"))

    def test_with_the_fix_the_thread_survives(self):
        self.assertIn("RESULT:ok", run("from app.core.console import make_console_safe; make_console_safe()"))

    def test_tolerates_missing_or_odd_streams(self):
        old = (sys.stdout, sys.stderr)
        try:
            sys.stdout = None                       # app sem console
            sys.stderr = io.StringIO()              # stream sem reconfigure de verdade (StringIO tem, mas ignora encoding)
            make_console_safe()
            sys.stderr = object()                   # sem o método
            make_console_safe()
        finally:
            sys.stdout, sys.stderr = old


if __name__ == "__main__":
    unittest.main()
