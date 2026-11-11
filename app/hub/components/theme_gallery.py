"""
Card "Tema visual" do Hub: galeria de miniaturas dos temas de um destino (flyout ou widget: o visual padrão + os
da pasta de temas),
no mesmo estilo da seleção de skins da Música/Timer (PreviewCard + ResponsiveCardGrid, selo "EM USO").

Um clique escolhe o tema, mostra o flyout para testar e atualiza o selo. Não há toggle de "ativo no menu":
temas não têm menu de troca rápida.
"""

import ctypes
import os
import sys
from contextlib import contextmanager
from typing import Callable

from PySide6.QtCore import QEventLoop, QStandardPaths, Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.preview_card import PreviewCard
from app.core.preview_registry import SkinSpec
from app.core.theme_loader import APP_ID, DEFAULT_ID, ThemeLoader
from app.core.theme_validation import CONTAINERS
from app.core.theme_package import (
    PACKAGE_EXT, PackageError, analyze_package, export_themes, has_theme, install_package, slugify,
)
from app.hub.components.message_dialog import confirm_destructive, show_message
from app.hub.components.responsive_grid import ResponsiveCardGrid
from app.hub.components.theme_import_dialog import TARGET_KEYS, ThemeImportDialog
from app.hub.theme import HubTheme

SpecFactory = Callable[[str, str, object], SkinSpec]   # (id do tema, título, tema carregado) -> SkinSpec


_last_dir = ""   # última pasta usada nos seletores (cache da sessão; a cópia persistente fica no config)


def _start_dir() -> str:
    """Pasta inicial do seletor: a última usada (inclusive em sessões anteriores) ou, na primeira vez, Downloads."""
    for candidate in (_last_dir, config_manager.get_last_theme_dir()):
        if candidate and os.path.isdir(candidate):
            return candidate
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or ""


@contextmanager
def _above_widgets(parent: QWidget):
    """
    Enquanto o seletor está aberto, deixa a janela do Hub "sempre no topo". O seletor nativo pertence ao Hub e
    herda isso; sem isso ele pode abrir atrás de um widget (também "sempre no topo"), e o Windows bloqueia os
    cliques no widget com o som de erro, já que o Hub está modal.
    """
    hwnd = 0
    try:
        hwnd = int(parent.window().winId()) if sys.platform == "win32" else 0
    except Exception:
        hwnd = 0
    flags = 0x0001 | 0x0002 | 0x0010   # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    user32 = ctypes.windll.user32 if hwnd else None
    if user32:
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)        # HWND_TOPMOST
    try:
        yield
    finally:
        if user32:
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)    # HWND_NOTOPMOST


def _pick(parent: QWidget, title: str, initial: str, filt: str, save: bool) -> str:
    """
    Abre o seletor bloqueando SÓ a janela do Hub (WindowModal), não o app inteiro: os widgets (Música, Timer)
    seguem clicáveis e arrastáveis enquanto o seletor está aberto. Espera por um laço de eventos local, então
    quem chama continua recebendo o caminho de forma síncrona. Devolve "" se o usuário cancelou.
    """
    dlg = QFileDialog(parent, title, initial, filt)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen)
    if not save:
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    loop = QEventLoop(dlg)
    dlg.finished.connect(loop.quit)
    dlg.open()
    loop.exec()
    files = dlg.selectedFiles() if dlg.result() == QDialog.DialogCode.Accepted else []
    dlg.deleteLater()
    return files[0] if files else ""


def _file_dialog(parent: QWidget, title: str, save: bool, suggested: str = "") -> str:
    """
    Seletor de arquivo NATIVO do Windows (o mesmo do Explorer). Funciona porque a thread principal é STA
    (RoInitialize(0) em audio_endpoint_service e CoInitializeEx(None, 2) nos serviços de áudio). Se alguém
    voltar a deixar a thread principal em MTA, o seletor nativo abre mas TRAVA o app ao fechar: nesse caso
    use `DontUseNativeDialog` de novo (seletor do Qt, que não usa COM). Ver tests/test_com_apartment.py.
    Devolve o caminho escolhido, ou "" se o usuário cancelou.
    """
    global _last_dir
    start = _start_dir()
    filt = t("theme_import_filter")
    initial = os.path.join(start, suggested) if (save and suggested) else start
    with _above_widgets(parent):
        path = _pick(parent, title, initial, filt, save)
    if save and path and not os.path.splitext(path)[1]:
        path += PACKAGE_EXT
    if path:
        _last_dir = os.path.dirname(path)
        config_manager.set_last_theme_dir(_last_dir)
    return path or ""


def _loader_for(container: str) -> ThemeLoader:
    """Loader do destino (importado sob demanda: só os módulos de tema, sem criar janelas)."""
    if container == "keylock":
        from app.widgets.keylock_osd.theme import loader
    elif container == "mixer":
        from app.widgets.volume_mixer.theme import loader
    elif container == "music":
        from app.widgets.music.skins.stack_theme import loader
    elif container == "timer":
        from app.widgets.timer.theme import loader
    else:
        raise ValueError(f"destino desconhecido: {container!r}")
    return loader


