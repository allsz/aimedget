"""
Janela Principal do Hub do Aimedget.
Design refinado com integração nativa ao Windows 11 DWM:
- A barra de título nativa se funde perfeitamente com a cor de fundo do app (claro ou escuro).
- Ícones do sistema operacional em resolução nativa perfeita (Windows Segoe Fluent Icons), idênticos aos do Discord/1Password.
- Cantos arredondados nativos do Windows 11 (DWMWCP_ROUND) preservados sem serrilhado.
- Suporte total aos Snap Layouts e atalhos de janela (Win + Setas).
"""

import sys
import time
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from app.core.config_manager import config_manager
from app.core.i18n import t
from app.core.version import __version__
from app.hub.components.message_dialog import confirm
from app.hub.components.sidebar import HubSidebar
from app.hub.dwm_helper import apply_windows_dwm_titlebar
from app.hub.hub_icon import create_aimedget_icon, create_aimedget_clean_icon, set_icon_accent
from app.hub.pages import GeneralPage, LockKeysPage, MusicPage, OverviewPage, TimerPage, VolumePage
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, get_hub_stylesheet, resolve_theme
from app.hub.tray_manager import AimedgetTrayIcon


class AimedgetHubWindow(QMainWindow):
    """Janela Shell principal do Aimedget Hub."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aimedget")   # aparece no preview da taskbar; na janela fica invisível (texto da barra pintado com a cor do fundo, ver _apply_theme)
        # Ícone sem fundo (transparente) para o cabeçalho e barra da janela do app
        self.setWindowIcon(create_aimedget_clean_icon(64))
        # Restaurar geometria salva ou aplicar tamanho padrão
        saved_geo = config_manager.get_hub_geometry()
        if saved_geo:
            x, y, w, h = saved_geo
            self.setGeometry(x, y, max(w, 850), max(h, 540))
        else:
            self.resize(1020, 680)
        self.setMinimumSize(850, 540)

        # Carregar preferência salva
        self._theme_preference = config_manager.get_hub_theme("system")
        self._current_theme: HubTheme = resolve_theme(self._theme_preference)

        self._pending_accent = config_manager.get_hub_accent()
        self._icons_pending = False
        self._accent_timer = QTimer(self)
        self._accent_timer.setSingleShot(True)
        self._accent_timer.setInterval(30)
        self._accent_timer.timeout.connect(self._flush_accent)

        # Inicializar Tray Icon
        self._quitting = False
        self.tray_icon = AimedgetTrayIcon(on_open_hub=self.show_and_activate, on_quit=self.quit_app, parent=self)
        self.tray_icon.show()
        self._offered_update = None      # versão nova encontrada, à espera da resposta do usuário
        self._offering_update = False
        self.tray_icon.messageClicked.connect(self._on_tray_message_clicked)

        self._build_ui()
        self._apply_theme(self._current_theme)
        self.retranslate_ui()
        self._apply_asymmetric_windows_icons()

        # Verificação discreta de atualizações em segundo plano após 5 segundos
        QTimer.singleShot(5000, self._check_background_update)

    def _apply_asymmetric_windows_icons(self):
        """
        Garante assimetria visual no Windows:
        - ICON_SMALL (Barra de título da janela) -> Ícone limpo sem fundo (transparente)
        - ICON_BIG (Alt+Tab / Task Switcher)     -> Ícone limpo sem fundo (transparente)
        - Barra de Tarefas e Executável (.exe)   -> Ícone oficial com fundo branco (AppUserModelID e PE Resource)
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            clean_small_img = create_aimedget_clean_icon(32).pixmap(32, 32).toImage()
            hicon_small = clean_small_img.toHICON()

            clean_big_img = create_aimedget_clean_icon(64).pixmap(64, 64).toImage()
            hicon_big = clean_big_img.toHICON()

            user32 = ctypes.windll.user32
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        except Exception:
            pass

    def _check_background_update(self):
        """
        Consulta o GitHub Releases em segundo plano, sem travar a UI. Só se o usuário deixou ligado (Geral >
        Atualizações) e no máximo uma vez por dia. Uma consulta que falhou (sem internet) não conta: tenta na próxima
        abertura.
        """
        from app.services.updater_service import is_check_due, updater_service
        if not config_manager.is_auto_update_check_enabled():
            return
        if not is_check_due(config_manager.get_last_update_check(), time.time()):
            return
        updater_service.check_for_updates(
            on_update_found=self._on_background_update_found,
            on_up_to_date=lambda _version: config_manager.set_last_update_check(time.time()),
        )

    def _on_background_update_found(self, info):
        """
        Versão nova: pergunta se o usuário quer atualizar. Com o Hub aberto, pergunta na hora; com ele na bandeja,
        avisa por um balão e a pergunta aparece ao clicar nele (nada salta na tela sem o usuário estar olhando).
        """
        config_manager.set_last_update_check(time.time())
        if info.latest_version == config_manager.get_declined_update_version():
            return   # já respondeu "agora não" para esta versão: não insiste (a consulta manual ainda mostra)
        self._offered_update = info
        if self.isVisible() and not self.isMinimized():
            self._offer_update()
            return
        if hasattr(self, "tray_icon") and self.tray_icon:
            try:
                self.tray_icon.showMessage(
                    t("update_toast_title"),
                    t("update_toast_text").format(version=info.latest_version),
                    QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
            except Exception:
                pass

    def _offer_update(self):
        """Pergunta se quer atualizar para a versão encontrada. Sim abre Geral e começa; Agora não lembra a versão."""
        info = getattr(self, "_offered_update", None)
        if info is None or self._offering_update:
            return
        self._offering_update = True
        try:
            wants = confirm(
                self, self._current_theme, t("update_prompt_title"),
                t("update_prompt_text").format(version=info.latest_version, current=__version__),
                yes=t("update_prompt_yes"), no=t("update_prompt_no"),
            )
        finally:
            self._offering_update = False
        self._offered_update = None
        if wants:
            self.sidebar.select_page("gen")
            self.page_gen.start_update(info)
        else:
            config_manager.set_declined_update_version(info.latest_version)

    def _on_tray_message_clicked(self):
        if getattr(self, "_offered_update", None) is not None:
            self.show_and_activate()
            self._offer_update()

    def show_and_activate(self):
        """Traz a janela do Hub para o primeiro plano."""
        self.show()
        self.raise_()
        self.activateWindow()
        self._apply_asymmetric_windows_icons()

    def show_music_skins(self):
        """Abre o Hub direto na página do Music Player (gerenciamento de skins)."""
        self.show_and_activate()
        self.sidebar.select_page("music")

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_asymmetric_windows_icons()

    def quit_app(self):
        """
        Encerra o Aimedget de verdade: Hub, widgets, flyouts e serviços, numa etapa só (Encerrar da bandeja, ou o X
        com "Manter na bandeja" desligado).

        Usa QApplication.exit() e não quit(): no Qt 6 o quit() PEDE para fechar todas as janelas e desiste se alguma
        recusar. O Hub recusa (com "Manter na bandeja" ele só se esconde), então o Encerrar às vezes era cancelado e
        o app ficava rodando com os widgets na tela até um segundo Encerrar.
        """
        if self._quitting:
            return
        self._quitting = True
        if self.isVisible() and not self.isMaximized() and not self.isMinimized():
            geo = self.geometry()
            config_manager.save_hub_geometry(geo.x(), geo.y(), geo.width(), geo.height())
        QApplication.exit(0)   # aboutToQuit continua disparando: os serviços são encerrados por cleanup_all

    def closeEvent(self, event: QCloseEvent):
        """X da janela: com "Manter na bandeja" só esconde o Hub; sem ele, encerra o app inteiro (widgets juntos)."""
        if self._quitting:
            event.accept()
            return
        if not self.isMaximized() and not self.isMinimized():
            geo = self.geometry()
            config_manager.save_hub_geometry(geo.x(), geo.y(), geo.width(), geo.height())

        if config_manager.is_keep_in_tray_enabled():
            event.ignore()
            self.hide()
        else:
            # Fechar só a janela deixaria os widgets vivos sem Hub e sem ícone útil: encerra tudo
            event.accept()
            QTimer.singleShot(0, self.quit_app)

    def hideEvent(self, event):
        """Garante que a geometria seja salva mesmo ao ocultar a janela."""
        if not self.isMaximized() and not self.isMinimized():
            geo = self.geometry()
            config_manager.save_hub_geometry(geo.x(), geo.y(), geo.width(), geo.height())
        super().hideEvent(event)

    def _build_ui(self):
        self.shell = QWidget(self)
        self.shell.setObjectName("HubShell")
        self.setCentralWidget(self.shell)

        main_layout = QHBoxLayout(self.shell)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Barra lateral
        self.sidebar = HubSidebar(theme=self._current_theme, parent=self.shell)
        self.sidebar.page_changed.connect(self._on_navigation)
        main_layout.addWidget(self.sidebar)

        # Stack de páginas
        self.stack = QStackedWidget(self.shell)
        main_layout.addWidget(self.stack, stretch=1)

        # Instanciar as páginas
        self.page_overview = OverviewPage(theme=self._current_theme, parent=self.stack)
        self.page_overview.customize_requested.connect(self._on_customize_requested)

        self.page_music = MusicPage(theme=self._current_theme, parent=self.stack)
        self.page_keys = LockKeysPage(theme=self._current_theme, parent=self.stack)
        self.page_vol = VolumePage(theme=self._current_theme, parent=self.stack)
        self.page_timer = TimerPage(theme=self._current_theme, parent=self.stack)
        self.page_gen = GeneralPage(
            on_theme_change=self._change_theme_mode,
            on_language_change=self._change_language,
            on_accent_change=self._change_accent,
            current_pref=self._theme_preference,
            current_lang=config_manager.get_language("pt"),
            theme=self._current_theme,
            parent=self.stack,
        )

        self.stack.addWidget(self.page_overview)  # index 0: ov
        self.stack.addWidget(self.page_music)     # index 1: music
        self.stack.addWidget(self.page_keys)      # index 2: keys
        self.stack.addWidget(self.page_vol)       # index 3: vol
        self.stack.addWidget(self.page_timer)     # index 4: timer
        self.stack.addWidget(self.page_gen)       # index 5: gen

        self._page_map = {
            "ov": 0,
            "music": 1,
            "keys": 2,
            "vol": 3,
            "timer": 4,
            "gen": 5,
        }

        # Inicializar contadores na sidebar
        # Aba Widget: exibe dinamicamente o total de skins marcadas como ativas
        # Demais abas: ocultar badges estáticos ou redundantes (count=0) para eliminar ruído visual
        active_widget_skins = config_manager.get_active_widget_skins()
        self.sidebar.set_badge_count("ov", 0)
        self.sidebar.set_badge_count("music", len(active_widget_skins))
        self.sidebar.set_badge_count("keys", 0)
        self.sidebar.set_badge_count("vol", 0)
        self.sidebar.set_badge_count("timer", 0)
        self.sidebar.set_badge_count("gen", 0)

        get_service_bridge().active_skins_changed.connect(self._on_active_skins_changed)

    def _on_active_skins_changed(self, active_skins: list):
        """Atualiza imediatamente o badge numérico da aba Widget quando skins são marcadas/desmarcadas."""
        self.sidebar.set_badge_count("music", len(active_skins))

    def _on_navigation(self, page_key: str):
        if page_key in self._page_map:
            self.stack.setCurrentIndex(self._page_map[page_key])

    def _on_customize_requested(self, widget_id: str):
        target_map = {
            "music_vinyl": "music",
            "keys_osd": "keys",
            "vol_mixer": "vol",
            "timer": "timer",
        }
        target_page = target_map.get(widget_id, "ov")
        self.sidebar.select_page(target_page)

    def _change_language(self, lang: str):
        from app.core.i18n import i18n
        i18n.set_language(lang)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.sidebar.retranslate_ui()
        self.page_overview.retranslate_ui()
        self.page_music.retranslate_ui()
        self.page_keys.retranslate_ui()
        self.page_vol.retranslate_ui()
        self.page_timer.retranslate_ui()
        self.page_gen.retranslate_ui()
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.retranslate_ui()

    def _change_theme_mode(self, mode: str):
        self._theme_preference = mode
        config_manager.set_hub_theme(mode)
        resolved = resolve_theme(mode)
        self._apply_theme(resolved)
        get_service_bridge().on_theme_changed(resolved)

    def _change_accent(self, accent, committed: bool):
        """Cor de destaque (matiz, '#RRGGBB' ou None = laranja padrão). Ao vivo enquanto arrasta; salva e atualiza
        os ícones ao soltar ou ao confirmar uma cor digitada."""
        self._pending_accent = accent
        if committed:
            config_manager.set_hub_accent(accent)
            self._accent_timer.stop()
            self._flush_accent(refresh_icons=True)
        elif not self._accent_timer.isActive():
            self._accent_timer.start()   # agrupa os eventos do arrasto (~33 por segundo)

    def _flush_accent(self, refresh_icons: bool = False):
        # Reaplicar o estilo do Hub inteiro leva ~70 ms; no meio da animação do campo de cor isso congelaria
        # alguns quadros. Espera o movimento terminar (o pedido mais recente vence).
        self._icons_pending = self._icons_pending or refresh_icons
        entry = self.page_gen.accent_entry
        if entry.is_animating():
            entry.when_idle(self._flush_accent)
            return
        refresh_icons, self._icons_pending = self._icons_pending, False
        resolved = resolve_theme(self._theme_preference, self._pending_accent)
        self._apply_theme(resolved)
        get_service_bridge().on_theme_changed(resolved)
        if refresh_icons:
            self._refresh_icons()

    def _refresh_icons(self):
        """Recolore o ícone da janela, da bandeja e do app com o matiz atual."""
        set_icon_accent(self._pending_accent)
        icon = create_aimedget_clean_icon(64)
        self.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)
        self.tray_icon.setIcon(create_aimedget_icon(32))
        self._apply_asymmetric_windows_icons()

    def _apply_theme(self, theme: HubTheme):
        self._current_theme = theme
        self.setStyleSheet(get_hub_stylesheet(theme))
        self.sidebar.update_theme(theme)
        self.page_overview.set_theme(theme)
        self.page_music.set_theme(theme)
        self.page_keys.set_theme(theme)
        self.page_vol.set_theme(theme)
        self.page_timer.set_theme(theme)
        self.page_gen.set_theme(theme)

        # Atualiza a paleta do menu do Tray em tempo real
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.update_theme(theme)

        # Aplica a cor na barra nativa e garante os cantos arredondados nativos do Windows 11
        apply_windows_dwm_titlebar(
            hwnd=int(self.winId()),
            bg_hex=theme.bg,
            text_hex=theme.bg,   # texto do título = cor da barra: invisível na janela, mas o nome aparece no preview da taskbar
            is_dark=theme.is_dark,
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AimedgetHubWindow()
    window.show()
    sys.exit(app.exec())
