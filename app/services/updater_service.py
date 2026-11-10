"""
Serviço de Atualização Automática (Auto-Updater) do Aimedget.
Utiliza a API pública de Releases do GitHub e CDN oficial para download.
Implementa o padrão Windows Trampoline para substituição segura de executável em execução.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from app.core.version import __version__, GITHUB_OWNER, GITHUB_REPO


@dataclass
class UpdateInfo:
    latest_version: str
    release_name: str
    body: str
    download_url: str
    asset_name: str
    published_at: str


def parse_semver(v_str: str) -> tuple:
    """Converte 'v1.2.3' ou '1.2.3' em tupla comparável (1, 2, 3)."""
    cleaned = v_str.strip().lstrip("v").strip()
    # Remove sufixos como -beta, -rc para comparação numérica
    base_part = cleaned.split("-")[0]
    parts = []
    for p in base_part.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer_version(latest_tag: str, current_tag: str = __version__) -> bool:
    """Retorna True se latest_tag for estritamente mais recente que current_tag."""
    return parse_semver(latest_tag) > parse_semver(current_tag)


class UpdateCheckWorker(QThread):
    """Thread secundária para consulta da API do GitHub sem travar a UI."""

    # Sinais emitidos:
    # update_found: (UpdateInfo)
    # up_to_date: (current_version: str)
    # check_failed: (error_message: str)
    update_found = Signal(object)
    up_to_date = Signal(str)
    check_failed = Signal(str)

    def run(self):
        api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        headers = {
            "User-Agent": f"Aimedget-App/{__version__} (Windows; x64)",
            "Accept": "application/vnd.github.v3+json",
        }

        req = urllib.request.Request(api_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                if response.status != 200:
                    self.check_failed.emit(f"Status HTTP {response.status}")
                    return

                data = json.loads(response.read().decode("utf-8"))

                tag_name = data.get("tag_name", "").strip()
                latest_clean = tag_name.lstrip("v")

                if not is_newer_version(latest_clean, __version__):
                    self.up_to_date.emit(__version__)
                    return

                # Procurar o executável nos assets da release
                assets = data.get("assets", [])
                exe_asset = None
                for a in assets:
                    name = a.get("name", "")
                    if name.lower().endswith(".exe"):
                        exe_asset = a
                        break

                if not exe_asset:
                    self.check_failed.emit("Nova versão encontrada, mas nenhum arquivo .exe anexado.")
                    return

                info = UpdateInfo(
                    latest_version=latest_clean,
                    release_name=data.get("name", f"Versão {tag_name}"),
                    body=data.get("body", "").strip(),
                    download_url=exe_asset.get("browser_download_url", ""),
                    asset_name=exe_asset.get("name", "Aimedget.exe"),
                    published_at=data.get("published_at", ""),
                )
                self.update_found.emit(info)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Nenhuma release publicada ainda no repositório
                self.up_to_date.emit(__version__)
            else:
                self.check_failed.emit(f"Erro GitHub API: {e.code} {e.reason}")
        except Exception as e:
            self.check_failed.emit(f"Falha de conexão: {str(e)}")


class DownloadWorker(QThread):
    """Thread secundária para download do executável com reporte de progresso."""

    # progresso em porcentagem (0 a 100)
    progress_changed = Signal(int)
    # concluído: (caminho_arquivo_temporario: str)
    download_finished = Signal(str)
    # falha: (mensagem_erro: str)
    download_failed = Signal(str)

    def __init__(self, download_url: str, parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        temp_dir = os.environ.get("TEMP", os.path.expanduser("~"))
        target_path = os.path.join(temp_dir, "aimedget_update_download.exe")

        headers = {
            "User-Agent": f"Aimedget-App/{__version__}",
        }
        req = urllib.request.Request(self.download_url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = response.headers.get("Content-Length")
                total_bytes = int(total_size) if total_size and total_size.isdigit() else 0

                downloaded_bytes = 0
                chunk_size = 64 * 1024  # 64 KB por bloco

                with open(target_path, "wb") as f:
                    while True:
                        if self._is_cancelled:
                            try:
                                f.close()
                                os.remove(target_path)
                            except Exception:
                                pass
                            return

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded_bytes += len(chunk)

                        if total_bytes > 0:
                            percent = int((downloaded_bytes / total_bytes) * 100)
                            self.progress_changed.emit(min(100, max(0, percent)))

                self.progress_changed.emit(100)
                self.download_finished.emit(target_path)

        except Exception as e:
            self.download_failed.emit(f"Erro no download: {str(e)}")


class UpdaterService(QObject):
    """
    Controlador de alto nível para verificação e aplicação de atualizações.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._check_worker: Optional[UpdateCheckWorker] = None
        self._download_worker: Optional[DownloadWorker] = None

    def check_for_updates(
        self,
        on_update_found=None,
        on_up_to_date=None,
        on_error=None,
    ):
        """Inicia verificação assíncrona de atualização."""
        if self._check_worker and self._check_worker.isRunning():
            return

        self._check_worker = UpdateCheckWorker(self)
        if on_update_found:
            self._check_worker.update_found.connect(on_update_found)
        if on_up_to_date:
            self._check_worker.up_to_date.connect(on_up_to_date)
        if on_error:
            self._check_worker.check_failed.connect(on_error)

        self._check_worker.start()

    def start_download(
        self,
        download_url: str,
        on_progress=None,
        on_finished=None,
        on_error=None,
    ):
        """Inicia download da nova versão."""
        if self._download_worker and self._download_worker.isRunning():
            return

        self._download_worker = DownloadWorker(download_url, self)
        if on_progress:
            self._download_worker.progress_changed.connect(on_progress)
        if on_finished:
            self._download_worker.download_finished.connect(on_finished)
        if on_error:
            self._download_worker.download_failed.connect(on_error)

        self._download_worker.start()

    @staticmethod
    def apply_update_and_restart(temp_downloaded_exe: str) -> bool:
        """
        Executa a substituição do binário atual via script Trampoline
        e reinicia o Aimedget.
        """
        # Se estiver rodando como script .py (desenvolvimento), apenas avisa
        if not getattr(sys, "frozen", False):
            print("[UpdaterService] Atualização automática só é aplicável em modo congelado (.exe).")
            return False

        current_exe = sys.executable
        current_pid = os.getpid()
        temp_dir = os.environ.get("TEMP", os.path.expanduser("~"))
        bat_script_path = os.path.join(temp_dir, "aimedget_updater_trampoline.bat")

        # Script Batch para Windows:
        # 1. Aguarda o processo atual (PID) encerrar completamente
        # 2. Sobrescreve o executável antigo com o novo
        # 3. Inicia o novo executável
        # 4. Apaga o executável temporário e deleta a si mesmo
        bat_content = f"""@echo off
chcp 65001 > nul
timeout /t 1 /nobreak > nul

:wait_loop
tasklist /fi "PID eq {current_pid}" 2>nul | find "{current_pid}" >nul
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak > nul
    goto wait_loop
)

copy /y "{temp_downloaded_exe}" "{current_exe}" > nul
del /f /q "{temp_downloaded_exe}" > nul

start "" "{current_exe}"
del "%~f0"
"""

        try:
            with open(bat_script_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            # Inicia o batch em segundo plano completamente desanexado
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS
                    | 0x08000000  # CREATE_NO_WINDOW
                )

            subprocess.Popen(
                ["cmd.exe", "/c", bat_script_path],
                shell=False,
                creationflags=creation_flags,
                close_fds=True,
            )

            # Fecha a aplicação atual para liberar o arquivo .exe
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.quit()
            else:
                sys.exit(0)

            return True

        except Exception as e:
            print(f"[UpdaterService] Erro ao disparar trampoline: {e}", file=sys.stderr)
            return False


# Instância global de conveniência
updater_service = UpdaterService()
