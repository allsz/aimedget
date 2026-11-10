"""
(Nome com "zz": roda por ULTIMO na suite, para os processos filhos nao deslocarem testes de temporização.)
Captura de crashes NATIVOS pelo crash reporter (faulthandler + marcador de sessão + log de mensagens do Qt).
Cada cenário roda num processo filho de verdade, porque um crash nativo derruba o processo inteiro.
  AIMEDGET_CRASH_TESTS=1 python -m unittest tests.test_zz_crash_reporter   (PowerShell: $env:AIMEDGET_CRASH_TESTS=1)

OPCIONAL: ficam fora da suíte padrão. Presentes nela, testes de temporização de outros módulos passaram a falhar
de vez em quando (~1 em 4 rodadas) e a causa não foi provada. Rode-os ao mexer em app/core/crash_reporter.py.
"""

import glob
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if os.environ.get("AIMEDGET_CRASH_TESTS") != "1":
    raise unittest.SkipTest("opcional: defina AIMEDGET_CRASH_TESTS=1 para rodar (ver o topo do arquivo)")

import app.core.crash_reporter as cr

CHILD = r'''
import os, sys, threading, time, faulthandler
sys.path.insert(0, sys.argv[3])
import app.core.crash_reporter as cr
reports = sys.argv[2]
cr.get_crash_reports_dir = lambda: reports      # relatórios vão para a pasta do teste
cr.install_crash_reporter()
mode = sys.argv[1]

def idle_worker():
    while True:
        time.sleep(0.05)

def boom_native():
    faulthandler._read_null()                   # acesso inválido REAL à memória (não vira exceção)

if mode == "native":
    threading.Thread(target=idle_worker, name="outra-thread", daemon=True).start()
    time.sleep(0.2)
    boom_native()
elif mode == "abrupt":
    os._exit(3)
elif mode == "pyexc":
    raise RuntimeError("erro comum do Python")
elif mode == "qt":
    from PySide6.QtCore import qDebug, qWarning, qCritical
    qDebug("mensagem-debug")
    qWarning("mensagem-aviso")
    qCritical("mensagem-critica")
elif mode == "qtfatal":
    from PySide6.QtCore import qFatal
    threading.Thread(target=idle_worker, name="outra-thread", daemon=True).start()
    time.sleep(0.2)
    def chamar_qfatal():
        qFatal("mensagem-fatal")
    chamar_qfatal()
# "clean" e "review": só instala e termina normalmente
'''


