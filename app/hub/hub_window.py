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
from PySide6.QtCore import QEasingCurve, QPoint, QRect, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QCloseEvent, QColor, QPalette
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
from app.core.theme_crossfade import mode_crossfade, theme_crossfade
from app.core.widget_animator import animations_enabled
from app.core.version import __version__
from app.hub.components.message_dialog import confirm
from app.hub.dwm_helper import apply_windows_dwm_titlebar, mix_hex, set_dark_frame, set_titlebar_colors
from app.hub.hub_icon import create_aimedget_icon, create_aimedget_clean_icon, set_icon_accent
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, get_hub_stylesheet, resolve_theme
from app.hub.tray_manager import AimedgetTrayIcon


# Trocar a cor do Hub inteiro leva ~70 ms de interface congelada. Aplicar isso a cada passo do arrasto derrubava o
# slider (e a onda) para 30-40 quadros por segundo. Por padrão a cor só é aplicada (e pintada) ao SOLTAR; o botão do
# seletor já mostra a cor escolhida durante o arrasto. True volta ao comportamento antigo (ao vivo, com travadas).
LIVE_APPLY_WHILE_DRAGGING = False

# Partida minimizada (arranque do Windows): o Hub não é montado na hora. Sobem só a bandeja, os serviços e os atalhos;
# as páginas são montadas na 1ª vez que o Hub abre OU, antes disso, quando a CPU do sistema se acalma (app/core/idle_gate.py). Assim
# o app fica pronto antes e a abertura do Hub pela bandeja continua instantânea.
PREBUILD_STEP_GAP_MS = 150   # respiro entre importar as páginas e montá-las