class ThemeGalleryCard(QFrame):
    """
    `loader` descobre os temas e guarda a escolha; `container` ("keylock"/"mixer"/"music"/"timer") diz de qual
    destino é a página; `make_spec` cria a miniatura; `on_applied` roda após escolher. Ao importar um pacote com
    vários destinos, `appliers` ({container: função}) aplica/mostra cada um (por padrão só o desta página).
    `subtitle_key` e `default_title_key` (chaves de tradução) trocam o texto de apoio e o nome do visual padrão.
    """

    def __init__(self, loader: ThemeLoader, container: str, make_spec: SpecFactory,
                 on_applied: Callable[[], None], theme: HubTheme,
                 appliers: dict[str, Callable[[], None]] | None = None, parent: QWidget | None = None,
                 subtitle_key: str = "theme_picker_sub", default_title_key: str = "theme_default"):
        super().__init__(parent)
        self.setProperty("class", "HubCard")
        self._subtitle_key = subtitle_key
        self._default_title_key = default_title_key
        self._loader = loader
        self._container = container
        self._make_spec = make_spec
        self._on_applied = on_applied
        self._appliers = dict(appliers) if appliers else {container: on_applied}
        self._theme = theme
        self._cards: dict[str, PreviewCard] = {}
        self._signature: tuple | None = None   # o que a galeria mostra agora (para não recriar à toa)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 22)
        root.setSpacing(0)

        header = QVBoxLayout()   # mesmo cabeçalho da seleção de skins da Música
        header.setSpacing(4)
        self.title = QLabel(t("theme_picker_title"))
        self.title.setStyleSheet("font-size: 14.5px; font-weight: 600;")
        self.sub = QLabel(t(self._subtitle_key))
        self.sub.setWordWrap(True)
        header.addWidget(self.title)
        header.addWidget(self.sub)
        root.addLayout(header)
        root.addSpacing(18)

        self._grid = ResponsiveCardGrid(min_card_width=190, spacing=16, parent=self)
        root.addWidget(self._grid)
        root.addSpacing(14)

        # Linha de ações (a importação/exportação de temas entra aqui)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.addStretch()
        self.btn_import = self._action_button(t("theme_import_btn"), self._pick_and_import)
        self.btn_export = self._action_button(t("theme_export_btn"), self._export)
        self.btn_export.setToolTip(t("theme_export_tip"))
        self.btn_delete = self._action_button(t("theme_delete_btn"), self._delete)
        self.btn_delete.setToolTip(t("theme_delete_tip"))
        self.btn_folder = self._action_button(t("theme_open_folder"), self._open_folder)
        for btn in (self.btn_import, self.btn_export, self.btn_delete, self.btn_folder):
            self.actions.addWidget(btn)
        root.addLayout(self.actions)

        self._apply_mute_color()
        self.refresh()

    # --- Conteúdo ---

    def _title_for(self, theme_id: str, name: str) -> str:
        if theme_id == DEFAULT_ID:
            return t(self._default_title_key)
        if theme_id == APP_ID:
            return t("theme_app")   # o tema embutido que herda a aparência do app é o "Padrão"
        return name or t("theme_custom")

    def _current_active(self, ids: set[str]) -> str:
        active = self._loader.active_id()
        return active if active in ids else DEFAULT_ID   # escolha salva que sumiu: o flyout usa o padrão

    def refresh(self):
        """Relê a pasta de temas. Só recria os cards se a lista (ou algum arquivo de tema) mudou."""
        themes = self._loader.list_themes()
        loaded = {th.id: self._loader.theme_for(th.id) for th in themes}   # mesmo objeto enquanto nada mudar
        signature = tuple((th.id, self._title_for(th.id, th.name), id(loaded[th.id])) for th in themes)
        active = self._current_active({th.id for th in themes})

        if signature != self._signature:
            self._signature = signature
            for card in self._cards.values():
                card.deleteLater()
            self._cards.clear()
            cards = []
            for th in themes:
                spec = self._make_spec(th.id, self._title_for(th.id, th.name), loaded[th.id])
                card = PreviewCard(spec=spec, theme=self._theme, is_selected=(th.id == active),
                                   show_badge=True, parent=self._grid)
                card.clicked.connect(self._choose)
                self._cards[th.id] = card
                cards.append(card)
            self._grid.set_cards(cards)
        else:
            self.sync_selection()

    def sync_selection(self):
        active = self._current_active(set(self._cards))
        for theme_id, card in self._cards.items():
            card.set_selected(theme_id == active)

    def _choose(self, theme_id: str):
        self._loader.set_active(theme_id)
        self.sync_selection()
        self._on_applied()

    def _action_button(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "Chip")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False: slot())
        return btn

    # --- Importar / exportar (.aimskin) ---

    def _pick_and_import(self):
        path = _file_dialog(self, t("theme_import_pick_title"), save=False)
        if path:
            self.import_package(path)

    def import_package(self, path: str) -> bool:
        """Analisa, mostra a verificação, instala o que o usuário confirmar, seleciona e mostra o flyout."""
        try:
            report = analyze_package(path)
        except PackageError as exc:
            show_message(self, self._theme, t("theme_import_title"), t("theme_import_error", why=str(exc)), "warning")
            return False
        try:
            dialog = ThemeImportDialog(report, self._theme, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            installed = install_package(report, dialog.chosen_containers, dialog.mode)
        except PackageError as exc:
            show_message(self, self._theme, t("theme_import_title"), t("theme_import_error", why=str(exc)), "warning")
            return False
        finally:
            report.close()

        for item in installed:
            _loader_for(item.container).set_active(item.theme_id)
        self.refresh()
        for item in installed:
            apply = self._appliers.get(item.container)
            if apply is not None:
                apply()
        return True

    def _export(self):
        active = self._current_active(set(self._cards))
        if self._loader.is_builtin(active):
            card = self._cards.get(active)
            name = card._spec.title if card else t(self._default_title_key)
            show_message(self, self._theme, t("theme_export_pick_title"), t("theme_export_default", name=name))
            return
        card = self._cards.get(active)
        suggested = f"{slugify(card._spec.title if card else active)}{PACKAGE_EXT}"
        path = _file_dialog(self, t("theme_export_pick_title"), save=True, suggested=suggested)
        if path:
            self.export_to(active, path)

    def export_to(self, theme_id: str, path: str) -> bool:
        """Exporta o tema para `path`. Se o MESMO tema (mesmo id) existir em outros destinos, vai junto
        (ex.: um pacote com Caps, Mixer, Música e Timer sai inteiro de qualquer uma das páginas)."""
        if not path.lower().endswith(PACKAGE_EXT):
            path += PACKAGE_EXT
        card = self._cards.get(theme_id)
        items = [(c, theme_id) for c in CONTAINERS if c == self._container or has_theme(c, theme_id)]
        try:
            count = export_themes(items, path, name=card._spec.title if card else None)
        except (PackageError, OSError) as exc:
            show_message(self, self._theme, t("theme_export_pick_title"), t("theme_export_error", why=str(exc)), "warning")
            return False
        where = ", ".join(t(TARGET_KEYS[c]) for c, _ in items)
        show_message(self, self._theme, t("theme_export_pick_title"), t("theme_export_done", n=count, where=where))
        return True

    # --- Excluir ---

    def _delete(self):
        """Exclui o tema em uso (o mesmo alvo do Exportar), depois de confirmar; oferece exportar uma cópia antes."""
        active = self._current_active(set(self._cards))
        card = self._cards.get(active)
        name = card._spec.title if card else (t(self._default_title_key) if active == DEFAULT_ID else active)
        if self._loader.is_protected(active):
            show_message(self, self._theme, t("theme_delete_title"), t("theme_delete_protected", name=name))
            return
        text = t("theme_delete_confirm", name=name)
        elsewhere = [c for c in CONTAINERS if c != self._container and has_theme(c, active)]
        if elsewhere:   # pacotes com vários destinos: só sai desta parte do app
            text += "\n\n" + t("theme_delete_elsewhere", where=", ".join(t(TARGET_KEYS[c]) for c in elsewhere))
        choice = confirm_destructive(self, self._theme, t("theme_delete_title"), text,
                                     yes=t("theme_delete_yes"), no=t("theme_import_cancel"),
                                     extra=t("theme_delete_export_first"))
        if choice == "no":
            return
        if choice == "extra":
            suggested = f"{slugify(name)}{PACKAGE_EXT}"
            path = _file_dialog(self, t("theme_export_pick_title"), save=True, suggested=suggested)
            if not path or not self.export_to(active, path):
                return   # sem cópia garantida, nada é apagado
        self.delete_theme(active)

    def delete_theme(self, theme_id: str) -> bool:
        """Apaga o tema desta parte do app e, se ele estava em uso, aplica o Padrão (o widget/flyout muda na hora)."""
        was_active = self._current_active(set(self._cards)) == theme_id
        try:
            self._loader.delete(theme_id)
        except (OSError, ValueError) as exc:
            show_message(self, self._theme, t("theme_delete_title"), t("theme_delete_error", why=str(exc)), "warning")
            return False
        self.refresh()
        if was_active:
            self._on_applied()
        return True

    def _open_folder(self):
        folder = self._loader.themes_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)  # type: ignore[attr-defined]  (Windows)
        except (OSError, AttributeError):
            pass

    # --- Tema da interface / idioma ---

    def _apply_mute_color(self):
        self.sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._apply_mute_color()
        for card in self._cards.values():
            card.set_theme(theme)

    def retranslate_ui(self):
        self.title.setText(t("theme_picker_title"))
        self.sub.setText(t(self._subtitle_key))
        self.btn_import.setText(t("theme_import_btn"))
        self.btn_export.setText(t("theme_export_btn"))
        self.btn_export.setToolTip(t("theme_export_tip"))
        self.btn_delete.setText(t("theme_delete_btn"))
        self.btn_delete.setToolTip(t("theme_delete_tip"))
        self.btn_folder.setText(t("theme_open_folder"))
        self.refresh()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
