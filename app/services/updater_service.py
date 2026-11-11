"""
Serviço de Atualização Automática (Auto-Updater) do Aimedget.

Consulta a API pública de Releases do GitHub. O app é distribuído como PASTA (PyInstaller onedir), então atualizar
não é trocar um .exe: é rodar o instalador da versão nova, que substitui a pasta inteira.
- Cópia instalada (tem o desinstalador do Inno Setup ao lado): baixa o instalador da release, confere o SHA-256 que o
  GitHub publica para o arquivo, roda em modo silencioso e o instalador reabre o app no fim.
- Cópia portátil ou desenvolvimento: não se sobrescreve; abre a página da release para o download manual.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from app.core.version import __version__, GITHUB_OWNER, GITHUB_REPO, GITHUB_RELEASES_URL

# O instalador da release (ex.: "Aimedget-Setup-1.0.1.exe"). O portátil é um .zip e nunca é baixado aqui.
_INSTALLER_ASSET = re.compile(r"setup.*\.exe$", re.IGNORECASE)
# Desinstalador que o Inno Setup deixa na pasta do app: é como o app sabe que foi instalado (e não é o portátil)
_UNINSTALLER_NAME = "unins000.exe"


@dataclass
class UpdateInfo:
    latest_version: str
    release_name: str
    body: str
    download_url: str    # instalador da release; "" se a release não tiver um
    asset_name: str
    published_at: str
    sha256: str = ""     # hash publicado pelo GitHub para o instalador ("" se a API não informar)
    page_url: str = GITHUB_RELEASES_URL   # página da release (download manual do portátil)


def pick_installer_asset(assets: list) -> dict | None:
    """O instalador entre os arquivos da release (nunca o .zip portátil nem outro .exe qualquer)."""
    for a in assets or []:
        if _INSTALLER_ASSET.search(a.get("name", "")):
            return a
    return None


def asset_sha256(asset: dict) -> str:
    """O GitHub publica `digest: "sha256:<hex>"` para cada arquivo de release; '' se não houver."""
    digest = (asset or {}).get("digest") or ""
    return digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else ""


def is_installed_build() -> bool:
    """True numa cópia instalada pelo instalador (o desinstalador do Inno fica ao lado do executável)."""
    if not getattr(sys, "frozen", False):
        return False
    return os.path.exists(os.path.join(os.path.dirname(sys.executable), _UNINSTALLER_NAME))


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

                # Sem instalador anexado a versão nova ainda é anunciada: o usuário baixa pela página da release
                installer = pick_installer_asset(data.get("assets", [])) or {}
                info = UpdateInfo(
                    latest_version=latest_clean,
                    release_name=data.get("name") or f"Versão {tag_name}",
                    body=(data.get("body") or "").strip(),
                    download_url=installer.get("browser_download_url", ""),
                    asset_name=installer.get("name", ""),
                    published_at=data.get("published_at", ""),
                    sha256=asset_sha256(installer),
                    page_url=data.get("html_url") or GITHUB_RELEASES_URL,
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

    def __init__(self, download_url: str, expected_sha256: str = "", parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.expected_sha256 = (expected_sha256 or "").lower()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        temp_dir = os.environ.get("TEMP", os.path.expanduser("~"))
        target_path = os.path.join(temp_dir, "Aimedget-Setup-update.exe")
        digest = hashlib.sha256()

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
                        digest.update(chunk)
                        downloaded_bytes += len(chunk)

                        if total_bytes > 0:
                            percent = int((downloaded_bytes / total_bytes) * 100)
                            self.progress_changed.emit(min(100, max(0, percent)))

                # Integridade: o arquivo tem que ser exatamente o que o GitHub publicou (download corrompido ou
                # trocado no caminho nunca é executado)
                if self.expected_sha256 and digest.hexdigest() != self.expected_sha256:
                    try:
                        os.remove(target_path)
                    except OSError:
                        pass
                    self.download_failed.emit("o arquivo baixado não confere com o publicado (SHA-256)")
                    return

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
        expected_sha256: str = "",
    ):
        """Inicia download do instalador da nova versão (conferido pelo SHA-256, se informado)."""
        if self._download_worker and self._download_worker.isRunning():
            return

        self._download_worker = DownloadWorker(download_url, expected_sha256, self)
        if on_progress:
            self._download_worker.progress_changed.connect(on_progress)
        if on_finished:
            self._download_worker.download_finished.connect(on_finished)
        if on_error:
            self._download_worker.download_failed.connect(on_error)

        self._download_worker.start()

    @staticmethod
    def apply_update_and_restart(downloaded_installer: str) -> bool:
        """
        Roda o instalador baixado em modo silencioso e fecha o app para liberar os arquivos. O instalador substitui
        a pasta do app e, com /UPDATE, reabre o Aimedget no fim (ver installer/Aimedget.iss). Só numa cópia instalada.
        """
        if not is_installed_build():
            return False
        try:
            subprocess.Popen(
                [downloaded_installer, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE"],
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
        except Exception as e:
            print(f"[UpdaterService] Falha ao iniciar o instalador: {e}", file=sys.stderr)
            return False

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.quit()
        else:
            sys.exit(0)
        return True


# Instância global de conveniência
updater_service = UpdaterService()