def run_child(mode: str, reports: str):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run(
        [sys.executable, "-c", CHILD, mode, reports, str(ROOT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=90, stdin=subprocess.DEVNULL,
    )


def native_logs(reports: str):
    return sorted(glob.glob(os.path.join(reports, "native_*.log")))


class _Dir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.reports = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


class NativeCrashTests(_Dir):
    def test_native_crash_leaves_evidence_of_every_thread(self):
        proc = run_child("native", self.reports)
        self.assertNotEqual(proc.returncode, 0)
        logs = native_logs(self.reports)
        self.assertEqual(len(logs), 1)
        text = Path(logs[0]).read_text(encoding="utf-8")
        self.assertTrue(any(m in text for m in cr.CRASH_MARKERS), text)
        self.assertIn("boom_native", text)                 # onde o crash aconteceu
        self.assertIn("idle_worker", text)                 # e o que as OUTRAS threads estavam fazendo
        self.assertNotIn(cr.CLEAN_EXIT_MARK, text)

    def test_next_start_reports_the_crash_and_keeps_the_log(self):
        run_child("native", self.reports)
        crashed = native_logs(self.reports)[0]
        proc = run_child("review", self.reports)           # próxima abertura
        self.assertEqual(proc.returncode, 0)
        self.assertIn("terminou de forma anormal", proc.stderr)
        self.assertIn(crashed, proc.stderr)
        self.assertTrue(os.path.isfile(crashed))           # a evidência é preservada
        latest = Path(self.reports, "latest_native_crash.txt").read_text(encoding="utf-8")
        self.assertIn("CRASH NATIVO", latest)
        self.assertIn("boom_native", latest)

    def test_abrupt_kill_is_flagged_even_without_any_error_text(self):
        proc = run_child("abrupt", self.reports)
        self.assertEqual(proc.returncode, 3)
        proc = run_child("review", self.reports)
        self.assertIn("terminou de forma anormal", proc.stderr)
        latest = Path(self.reports, "latest_native_crash.txt").read_text(encoding="utf-8")
        self.assertIn("ENCERRADA ABRUPTAMENTE", latest)


class NormalSessionTests(_Dir):
    def test_clean_session_leaves_no_evidence_behind(self):
        proc = run_child("clean", self.reports)
        self.assertEqual(proc.returncode, 0)
        first = native_logs(self.reports)
        self.assertEqual(len(first), 1)
        self.assertIn(cr.CLEAN_EXIT_MARK, Path(first[0]).read_text(encoding="utf-8"))
        proc = run_child("review", self.reports)           # próxima abertura descarta o log da sessão normal
        self.assertNotIn("anormal", proc.stderr)
        self.assertFalse(os.path.exists(first[0]))
        self.assertFalse(os.path.exists(os.path.join(self.reports, "latest_native_crash.txt")))

    def test_python_exception_is_still_reported_the_old_way(self):
        proc = run_child("pyexc", self.reports)
        self.assertEqual(proc.returncode, 1)
        reports = glob.glob(os.path.join(self.reports, "crash_*.log"))
        self.assertEqual(len(reports), 1)
        self.assertIn("RuntimeError", Path(reports[0]).read_text(encoding="utf-8"))
        # uma exceção do Python NÃO é crash nativo: a próxima abertura não acusa nada
        proc = run_child("review", self.reports)
        self.assertNotIn("anormal", proc.stderr)


class QtMessageLogTests(_Dir):
    def test_warnings_and_criticals_are_logged_but_debug_is_not(self):
        proc = run_child("qt", self.reports)
        self.assertEqual(proc.returncode, 0)
        log = Path(self.reports, "qt_messages.log").read_text(encoding="utf-8")
        self.assertIn("WARN", log)
        self.assertIn("mensagem-aviso", log)
        self.assertIn("CRIT", log)
        self.assertIn("mensagem-critica", log)
        self.assertNotIn("mensagem-debug", log)
        self.assertIn("MainThread", log)
        self.assertIn("mensagem-aviso", proc.stderr)       # o terminal continua mostrando as mensagens

    def test_fatal_message_reaches_the_disk_before_the_abort(self):
        try:
            from PySide6.QtCore import qFatal  # noqa: F401
        except ImportError:
            self.skipTest("esta versão do PySide6 não expõe qFatal")
        proc = run_child("qtfatal", self.reports)
        self.assertNotEqual(proc.returncode, 0)
        log = Path(self.reports, "qt_messages.log").read_text(encoding="utf-8")
        self.assertIn("FATAL", log)
        self.assertIn("mensagem-fatal", log)
        # No Windows o abort() do Qt pula o faulthandler (0xC0000409): o handler despeja as pilhas antes de abortar
        text = Path(native_logs(self.reports)[0]).read_text(encoding="utf-8")
        self.assertIn(cr.QFATAL_MARK, text)
        self.assertIn("chamar_qfatal", text)               # quem chamou
        self.assertIn("idle_worker", text)                 # e o que as outras threads faziam
        proc = run_child("review", self.reports)           # a próxima abertura acusa como crash
        self.assertIn("terminou de forma anormal", proc.stderr)
        self.assertIn("CRASH NATIVO", Path(self.reports, "latest_native_crash.txt").read_text(encoding="utf-8"))

    def test_log_rotates_when_too_big(self):
        # o handler gira o arquivo ao passar do limite; aqui só confere a constante e o comportamento de rotação em si
        path = os.path.join(self.reports, "qt_messages.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * (cr.QT_LOG_MAX_BYTES + 10))
        proc = run_child("qt", self.reports)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLess(os.path.getsize(path), cr.QT_LOG_MAX_BYTES)


class SessionReviewTests(_Dir):
    def _fake_log(self, pid, body):
        path = os.path.join(self.reports, f"native_2026-01-01_00-00-00_pid{pid}.log")
        Path(path).write_text(body, encoding="utf-8")
        return path

    def test_pid_alive(self):
        self.assertTrue(cr._pid_alive(os.getpid()))
        self.assertFalse(cr._pid_alive(0))
        self.assertFalse(cr._pid_alive(-5))
        self.assertFalse(cr._pid_alive(4_000_000))

    def test_a_session_still_running_is_never_flagged(self):
        """Outra instância aberta ao mesmo tempo: o log dela está 'incompleto' porque ela ainda roda."""
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.DEVNULL)
        try:
            path = self._fake_log(other.pid, "=== Sessão iniciada ===\n")
            self.assertEqual(cr.review_previous_sessions(self.reports), [])
            self.assertTrue(os.path.exists(path))
        finally:
            other.kill()
            other.wait()
        deadline = time.time() + 10
        while cr._pid_alive(other.pid) and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(cr.review_previous_sessions(self.reports), [path])   # morreu sem encerrar: agora é acusada

    def test_classification(self):
        self.assertEqual(cr._classify_native_log("x\n" + cr.CLEAN_EXIT_MARK), "clean")
        self.assertEqual(cr._classify_native_log("Windows fatal exception: access violation\n"), "crash")
        self.assertEqual(cr._classify_native_log("Fatal Python error: Aborted\n" + cr.CLEAN_EXIT_MARK), "crash")
        self.assertEqual(cr._classify_native_log("=== Sessão iniciada ==="), "abrupt")

    def test_old_logs_are_pruned(self):
        for i in range(cr.MAX_NATIVE_LOGS + 5):
            p = self._fake_log(900000 + i, "x")
            os.utime(p, (1000 + i, 1000 + i))
        cr._clean_old_native_logs(self.reports)
        self.assertEqual(len(native_logs(self.reports)), cr.MAX_NATIVE_LOGS)

    def test_capture_never_prevents_startup(self):
        """Se não der para gravar o log (pasta inválida), o app abre do mesmo jeito."""
        a_file = os.path.join(self.reports, "eu_sou_um_arquivo")
        Path(a_file).write_text("x")
        old = cr.get_crash_reports_dir
        cr.get_crash_reports_dir = lambda: os.path.join(a_file, "subpasta")   # dentro de um arquivo: impossível
        try:
            self.assertIsNone(cr.install_native_crash_capture())
        finally:
            cr.get_crash_reports_dir = old


if __name__ == "__main__":
    unittest.main()
