import atexit
import datetime
import faulthandler
import glob
import os
import platform
import sys
import threading
import traceback
from typing import Any, Optional

from app.core.paths import get_base_dir


def get_crash_reports_dir() -> str:
    """
    Retorna o diretório destinado aos relatórios de crash.
    Em modo desenvolvimento, salva prioritariamente na pasta 'crash_reports/' na raiz do projeto.
    Em executável congelado (.exe), salva em '%LOCALAPPDATA%/WindowsRedesign/crash_reports/'.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        reports_dir = os.path.join(base, "WindowsRedesign", "crash_reports")
    else:
        reports_dir = os.path.join(get_base_dir(), "crash_reports")

    try:
        os.makedirs(reports_dir, exist_ok=True)
    except Exception:
        fallback = os.path.join(os.environ.get("TEMP", "."), "WindowsRedesign_crash_reports")
        os.makedirs(fallback, exist_ok=True)
        return fallback

    return reports_dir


def _clean_old_crash_reports(reports_dir: str, max_reports: int = 25):
    """Mantém apenas os relatórios mais recentes para evitar acúmulo desnecessário de arquivos."""
    try:
        files = glob.glob(os.path.join(reports_dir, "crash_*.log"))
        if len(files) > max_reports:
            files.sort(key=os.path.getmtime)
            for f in files[:-max_reports]:
                try:
                    os.remove(f)
                except Exception:
                    pass
    except Exception:
        pass


def generate_crash_report(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: Any,
    context_note: str = "",
    thread_obj: Optional[threading.Thread] = None,
) -> str:
    """
    Gera e salva um relatório detalhado de crash em disco.
    Retorna o caminho absoluto do arquivo .log gerado.
    """
    reports_dir = get_crash_reports_dir()
    now = datetime.datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    iso_timestamp = now.isoformat()

    report_filename = f"crash_{timestamp_str}.log"
    report_path = os.path.join(reports_dir, report_filename)
    latest_path = os.path.join(reports_dir, "latest_crash.txt")

    thread_name = thread_obj.name if thread_obj else threading.current_thread().name
    thread_id = thread_obj.ident if thread_obj else threading.get_ident()

    # Formata o traceback completo
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    full_traceback = "".join(tb_lines)

    # Informações de versão e bibliotecas
    pyside_version = "Unknown"
    try:
        import PySide6
        pyside_version = PySide6.__version__
    except Exception:
        pass

    # Inspeção dos frames para capturar variáveis locais do ponto exato do erro
    local_vars_info = []
    try:
        curr_tb = exc_tb
        frame_idx = 0
        while curr_tb is not None:
            frame = curr_tb.tb_frame
            code = frame.f_code
            filename = os.path.basename(code.co_filename)
            func_name = code.co_name
            lineno = curr_tb.tb_lineno
            locals_repr = {}
            for k, v in list(frame.f_locals.items())[:15]:  # limita a 15 variáveis por frame
                try:
                    r = repr(v)
                    if len(r) > 120:
                        r = r[:117] + "..."
                    locals_repr[k] = r
                except Exception:
                    locals_repr[k] = "<unprintable>"

            local_vars_info.append(
                f"  Frame #{frame_idx} [{filename}:{lineno} in {func_name}()]:\n"
                + "\n".join(f"    - {k} = {val}" for k, val in locals_repr.items())
            )
            curr_tb = curr_tb.tb_next
            frame_idx += 1
    except Exception:
        local_vars_info.append("  <Não foi possível extrair variáveis locais>")

    local_vars_str = "\n".join(local_vars_info) if local_vars_info else "  (Nenhum frame inspecionado)"

    report_content = f"""{"=" * 80}
💥 WINDOWS REDESIGN - RELATÓRIO DE CRASH
{"=" * 80}
Carimbo de Data/Hora: {now.strftime("%d/%m/%Y %H:%M:%S")} (Local)
ISO Timestamp:       {iso_timestamp}
Contexto:            {context_note or "Exceção não tratada capturada globalmente"}