class AimedgetHubWindow(QMainWindow):
    """Janela Shell principal do Aimedget Hub."""

    def __init__(self, parent=None, defer_ui: bool = False):
        """`defer_ui=True`: não monta sidebar e páginas agora (ver app/core/idle_gate.py); `_ensure_ui()` monta."""
        super().__init__(parent)
        self._ui_built = False
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
        self._current_theme_before_mode: HubTheme = self._current_theme
        self._titlebar_hex: str | None = None   # cor que a barra nativa mostra agora (a troca de modo parte dela)

        self._pending_accent = config_manager.get_hub_accent()
        self._icons_pending = False
        self._gesture_dragged = False   # o gesto atual no seletor foi um ARRASTO (ao vivo, sem a animação de pintura)
        self._accent_timer = QTimer(self)
        self._accent_timer.setSingleShot(True)
        self._accent_timer.setInterval(30)
        self._accent_timer.timeout.connect(self._flush_accent)

        # Fade-in sutil ao exibir/restaurar o Hub: esconde o 1º frame branco do Win32/DWM
        self._reveal_anim = QVariantAnimation(self)
        self._reveal_anim.setDuration(170)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reveal_anim.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.setInterval(16)
        self._reveal_timer.timeout.connect(self._start_reveal_anim)

        # Inicializar Tray Icon
        self._quitting = False
        self.tray_icon = AimedgetTrayIcon(on_open_hub=self.show_and_activate, on_quit=self.quit_app, parent=self)
        self.tray_icon.show()
        self._offered_update = None      # versão nova encontrada, à espera da resposta do usuário
        self._offering_update = False
        self.tray_icon.messageClicked.connect(self._on_tray_message_clicked)

        if defer_ui:
            # Só a bandeja já precisa do tema e do idioma
            self.tray_icon.update_theme(self._current_theme)
            self.tray_icon.retranslate_ui()
        else:
            self._ensure_ui()

        # Modo "Sistema": acompanha o Windows ao vivo (claro/escuro), não só ao abrir o app
        hints = QApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)

        # Verificação discreta de atualizações em segundo plano após 5 segundos
        QTimer.singleShot(5000, self._check_background_update)

    def _ensure_ui(self):
        """Monta sidebar e páginas (uma vez). Chamado antes de qualquer coisa que precise delas."""
        if self._ui_built:
            return
        self._ui_built = True
        from app.core import startup_trace
        from app.hub.components.accent_wipe import AccentWipe
        t0 = time.perf_counter()
        self._build_ui()
        self._accent_wipe = AccentWipe(self.shell)
        self._apply_theme(self._current_theme)
        self.retranslate_ui()
        self._apply_asymmetric_windows_icons()
        startup_trace.amend("hub_ui_cost", (time.perf_counter() - t0) * 1000)

    def prebuild_ui(self):
        """Monta o Hub escondido, em duas etapas com respiro entre elas (imports, depois as páginas), para a primeira
        abertura pela bandeja não esperar sem congelar de uma vez os widgets que já estão na tela."""
        if self._quitting or self._ui_built:
            return
        self._import_pages()
        QTimer.singleShot(PREBUILD_STEP_GAP_MS, lambda: None if self._quitting else self._ensure_ui())

    @staticmethod
    def _import_pages():
        """Só carrega os módulos das páginas (a parte mais cara do 1º Hub); `_build_ui` os reencontra em cache."""
        from app.hub.components import page_transition, sidebar   # noqa: F401
        from app.hub import battery_page, pages, performance_page, storage_page, weather_page   # noqa: F401

    def _apply_asymmetric_windows_icons(self):
        """
        Garante assimetria visual no Windows:
        - ICON_SMALL (Barra de título da janela) -> Ícone limpo sem fundo (transparente)
        - ICON_BIG (Alt+Tab / Task Switcher)     -> Ícone limpo sem fundo (transparente)
        - Barra de Tarefas e Executável (.exe)   -> Ícone oficial com fundo branco (AppUserModelID e PE Resource);
          em desenvolvimento (Aimedget.Hub.Dev), usa o HICON da janela com o selo vermelho DEV.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(self.winId())
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            GCLP_HICON = -14
            GCLP_HICONSM = -34

            clean_small_img = create_aimedget_clean_icon(32).pixmap(32, 32).toImage()
            hicon_small = int(clean_small_img.toHICON())

            clean_big_img = create_aimedget_clean_icon(64).pixmap(64, 64).toImage()
            hicon_big = int(clean_big_img.toHICON())

            user32 = ctypes.windll.user32
            send_msg = user32.SendMessageW
            send_msg.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            send_msg.restype = wintypes.LPARAM

            send_msg(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            send_msg(hwnd, WM_SETICON, ICON_BIG, hicon_big)

            # Atualiza também os ícones da classe da janela para que a barra de tarefas em modo DEV
            # (sem atalho no Menu Iniciar para Aimedget.Hub.Dev) não volte para o ícone do python.exe.
            set_class_long = getattr(user32, "SetClassLongPtrW", user32.SetClassLongW)
            set_class_long.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPARAM]
            set_class_long.restype = wintypes.LPARAM
            set_class_long(hwnd, GCLP_HICONSM, hicon_small)
            set_class_long(hwnd, GCLP_HICON, hicon_big)

            # Libera os HICONs antigos criados por nós (evita vazamento de handles GDI)
            old_hicons = getattr(self, "_win_hicons", ())
            self._win_hicons = (hicon_small, hicon_big)
            if old_hicons:
                destroy_icon = user32.DestroyIcon
                destroy_icon.argtypes = [wintypes.HICON]
                destroy_icon.restype = wintypes.BOOL
                for old in old_hicons:
                    if old and old not in self._win_hicons:
                        destroy_icon(old)
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
            self._ensure_ui()
            self.sidebar.select_page("gen")
            self.page_gen.start_update(info)
        else:
            config_manager.set_declined_update_version(info.latest_version)

    def _on_tray_message_clicked(self):
        if getattr(self, "_offered_update", None) is not None:
            self.show_and_activate()
            self._offer_update()

    def _bring_to_front(self):
        """Garante restauração, foco e Z-order no Windows (inclusive após fechar um QMenu de widget flutuante)."""
        if not self.isVisible():
            return
        if self.isMinimized():
            self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                user32 = ctypes.windll.user32
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def _start_reveal_anim(self):
        """Inicia o fade-in suave após o primeiro frame pintado (evitando o flash branco do Win32/DWM)."""
        if not self.isVisible():
            self.setWindowOpacity(1.0)
            return
        if not animations_enabled():
            self.setWindowOpacity(1.0)
            return
        self._reveal_anim.stop()
        self._reveal_anim.setStartValue(self.windowOpacity())
        self._reveal_anim.setEndValue(1.0)
        self._reveal_anim.start()

    def show_and_activate(self):
        """Traz a janela do Hub para o primeiro plano com fade-in suave (sem flash branco do Windows)."""
        self._ensure_ui()
        needs_reveal = (not self.isVisible()) or self.isMinimized()
        self._reveal_timer.stop()
        self._reveal_anim.stop()
        if needs_reveal:
            self.setWindowOpacity(0.0)
        if self.isMinimized():
            self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.show()
        self._bring_to_front()
        self._apply_asymmetric_windows_icons()
        # Quando disparado de dentro de um QMenu.exec() de widget flutuante, o fechamento do popup pode devolver
        # o foco ao widget logo após `triggered`: reforça a ativação no próximo tick do loop de eventos.
        QTimer.singleShot(0, self._bring_to_front)
        if needs_reveal:
            self._reveal_timer.start()
        elif self.windowOpacity() < 1.0:
            self.setWindowOpacity(1.0)

    def show_music_skins(self):
        """Abre o Hub direto na seção de skins da página do Music Player."""
        self._ensure_ui()
        self.sidebar.select_page("music")
        self.show_and_activate()
        self.page_music.focus_skins()

    def show_weather_cities(self):
        """Abre o Hub direto na seção de cidades da página do Clima (pelo menu do cartão)."""
        self._ensure_ui()
        self.sidebar.select_page("weather")
        self.show_and_activate()
        self.page_weather.focus_cities()

    def show_widget_page(self, page_id: str):
        """Abre o Hub na página de configuração de um widget ("Configurar" no menu do widget)."""
        self._ensure_ui()
        self.sidebar.select_page(page_id)
        self.show_and_activate()

    def showEvent(self, event):
        self._ensure_ui()   # quem chama show() direto (sem show_and_activate) também recebe o Hub montado
        super().showEvent(event)
        self._apply_asymmetric_windows_icons()
        # Depois do fade-in, monta as miniaturas da página Música em segundo plano (a 1ª visita não trava mais).
        from app.widgets.music.skins.specs import warm_previews
        warm_previews()

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
        self._reveal_timer.stop()
        self._reveal_anim.stop()
        if not self.isMaximized() and not self.isMinimized():
            geo = self.geometry()
            config_manager.save_hub_geometry(geo.x(), geo.y(), geo.width(), geo.height())
        super().hideEvent(event)

    def _build_ui(self):
        # Importados aqui (e não no topo): na partida minimizada o Hub só é montado depois, e estes módulos pesam
        # cerca de 0,4 s de import
        from app.hub.components.page_transition import PageTransition
        from app.hub.components.sidebar import HubSidebar
        from app.hub.pages import GeneralPage, LockKeysPage, MusicPage, OverviewPage, TimerPage, VolumePage
        from app.hub.performance_page import PerformancePage
        from app.hub.storage_page import StoragePage
        from app.hub.battery_page import BatteryPage
        from app.hub.weather_page import WeatherPage

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
        self._page_transition = PageTransition(self.stack)

        # Instanciar as páginas
        self.page_overview = OverviewPage(theme=self._current_theme, parent=self.stack)
        self.page_overview.customize_requested.connect(self._on_customize_requested)

        self.page_music = MusicPage(theme=self._current_theme, parent=self.stack)
        self.page_keys = LockKeysPage(theme=self._current_theme, parent=self.stack)
        self.page_vol = VolumePage(theme=self._current_theme, parent=self.stack)
        self.page_timer = TimerPage(theme=self._current_theme, parent=self.stack)
        self.page_weather = WeatherPage(theme=self._current_theme, parent=self.stack)
        self.page_performance = PerformancePage(theme=self._current_theme, parent=self.stack)
        self.page_storage = StoragePage(theme=self._current_theme, parent=self.stack)
        self.page_battery = BatteryPage(theme=self._current_theme, parent=self.stack)
        self.page_gen = GeneralPage(
            on_theme_change=self._change_theme_mode,
            on_language_change=self._change_language,
            on_accent_change=self._change_accent,
            current_pref=self._theme_preference,
            current_lang=config_manager.get_language("pt"),
            theme=self._current_theme,
            parent=self.stack,
        )

        self.stack.addWidget(self.page_overview)     # index 0: ov
        self.stack.addWidget(self.page_music)        # index 1: music
        self.stack.addWidget(self.page_keys)         # index 2: keys
        self.stack.addWidget(self.page_vol)          # index 3: vol
        self.stack.addWidget(self.page_timer)        # index 4: timer
        self.stack.addWidget(self.page_weather)      # index 5: weather
        self.stack.addWidget(self.page_performance)  # index 6: performance
        self.stack.addWidget(self.page_storage)      # index 7: storage
        self.stack.addWidget(self.page_battery)      # index 8: battery
        self.stack.addWidget(self.page_gen)          # index 9: gen

        self._page_map = {
            "ov": 0,
            "music": 1,
            "keys": 2,
            "vol": 3,
            "timer": 4,
            "weather": 5,
            "performance": 6,
            "storage": 7,
            "battery": 8,
            "gen": 9,
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
        self.sidebar.set_badge_count("weather", 0)
        self.sidebar.set_badge_count("performance", 0)
        self.sidebar.set_badge_count("storage", 0)
        self.sidebar.set_badge_count("battery", 0)
        self.sidebar.set_badge_count("gen", 0)

        bridge = get_service_bridge()
        bridge.active_skins_changed.connect(self._on_active_skins_changed)

    def _on_active_skins_changed(self, active_skins: list):
        """Atualiza imediatamente o badge numérico da aba Widget quando skins são marcadas/desmarcadas."""
        self.sidebar.set_badge_count("music", len(active_skins))

    def _on_navigation(self, page_key: str):
        self._stop_wipe()   # a foto é da página antiga
        if page_key not in self._page_map:
            return
        self.stack.setCurrentIndex(self._page_map[page_key])

    def _on_customize_requested(self, widget_id: str):
        target_map = {
            "music_vinyl": "music",
            "keys_osd": "keys",
            "vol_mixer": "vol",
            "timer": "timer",
            "weather": "weather",
            "performance": "performance",
            "storage": "storage",
            "battery": "battery",
        }
        target_page = target_map.get(widget_id, "ov")
        self.sidebar.select_page(target_page)

    def _change_language(self, lang: str):
        from app.core.i18n import i18n
        i18n.set_language(lang)
        self.retranslate_ui()

    def retranslate_ui(self):
        if not getattr(self, "_ui_built", True):
            if self.tray_icon:
                self.tray_icon.retranslate_ui()
            return
        self._stop_wipe()
        self.sidebar.retranslate_ui()
        self.page_overview.retranslate_ui()
        self.page_music.retranslate_ui()
        self.page_keys.retranslate_ui()
        self.page_vol.retranslate_ui()
        self.page_timer.retranslate_ui()
        self.page_weather.retranslate_ui()
        self.page_performance.retranslate_ui()
        self.page_storage.retranslate_ui()
        self.page_battery.retranslate_ui()
        self.page_gen.retranslate_ui()
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.retranslate_ui()

    def _change_theme_mode(self, mode: str):
        self._stop_wipe()
        self._theme_preference = mode
        config_manager.set_hub_theme(mode)
        self._switch_mode_animated(resolve_theme(mode))

    def _on_system_color_scheme_changed(self, *_args):
        """O Windows trocou de claro/escuro: no modo "Sistema", o Hub e os widgets que seguem o app trocam juntos,
        com a mesma dissolvência da troca manual. Os visuais "Windows" dos flyouts (Caps/Num Lock e Volume) são a
        exceção: seguem SEMPRE o Windows, então trocam (miniaturas e flyouts) mesmo com o app fixo em claro ou escuro."""
        if not getattr(self, "_ui_built", True):
            # Hub ainda não montado: só acompanha o tema (a bandeja e os widgets seguem o Windows; as páginas nascem
            # já com o tema certo quando forem montadas)
            if self._theme_preference == "system":
                resolved = resolve_theme("system")
                if resolved != self._current_theme:
                    self._current_theme = self._current_theme_before_mode = resolved
                    self.tray_icon.update_theme(resolved)
                    get_service_bridge().on_theme_changed(resolved)
            get_service_bridge().on_windows_mode_changed()
            return
        if self._theme_preference == "system":
            resolved = resolve_theme("system")
            if resolved != self._current_theme:
                self._stop_wipe()
                self._switch_mode_animated(resolved)   # já atualiza os visuais "Windows" dentro da dissolvência
                return
        with mode_crossfade(self.shell):
            self._refresh_windows_looks()

    def _refresh_windows_looks(self):
        """Miniaturas (galerias e Visão geral) e flyouts com o visual "Windows" releem o modo do Windows. Barato quando
        nada mudou: as galerias só recriam os cartões se o objeto do tema mudou."""
        for page in (getattr(self, "page_keys", None), getattr(self, "page_vol", None)):
            if page is not None:
                page.theme_picker.refresh()
        if getattr(self, "page_overview", None) is not None:
            self.page_overview.refresh_flyout_cards()
        get_service_bridge().on_windows_mode_changed()

    def _switch_mode_animated(self, resolved: HubTheme):
        """Claro/escuro: a janela dissolve em 300 ms (curva in-out) e a barra de título nativa muda de cor junto,
        quadro a quadro, com a mesma curva (protótipo mockups/theme-mode-transition.html, variante C)."""
        hwnd = int(self.winId())
        start = self._titlebar_hex or self._current_theme.bg
        target = resolved.bg
        dark_sent = [None]

        def _titlebar(e: float):
            color = target if e >= 1.0 else mix_hex(start, target, e)
            self._titlebar_hex = color
            set_titlebar_colors(hwnd, color, color)   # título = cor da barra (ver _apply_theme)
            want_dark = resolved.is_dark if e >= 0.5 else self._current_theme_before_mode.is_dark
            if dark_sent[0] != want_dark:   # botões do quadro trocam no meio, quando a barra cruza o cinza
                dark_sent[0] = want_dark
                set_dark_frame(hwnd, want_dark)

        self._current_theme_before_mode = self._current_theme
        with mode_crossfade(self.shell, on_progress=_titlebar):
            self._apply_theme(resolved, titlebar=False)
            get_service_bridge().on_theme_changed(resolved)
            self._refresh_windows_looks()   # o Windows pode ter trocado de modo junto (app em "Sistema")

    def _change_accent(self, accent, committed: bool):
        """Cor de destaque (matiz, '#RRGGBB' ou None = laranja padrão). Ao vivo enquanto arrasta; salva e atualiza
        os ícones ao soltar ou ao confirmar uma cor digitada."""
        self._pending_accent = accent
        if committed:
            config_manager.set_hub_accent(accent)
            self._accent_timer.stop()
            self._flush_accent(refresh_icons=True)
            self._gesture_dragged = False
        elif LIVE_APPLY_WHILE_DRAGGING:
            if self.page_gen.hue_slider.is_wave_dragging():
                self._gesture_dragged = True   # ao vivo: a cor segue o dedo, sem a animação de pintura
            if not self._accent_timer.isActive():
                self._accent_timer.start()   # agrupa os eventos do arrasto (~33 por segundo)
        # Sem aplicação ao vivo: só guarda a cor pedida; ela é aplicada, pintada, ao soltar (commit)

    def _stop_wipe(self):
        wipe = getattr(self, "_accent_wipe", None)   # ainda não existe durante a montagem da janela
        if wipe is not None:
            wipe.stop()

    def _can_wipe(self) -> bool:
        """A pintura animada só vale com a janela à vista, no tamanho final e com os efeitos do Windows ligados."""
        return animations_enabled() and self.isVisible() and not self._gesture_dragged and self.shell.width() > 1

    def _wipe_excluded_rects(self) -> list[QRect]:
        """Controles que ficam AO VIVO durante a pintura (respondem na hora ao clique): o seletor e o campo de cor."""
        rects = []
        for w in (self.page_gen.hue_slider, self.page_gen.accent_entry):
            if w.isVisible():
                rects.append(QRect(w.mapTo(self.shell, QPoint(0, 0)), w.size()).adjusted(-6, -6, 6, 6))
        return rects

    def _wipe_carved_rects(self) -> list[QRect]:
        """Os círculos de tema (claro/escuro/preto/sistema) ficam acima do seletor, e a margem do seletor invade o
        pé deles: sem isto só o arco de baixo do anel mudava de cor na hora e o resto esperava a onda."""
        group = getattr(self.page_gen, "_theme_group", None)
        if group is None or not group.isVisible():
            return []
        return [QRect(group.mapTo(self.shell, QPoint(0, 0)), group.size())]

    def _apply_accent_theme(self, resolved: HubTheme, animate: bool):
        """Aplica a cor nova. Animado: foto da janela antiga, troca por baixo e a cor nova é "pintada" da esquerda
        para a direita por cima (a troca em si, ~70 ms, fica escondida atrás da foto)."""
        if animate:
            snapshot = self.shell.grab()
            excluded = self._wipe_excluded_rects()
            carved = self._wipe_carved_rects()
        self._apply_theme(resolved)
        get_service_bridge().on_theme_changed(resolved)
        if animate:
            self._accent_wipe.start(snapshot, excluded, carved)

    def _flush_accent(self, refresh_icons: bool = False):
        self._icons_pending = self._icons_pending or refresh_icons
        animate = self._can_wipe()
        entry = self.page_gen.accent_entry
        # Reaplicar o estilo do Hub inteiro (~70 ms, mais a foto) trava a thread da interface: no meio da animação do
        # campo de cor congelaria alguns quadros (um clique no seletor liga o "Redefinir" e solta o botão em seguida).
        # Então espera o movimento terminar (o pedido mais recente vence); a pintura começa logo depois.
        if entry.is_animating():
            entry.when_idle(self._flush_accent)
            return
        refresh_icons, self._icons_pending = self._icons_pending, False
        resolved = resolve_theme(self._theme_preference, self._pending_accent)
        if resolved != self._current_theme:   # soltar o seletor depois de arrastar repete a cor já aplicada ao vivo
            self._accent_wipe.stop()
            self._apply_accent_theme(resolved, animate)
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

    def _apply_theme(self, theme: HubTheme, titlebar: bool = True):
        """`titlebar=False`: a barra nativa fica com quem chamou (a troca de modo a anima junto com a dissolvência)."""
        self._current_theme = theme
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(theme.bg))
        self.setPalette(pal)
        self.setStyleSheet(get_hub_stylesheet(theme))
        self.sidebar.update_theme(theme)
        self.page_overview.set_theme(theme)
        self.page_music.set_theme(theme)
        self.page_keys.set_theme(theme)
        self.page_vol.set_theme(theme)
        self.page_timer.set_theme(theme)
        self.page_weather.set_theme(theme)
        self.page_performance.set_theme(theme)
        self.page_storage.set_theme(theme)
        self.page_battery.set_theme(theme)
        self.page_gen.set_theme(theme)

        # Atualiza a paleta do menu do Tray em tempo real
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.update_theme(theme)

        if not titlebar:
            return
        # Aplica a cor na barra nativa e garante os cantos arredondados nativos do Windows 11
        self._titlebar_hex = theme.bg
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