INFORMAÇÕES DO SISTEMA:
- Sistema Operacional: {platform.system()} {platform.release()} ({platform.version()})
- Arquitetura:         {platform.machine()} ({platform.architecture()[0]})
- Versão do Python:    {sys.version.split()[0]} ({sys.executable})
- PySide6 / Qt:        {pyside_version}
- Process ID (PID):    {os.getpid()}
- Thread Envolvida:    '{thread_name}' (ID: {thread_id})
- Linha de Comando:    {' '.join(sys.argv)}
- Diretório de Trab.:  {os.getcwd()}

DETALHES DA EXCEÇÃO:
- Tipo:     {exc_type.__name__}
- Mensagem: {str(exc_value)}

TRACEBACK COMPLETO:
{full_traceback.strip()}

VARIÁVEIS LOCAIS NOS FRAMES:
{local_vars_str}
{"=" * 80}
"""

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        # Atualiza o arquivo de conveniência 'latest_crash.txt'
        with open(latest_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        _clean_old_crash_reports(reports_dir)
    except Exception as save_err:
        print(f"[CrashReporter] Falha ao gravar arquivo de crash: {save_err}", file=sys.stderr)

    return report_path


def record_exception(
    exc: BaseException,
    context: str = "",
    print_to_terminal: bool = True,
) -> str:
    """
    Registra manualmente uma exceção capturada em try/except como um crash report,
    sem encerrar a aplicação. Útil para live-reload e handlers tolerantes a falhas.
    """
    report_path = generate_crash_report(
        type(exc),
        exc,
        exc.__traceback__,
        context_note=context or "Exceção registrada manualmente",
    )
    if print_to_terminal:
        print("\n" + "!" * 76)
        print("[CRASH REPORT GERADO] O erro foi gravado com sucesso:")
        print(f"    Arquivo: {report_path}")
        print("!" * 76 + "\n", flush=True)
    return report_path


def _sys_excepthook(exc_type, exc_value, exc_tb):
    """Hook global do Python para capturar exceções não tratadas na MainThread."""
    # Se for interrupção voluntária do usuário (Ctrl+C), respeita
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    report_path = generate_crash_report(
        exc_type,
        exc_value,
        exc_tb,
        context_note="Exceção não tratada na Thread Principal (sys.excepthook)",
    )

    print("\n" + "=" * 78, file=sys.stderr)
    print("[CRASH DETECTADO NA APLICACAO]", file=sys.stderr)
    print(f"   Tipo: {exc_type.__name__}: {exc_value}", file=sys.stderr)
    print("   Relatorio completo gravado em:", file=sys.stderr)
    print(f"      {report_path}", file=sys.stderr)
    print("=" * 78 + "\n", file=sys.stderr, flush=True)

    # Chama o excepthook padrão original do Python
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _threading_excepthook(args):
    """Hook global do Python para capturar exceções não tratadas em threads de background."""
    if issubclass(args.exc_type, KeyboardInterrupt):
        return

    report_path = generate_crash_report(
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
        context_note=f"Exceção não tratada na thread secundária '{args.thread.name}'",
        thread_obj=args.thread,
    )

    print("\n" + "=" * 78, file=sys.stderr)
    print(f"[CRASH DETECTADO EM THREAD: '{args.thread.name}']", file=sys.stderr)
    print(f"   Tipo: {args.exc_type.__name__}: {args.exc_value}", file=sys.stderr)
    print("   Relatorio completo gravado em:", file=sys.stderr)
    print(f"      {report_path}", file=sys.stderr)
    print("=" * 78 + "\n", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------------
# Crashes NATIVOS (acesso inválido à memória, abort() do Qt, ...)
#
# Os hooks acima só enxergam exceções do Python. Um crash nativo mata o processo sem chamar nenhum
# deles, e num .exe sem console nem a mensagem do Python aparece: não sobraria rastro algum.
# Esta parte deixa evidência em disco:
#   native_<data>_pid<N>.log  o `faulthandler` escreve aqui, no instante do crash, a pilha do Python de
#                             TODAS as threads. Sessão normal: termina com a linha de "encerrada normalmente".
#   latest_native_crash.txt   cópia do último crash nativo encontrado (criada na abertura seguinte)
#   qt_messages.log           avisos/erros/fatais do próprio Qt (ex.: "QThread: Destroyed while thread is
#                             still running"), que costumam aparecer pouco antes de um crash
# Na abertura seguinte, a sessão anterior é analisada: terminou normalmente (log descartado), crashou
# (log guardado e avisado) ou foi encerrada à força (log guardado e avisado).
# ---------------------------------------------------------------------------------------------

NATIVE_LOG_PREFIX = "native_"
CLEAN_EXIT_MARK = "=== SESSAO ENCERRADA NORMALMENTE ==="
QFATAL_MARK = "=== QFATAL DO QT"
# Escritos pelo faulthandler (crash nativo) ou pelo nosso handler (qFatal: no Windows o abort() do Qt termina o processo
# com 0xC0000409 e PULA o faulthandler, então a pilha das threads é despejada no log antes de o processo morrer)
CRASH_MARKERS = ("Windows fatal exception", "Fatal Python error", QFATAL_MARK)
MAX_NATIVE_LOGS = 15
QT_LOG_MAX_BYTES = 256 * 1024

_native_log_file = None      # precisa continuar aberto: o faulthandler só escreve no instante do crash
_qt_log_lock = threading.Lock()


def _pid_alive(pid: int) -> bool:
    """True se o processo ainda existe. (Nunca usar os.kill no Windows: sinal desconhecido ENCERRA o processo.)"""
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        # Instância PRIVADA da DLL: `ctypes.windll.kernel32` é um objeto compartilhado, e mudar o restype dele
        # alteraria o comportamento de qualquer outro código que chame as mesmas funções (ex.: win_app_icon_extractor)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return True   # na dúvida, não mexe no log de quem pode estar rodando


def _pid_from_native_name(name: str) -> int:
    try:
        return int(name.rsplit("_pid", 1)[1].split(".")[0])
    except (IndexError, ValueError):
        return -1


def _classify_native_log(text: str) -> str:
    """'clean' (terminou bem, sem crash), 'crash' (o faulthandler registrou um crash) ou 'abrupt' (sumiu sem avisar)."""
    if any(m in text for m in CRASH_MARKERS):
        return "crash"
    if CLEAN_EXIT_MARK in text:
        return "clean"
    return "abrupt"


def review_previous_sessions(reports_dir: str) -> list[str]:
    """
    Analisa os logs nativos de sessões anteriores (que não estejam mais rodando): descarta os de sessões normais,
    mantém e devolve o caminho dos que terminaram em crash ou de forma abrupta.
    """
    flagged: list[str] = []
    try:
        names = sorted(n for n in os.listdir(reports_dir) if n.startswith(NATIVE_LOG_PREFIX) and n.endswith(".log"))
    except OSError:
        return flagged
    own_pid = os.getpid()
    for name in names:
        pid = _pid_from_native_name(name)
        if pid == own_pid or _pid_alive(pid):
            continue   # sessão em andamento (inclusive outra instância aberta ao mesmo tempo)
        path = os.path.join(reports_dir, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        kind = _classify_native_log(text)
        if kind == "clean":
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        flagged.append(path)
        try:
            with open(os.path.join(reports_dir, "latest_native_crash.txt"), "w", encoding="utf-8") as f:
                label = "CRASH NATIVO" if kind == "crash" else "SESSAO ENCERRADA ABRUPTAMENTE (sem erro registrado)"
                f.write(f"{label}\nArquivo original: {path}\n{'=' * 80}\n{text}")
        except OSError:
            pass
    return flagged


def _clean_old_native_logs(reports_dir: str):
    try:
        files = sorted(glob.glob(os.path.join(reports_dir, NATIVE_LOG_PREFIX + "*.log")), key=os.path.getmtime)
        for f in files[:-MAX_NATIVE_LOGS]:
            try:
                os.remove(f)
            except OSError:
                pass
    except Exception:
        pass


def _mark_clean_exit():
    """Última linha da sessão: diz, na abertura seguinte, que o processo terminou normalmente."""
    f = _native_log_file
    if f is None:
        return
    try:
        f.write(f"\n{CLEAN_EXIT_MARK} {datetime.datetime.now().isoformat()}\n")
        f.flush()
    except Exception:
        pass


def install_native_crash_capture() -> Optional[str]:
    """
    Liga o `faulthandler` apontando para um arquivo da sessão e analisa as sessões anteriores.
    Devolve o caminho do log desta sessão (None se não foi possível).
    """
    global _native_log_file
    reports_dir = get_crash_reports_dir()

    for path in review_previous_sessions(reports_dir):
        print(f"[CrashReporter] A sessão anterior terminou de forma anormal. Evidência em: {path}",
              file=sys.stderr, flush=True)
    _clean_old_native_logs(reports_dir)

    now = datetime.datetime.now()
    path = os.path.join(reports_dir, f"{NATIVE_LOG_PREFIX}{now.strftime('%Y-%m-%d_%H-%M-%S')}_pid{os.getpid()}.log")
    try:
        pyside_version = "?"
        try:
            import PySide6
            pyside_version = PySide6.__version__
        except Exception:
            pass
        _native_log_file = open(path, "w", encoding="utf-8")
        _native_log_file.write(
            f"=== Sessão iniciada {now.isoformat()} | PID {os.getpid()} | Python {sys.version.split()[0]} | "
            f"PySide6 {pyside_version} | {platform.system()} {platform.release()} ===\n"
            f"Se houver mais texto abaixo (fora a linha final de encerramento), o processo morreu de forma abrupta.\n"
        )
        _native_log_file.flush()
        faulthandler.enable(file=_native_log_file, all_threads=True)
        atexit.register(_mark_clean_exit)
    except Exception as exc:   # a captura NUNCA pode impedir o app de abrir
        print(f"[CrashReporter] Captura de crash nativo indisponível: {exc}", file=sys.stderr)
        return None
    return path


def install_qt_message_log():
    """Grava avisos, erros e fatais do Qt em qt_messages.log (sem alterar o que já aparece no terminal)."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    labels = {QtMsgType.QtWarningMsg: "WARN", QtMsgType.QtCriticalMsg: "CRIT", QtMsgType.QtFatalMsg: "FATAL"}
    log_path = os.path.join(get_crash_reports_dir(), "qt_messages.log")

    def handler(mode, context, message):
        label = labels.get(mode)
        try:
            if sys.stderr is not None:
                print(message, file=sys.stderr, flush=True)   # comportamento padrão do Qt preservado
        except Exception:
            pass
        if label is None:   # debug/info: só ruído
            return
        if label == "FATAL" and _native_log_file is not None:
            try:   # o Qt vai abortar logo depois deste handler: este é o último momento de registrar o estado
                _native_log_file.write(f"\n{QFATAL_MARK} (o processo vai abortar): {message} ===\n")
                _native_log_file.flush()
                faulthandler.dump_traceback(file=_native_log_file, all_threads=True)
                _native_log_file.flush()
            except Exception:
                pass
        try:
            where = f" [{os.path.basename(context.file)}:{context.line}]" if getattr(context, "file", None) else ""
            line = (f"{datetime.datetime.now().isoformat(timespec='milliseconds')} {label} "
                    f"[{threading.current_thread().name}]{where} {message}\n")
            with _qt_log_lock:
                if os.path.exists(log_path) and os.path.getsize(log_path) > QT_LOG_MAX_BYTES:
                    os.replace(log_path, log_path + ".1")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line)   # aberto/fechado a cada linha: um FATAL (abort logo depois) já está em disco
        except Exception:
            pass

    qInstallMessageHandler(handler)


def install_crash_reporter():
    """
    Instala os hooks globais de captura de crash:
    - sys.excepthook para a thread principal e interface gráfica
    - threading.excepthook para todas as threads em segundo plano (GSMTC, KeyLock, AudioMixer)
    - faulthandler + marcador de sessão para crashes nativos, e o registro de mensagens do Qt
    """
    sys.excepthook = _sys_excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _threading_excepthook
    # Garante a criação do diretório
    get_crash_reports_dir()
    install_native_crash_capture()
    install_qt_message_log()
