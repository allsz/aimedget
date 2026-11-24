"""
HubServiceBridge - Ponte central de comunicação entre o Aimedget Hub e os serviços de background.
Gerencia instâncias únicas de MusicController, KeyLockService/Flyout e AudioMixerService/Flyout.
"""

from typing import Optional
from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtWidgets import QApplication

from app.core.anchor_manager import anchor_manager
from app.core.config_manager import config_manager
from app.core.osd_anchor import link_flyouts
from app.core.theme_crossfade import theme_crossfade
from app.services.audio_endpoint_service import AudioEndpointService
from app.services.audio_mixer_service import AudioMixerService
from app.services.hotkey_service import get_hotkey_service
from app.services.keylock_service import KeyLockService
from app.services.player_volume import find_session_for_player
from app.widgets.keylock_osd.keylock_flyout import KeyLockFlyout
from app.widgets.music.music_controller import MusicWidgetController
from app.widgets.music.volume_osd import MusicVolumeOSD
from app.widgets.timer.timer_controller import TimerWidgetController
from app.widgets.volume_mixer.mixer_flyout import VolumeMixerFlyout
from app.widgets.performance.performance_controller import PerformanceWidgetController
from app.widgets.storage.storage_controller import StorageWidgetController
from app.widgets.battery.battery_controller import BatteryWidgetController
from app.widgets.weather.weather_controller import WeatherWidgetController


# Passo do volume por entalhe da roda do mouse sobre o Music Widget (em % do volume master)
MUSIC_WHEEL_VOLUME_STEP = 2


class HubServiceBridge(QObject):
    """
    Gerenciador unificado dos serviços e widgets do desktop.
    Permite que o Hub ligue/desligue widgets e reposicione-os na tela.
    """

    status_changed = Signal(str, bool)  # widget_id, is_active
    music_skin_changed = Signal(str)  # skin_name
    manage_music_skins_requested = Signal()
    music_scale_changed = Signal(object)  # float or None
    active_skins_changed = Signal(list)  # list of active skin ids
    timer_skin_changed = Signal(str)  # skin_name
    weather_skin_changed = Signal(str)  # id da skin (fonte)
    performance_skin_changed = Signal(str)
    manage_weather_cities_requested = Signal()
    configure_widget_requested = Signal(str)  # id da página do Hub ("music", "weather"...)
    osd_anchor_changed = Signal(str, str)  # (flyout 'keylock'/'mixer', âncora)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. Módulo de Música
        self.music_controller = MusicWidgetController()
        self.music_controller.skin_changed.connect(self.music_skin_changed.emit)
        self.music_controller.manage_skins_requested.connect(self.manage_music_skins_requested.emit)
        self._wheel_remainder = 0.0
        self.music_volume_osd = MusicVolumeOSD()
        self.music_controller.volume_wheel_requested.connect(self._on_music_volume_wheel)
        self.music_controller.scale_changed.connect(self.music_scale_changed.emit)

        # 2. Módulo de Caps / Num Lock
        self.keylock_flyout = KeyLockFlyout()
        self.keylock_service = KeyLockService()
        self.keylock_service.keylock_changed.connect(self._on_keylock_changed)

        # 3. Módulo de Volume Mixer
        self.volume_flyout = VolumeMixerFlyout()
        self.audio_service = AudioMixerService()
        self.audio_service.master_volume_changed.connect(self.volume_flyout.on_master_volume_changed)
        self.audio_service.sessions_updated.connect(self.volume_flyout.on_sessions_updated)
        self.audio_service.osd_requested.connect(self.volume_flyout.show_osd)

        self.volume_flyout.master_volume_dragged.connect(self.audio_service.set_master_volume)
        self.volume_flyout.master_mute_toggled.connect(self.audio_service.toggle_master_mute)
        self.volume_flyout.app_volume_dragged.connect(self.audio_service.set_app_volume)
        self.volume_flyout.app_mute_toggled.connect(self.audio_service.toggle_app_mute)
        self.volume_flyout.refresh_requested.connect(self.audio_service.refresh_sessions)
        # A lista de apps só é varrida periodicamente enquanto o mixer está na tela
        self.volume_flyout.visibility_changed.connect(self.audio_service.set_live_sessions)

        # Empilhamento cooperativo nos dois sentidos + âncora salva (compartilhada pelos dois flyouts)
        self.osd_stack = link_flyouts(self.keylock_flyout, self.volume_flyout)

        # Roteamento de áudio por aplicativo (Opção B - Gaveta Inline)
        self.endpoint_service = AudioEndpointService(mixer_service=self.audio_service)
        self.endpoint_service.endpoints_updated.connect(
            lambda: self.volume_flyout.on_endpoints_updated(
                self.endpoint_service.get_endpoints("output"),
                self.endpoint_service.get_endpoints("input"),
            )
        )
        self.volume_flyout.app_routing_changed.connect(self.endpoint_service.set_app_device)
        # Gaveta do ícone do volume principal (botão direito): troca o dispositivo PADRÃO do Windows
        self.volume_flyout.default_device_changed.connect(self.endpoint_service.set_default_device)
        # O mixer precisa saber a rota de cada app para mostrar o volume da sessão certa quando o app tem sessões em
        # mais de um dispositivo (ex.: Chrome roteado para o fone, com uma sessão parada nas caixas)
        self.audio_service.set_route_resolver(lambda app_id: self.endpoint_service.get_app_device(app_id, "output"))
        self.endpoint_service.app_routing_changed.connect(self.audio_service.on_app_route_changed)
        self.volume_flyout.on_endpoints_updated(
            self.endpoint_service.get_endpoints("output"),
            self.endpoint_service.get_endpoints("input"),
        )

        # Sincroniza estado inicial do áudio
        self.volume_flyout.on_master_volume_changed(
            self.audio_service.get_master_volume(), self.audio_service.get_master_mute()
        )
        self.volume_flyout.on_sessions_updated(self.audio_service._cached_sessions)

        # 4. Módulo de Timer Widget
        self.timer_controller = TimerWidgetController()
        self.timer_controller.status_changed.connect(self._on_timer_status_changed)
        self.timer_controller.skin_changed.connect(self.timer_skin_changed.emit)

        # 5. Módulo de Clima (a rede só é consultada com o cartão na tela)
        self.weather_controller = WeatherWidgetController()
        self.weather_controller.status_changed.connect(self._on_weather_status_changed)
        self.weather_controller.skin_changed.connect(self.weather_skin_changed.emit)
        self.weather_controller.manage_cities_requested.connect(self.manage_weather_cities_requested.emit)

        # 5b. Módulo de Desempenho (sampler Win32 só roda com o cartão na tela)
        self.performance_controller = PerformanceWidgetController()
        self.performance_controller.status_changed.connect(self._on_performance_status_changed)
        self.performance_controller.skin_changed.connect(self.performance_skin_changed.emit)

        # 5c. Módulo de Armazenamento (varredura em background só roda com o cartão na tela)
        self.storage_controller = StorageWidgetController()
        self.storage_controller.status_changed.connect(self._on_storage_status_changed)

        # 5d. Módulo de Baterias (leitura dos periféricos só roda com o cartão na tela)
        self.battery_controller = BatteryWidgetController()
        self.battery_controller.status_changed.connect(self._on_battery_status_changed)
        self._wire_configure_requests()

        # 6. Serviço Global de Atalhos (Hotkeys)
        self.hotkey_service = get_hotkey_service()
        self._init_hotkeys()

        # Estados de ativação
        self._states = {
            "music_vinyl": config_manager.is_music_enabled(),
            "keys_osd": True,
            "vol_mixer": True,
            "timer": config_manager.is_timer_show_on_startup(),
            "weather": bool(config_manager.get_weather("show_on_startup", False)),
            "performance": bool(config_manager.get_performance("show_on_startup", False)),
            "storage": bool(config_manager.get_storage("show_on_startup", False)),
            "battery": bool(config_manager.get_battery("show_on_startup", False)),
        }

    def _wire_configure_requests(self):
        """"Configurar" no menu de cada widget abre o Hub na página dele."""
        for page_id, controller in (("music", self.music_controller), ("timer", self.timer_controller),
                                    ("weather", self.weather_controller), ("performance", self.performance_controller),
                                    ("storage", self.storage_controller), ("battery", self.battery_controller)):
            controller.configure_requested.connect(lambda _p=page_id: self.configure_widget_requested.emit(_p))

    def start_all(self):
        """Inicializa os widgets no desktop de acordo com as preferências salvas."""
        # Se o widget de música estiver ativado, exibe ou inicia modo auto
        if self._states.get("music_vinyl", True):
            self.music_controller.start()

        # O timer só aparece ao iniciar se o usuário optou; caso contrário, fica
        # disponível pelo atalho global (Win+Alt+T)
        if config_manager.is_timer_show_on_startup():
            self.timer_controller.start()

        if config_manager.get_weather("show_on_startup", False):
            self.weather_controller.start()

        if config_manager.get_performance("show_on_startup", False):
            self.performance_controller.start()

        if config_manager.get_storage("show_on_startup", False):
            self.storage_controller.start()

        if config_manager.get_battery("show_on_startup", False):
            self.battery_controller.start()

    # --- Atalhos Globais e Ações de Toggle ---

    def _init_hotkeys(self):
        # Music Player (padrão Win+Alt+M)
        music_hk = config_manager.get_music_hotkey("Win+Alt+M")
        self.hotkey_service.register("music_toggle", music_hk, self.toggle_music_widget)

        # Timer Widget (padrão Win+Alt+T)
        timer_hk = config_manager.get_timer_hotkey("Win+Alt+T")
        self.hotkey_service.register("timer_toggle", timer_hk, self.toggle_timer_widget)

        # Weather Widget (padrão Win+Alt+W)
        weather_hk = config_manager.get_weather("hotkey", "Win+Alt+W")
        self.hotkey_service.register("weather_toggle", weather_hk, self.toggle_weather_widget)

        # Performance Widget (padrão Win+Alt+P)
        perf_hk = config_manager.get_performance("hotkey", "Win+Alt+P")
        self.hotkey_service.register("performance_toggle", perf_hk, self.toggle_performance_widget)

        # Storage Widget (padrão Win+Alt+S)
        storage_hk = config_manager.get_storage("hotkey", "Win+Alt+S")
        self.hotkey_service.register("storage_toggle", storage_hk, self.toggle_storage_widget)

        # Battery Widget (padrão Win+Alt+E; Win+Alt+B é do HDR do Windows)
        battery_hk = config_manager.get_battery("hotkey", "Win+Alt+E")
        self.hotkey_service.register("battery_toggle", battery_hk, self.toggle_battery_widget)

        # Volume Mixer (padrão Win+Alt+V)
        vol_hk = config_manager.get_volume_hotkey("Win+Alt+V")
        self.hotkey_service.register("volume_toggle", vol_hk, self.toggle_volume_mixer)

        # Lock Keys (padrão Win+Alt+K)
        keys_hk = config_manager.get_keylock_hotkey("Win+Alt+K")
        self.hotkey_service.register("keys_test", keys_hk, lambda: self.trigger_test_keylock("Caps Lock", True))

    def toggle_music_widget(self):
        """Alterna a visibilidade do Music Player."""
        controller = self.music_controller
        if controller.is_shown():
            controller.hide(by_user=True)
        else:
            if not controller.is_hiding():  # apertar de novo no meio da saída apenas reverte
                controller.restore_or_center_position()
            controller.show(is_manual=True)
            if self.music_controller.skin:
                self.music_controller.skin.raise_()
                self.music_controller.skin.activateWindow()

    def toggle_timer_widget(self):
        """Alterna a visibilidade do Timer Widget."""
        if self.timer_controller.is_shown():   # saindo (fade-out em curso) conta como escondido: o atalho o traz de volta
            self.set_timer_enabled(False)
        else:
            self.set_timer_enabled(True)
            if self.timer_controller.skin:
                self.timer_controller.skin.raise_()
                self.timer_controller.skin.activateWindow()

    def toggle_weather_widget(self):
        """Alterna a visibilidade do Weather Widget."""
        if self.weather_controller.is_shown():
            self.set_weather_enabled(False)
        else:
            self.set_weather_enabled(True)
            self.weather_controller.skin.raise_()
            self.weather_controller.skin.activateWindow()

    def toggle_performance_widget(self):
        """Alterna a visibilidade do Performance Widget."""
        if self.performance_controller.is_shown():
            self.set_performance_enabled(False)
        else:
            self.set_performance_enabled(True)
            self.performance_controller.skin.raise_()
            self.performance_controller.skin.activateWindow()

    def toggle_storage_widget(self):
        """Alterna a visibilidade do Storage Widget."""
        if self.storage_controller.is_shown():
            self.set_storage_enabled(False)
        else:
            self.set_storage_enabled(True)
            self.storage_controller.skin.raise_()
            self.storage_controller.skin.activateWindow()

    def toggle_battery_widget(self):
        """Alterna a visibilidade do Battery Widget."""
        if self.battery_controller.is_shown():
            self.set_battery_enabled(False)
        else:
            self.set_battery_enabled(True)
            self.battery_controller.skin.raise_()
            self.battery_controller.skin.activateWindow()

    def toggle_volume_mixer(self):
        """Alterna a visibilidade do Volume Mixer."""
        if self.volume_flyout.isVisible():
            self.volume_flyout.hide()
        else:
            self.volume_flyout.show_osd()

    def update_music_hotkey(self, hotkey: str):
        config_manager.set_music_hotkey(hotkey)
        self.hotkey_service.register("music_toggle", hotkey, self.toggle_music_widget)

    def update_timer_hotkey(self, hotkey: str):
        config_manager.set_timer_hotkey(hotkey)
        self.hotkey_service.register("timer_toggle", hotkey, self.toggle_timer_widget)

    def update_weather_hotkey(self, hotkey: str):
        config_manager.set_weather("hotkey", hotkey)
        self.hotkey_service.register("weather_toggle", hotkey, self.toggle_weather_widget)

    def update_performance_hotkey(self, hotkey: str):
        config_manager.set_performance("hotkey", hotkey)
        self.hotkey_service.register("performance_toggle", hotkey, self.toggle_performance_widget)

    def set_storage_hotkey(self, hotkey: str):
        config_manager.set_storage("hotkey", hotkey)
        self.hotkey_service.register("storage_toggle", hotkey, self.toggle_storage_widget)

    def set_battery_hotkey(self, hotkey: str):
        config_manager.set_battery("hotkey", hotkey)
        self.hotkey_service.register("battery_toggle", hotkey, self.toggle_battery_widget)

    def update_volume_hotkey(self, hotkey: str):
        config_manager.set_volume_hotkey(hotkey)
        self.hotkey_service.register("volume_toggle", hotkey, self.toggle_volume_mixer)

    def update_keylock_hotkey(self, hotkey: str):
        config_manager.set_keylock_hotkey(hotkey)
        self.hotkey_service.register("keys_test", hotkey, lambda: self.trigger_test_keylock("Caps Lock", True))

    # --- Controles do Music Widget ---

    def set_music_widget_enabled(self, enabled: bool):
        self._states["music_vinyl"] = enabled
        self.music_controller.set_enabled(enabled)
        self.status_changed.emit("music_vinyl", enabled)

    def is_music_widget_enabled(self) -> bool:
        return self._states.get("music_vinyl", True)

    def set_music_auto_launch(self, enabled: bool):
        config_manager.set_auto_launch_enabled(enabled)
        self.music_controller.on_auto_launch_changed(enabled)

    def set_music_auto_hide(self, enabled: bool):
        config_manager.set_auto_hide_enabled(enabled)
        self.music_controller.on_auto_hide_changed(enabled)

    def set_music_skin(self, skin_name: str):
        if skin_name in self.music_controller.AVAILABLE_SKINS:
            self.music_controller.set_skin(skin_name)

    def _resolve_music_volume_target(self):
        """Sessão do mixer do player exibido pelo widget (app desktop ou navegador); None = sistema."""
        worker = getattr(self.music_controller, "media_worker", None)
        aumid = getattr(worker, "current_source_app_id", "")
        provider = getattr(worker, "_last_provider", "")
        # Com o mixer fechado a lista não é varrida sozinha: pede uma recente (no máx. 2 s; a roda gira em rajadas)
        return find_session_for_player(aumid, provider, self.audio_service.get_fresh_sessions())

    def _on_music_volume_wheel(self, notches: float):
        """
        Roda do mouse no Music Widget: ajusta o volume do player que está tocando
        (app desktop, ou o navegador inteiro) e mostra o mini OSD. Se o player não for
        identificado no mixer, ajusta o volume master do sistema.
        """
        # Acumula frações (touchpads de alta resolução) para um ajuste suave e sem perda
        self._wheel_remainder += notches * MUSIC_WHEEL_VOLUME_STEP
        steps = int(self._wheel_remainder)
        self._wheel_remainder -= steps
        anchor = self.music_controller.skin
        if steps == 0 or anchor is None:
            return

        mixer = self.audio_service
        session = self._resolve_music_volume_target()
        if session is not None:
            current = session.volume
            target = max(0, min(100, current + steps))
            if target != current:
                mixer.set_app_volume(session.app_id, target)
            muted = session.is_muted
        else:
            current = mixer.get_master_volume()
            target = max(0, min(100, current + steps))
            if target != current:
                mixer.set_master_volume(target, from_ui=True)  # from_ui evita o OSD duplicado do mixer
            muted = mixer.get_master_mute()
        self.music_volume_osd.show_for(anchor, target, muted)

    def apply_music_theme(self):
        """
        Aplica o tema da Capa Empilhada escolhido no Hub ao widget vivo. Um tema que não seja o padrão ("cores da
        capa") torna a Capa Empilhada a skin em uso: o tema só existe nela, e escolher um tema sem ver o resultado
        confundiria (ex.: quem recebe um pacote e importa).
        """
        from app.core.theme_loader import DEFAULT_ID
        from app.widgets.music.skins import stack_theme

        stacked = "capa_empilhada"
        if stack_theme.loader.active_id() != DEFAULT_ID and self.music_controller.active_skin_name != stacked:
            if stacked not in config_manager.get_active_widget_skins():
                self.set_music_skin_active(stacked, True)
            self.set_music_skin(stacked)   # a skin nova já nasce com o tema escolhido (e entra com a própria troca)
            swapped = True
        else:
            swapped = False
        skin = self.music_controller.skin
        if skin is not None and hasattr(skin, "reload_skin_theme"):
            if swapped:
                skin.reload_skin_theme()   # skin nova: já entra com a troca própria, um 2º fade por cima seria feio
            else:
                with theme_crossfade(skin):   # a mesma transição do Clima, em todo tema
                    skin.reload_skin_theme()

    def apply_timer_theme(self):
        """Aplica o tema do Timer escolhido no Hub ao widget vivo."""
        skin = self.timer_controller.skin
        if skin is not None and hasattr(skin, "reload_skin_theme"):
            with theme_crossfade(skin):
                skin.reload_skin_theme()

    def apply_weather_theme(self):
        """Aplica o tema da skin Nothing Dot do Clima ao widget vivo (e ativa a skin se necessário)."""
        from app.core.theme_loader import DEFAULT_ID
        from app.widgets.weather import font_skins, theme as weather_theme

        if weather_theme.loader.active_id() != DEFAULT_ID and not font_skins.is_nothing_skin(
            self.weather_controller.active_skin_name
        ):
            self.set_weather_skin(font_skins.NOTHING_DOT_SKIN)
        else:
            self.weather_controller.skin.begin_skin_crossfade()
            self.weather_controller.skin.update()

    def apply_performance_theme(self):
        """Aplica o tema da skin Nothing Dot do Desempenho ao widget vivo (e ativa a skin se necessário)."""
        from app.core.theme_loader import DEFAULT_ID
        from app.widgets.performance import theme as perf_theme
        from app.widgets.performance.card_state import SKIN_NOTHING_DOT

        if perf_theme.loader.active_id() != DEFAULT_ID and self.performance_controller.active_skin_name != SKIN_NOTHING_DOT:
            self.set_performance_skin(SKIN_NOTHING_DOT)
        else:
            self.performance_controller.skin.begin_skin_crossfade()
            self.performance_controller.skin.update()

    def theme_appliers(self) -> dict:
        """O que fazer em cada destino depois de escolher/importar um tema: flyouts aparecem para teste,
        widgets aplicam ao vivo."""
        return {
            "keylock": lambda: self.trigger_test_keylock("Caps Lock", True),
            "mixer": self.trigger_test_volume,
            "music": self.apply_music_theme,
            "timer": self.apply_timer_theme,
            "weather": self.apply_weather_theme,
            "performance": self.apply_performance_theme,
        }

    def set_music_skin_active(self, skin_name: str, active: bool) -> bool:
        """Ativa/desativa uma skin no menu de troca rápida. Retorna False se violar o mínimo de 1."""
        if not config_manager.set_skin_active(skin_name, active):
            return False
        self.music_controller.ensure_active_skin_valid()
        self.active_skins_changed.emit(config_manager.get_active_widget_skins())
        return True

    def set_music_scale(self, scale: Optional[float]):
        """Ajusta o fator de escala proporcional do widget de música."""
        self.music_controller.set_scale(scale)

    def apply_music_scale_live(self, scale: float):
        """Aplica a escala enquanto o controle é arrastado, sem gravar (a gravação vem ao soltar)."""
        self.music_controller.apply_scale_live(scale)

    def move_music_to_screen_position(self, pos_key: str):
        """
        Posiciona a janela de música em um dos quadrantes de tela:
        tl, tc, tr, bl, bc, br
        """
        if not self.music_controller.skin:
            return

        app = QApplication.instance()
        if not app or not app.primaryScreen():
            return

        screen_geo = app.primaryScreen().availableGeometry()
        w, h = self.music_controller.skin._card_size()   # o CARTÃO encosta na margem da tela, não a janela
        margin = 24

        x, y = self._calc_coords(screen_geo, w, h, pos_key, margin)
        self.music_controller.settle()
        self._leave_anchor_group(self.music_controller.skin)
        self.music_controller.skin.glide_card_to(x, y)   # na tela, o cartão desliza até o lugar escolhido
        config_manager.set_music_position_remembered(True, x, y)

    # --- Âncora de cada flyout de sistema (Caps/Num Lock e Mixer; na mesma âncora eles se empilham) ---

    def get_osd_anchor(self, flyout: str) -> str:
        return config_manager.get_osd_anchor(flyout)

    def set_osd_anchor(self, flyout: str, anchor: str):
        """Salva e aplica na hora a posição de um flyout ('keylock' ou 'mixer')."""
        config_manager.set_osd_anchor(flyout, anchor)
        self.osd_stack.set_anchors(config_manager.get_osd_anchor("keylock"), config_manager.get_osd_anchor("mixer"))
        self.osd_anchor_changed.emit(flyout, config_manager.get_osd_anchor(flyout))

    # --- Controles de Lock Keys OSD ---

    def set_keylock_enabled(self, enabled: bool):
        self._states["keys_osd"] = enabled
        try:
            if enabled:
                self.keylock_service.keylock_changed.connect(self._on_keylock_changed)
            else:
                self.keylock_service.keylock_changed.disconnect(self._on_keylock_changed)
        except Exception:
            pass
        if enabled:
            self.keylock_service.start()
        else:
            self.keylock_service.stop()
        self.status_changed.emit("keys_osd", enabled)

    def _on_keylock_changed(self, key_name: str, is_on: bool):
        """Mostra o indicador só se aquela tecla estiver ligada nas opções do Hub (Caps Lock / Num Lock)."""
        if config_manager.is_keylock_key_enabled(key_name):
            self.keylock_flyout.show_osd(key_name, is_on)

    def is_keylock_enabled(self) -> bool:
        return self._states.get("keys_osd", True)

    def trigger_test_keylock(self, key_name: str = "Caps Lock", is_on: bool = True):
        """Simula a exibição imediata do OSD na tela para testes visuais."""
        self.keylock_flyout.show_osd(key_name, is_on)

    # --- Controles de Volume Mixer ---

    def set_volume_mixer_enabled(self, enabled: bool):
        self._states["vol_mixer"] = enabled
        try:
            if enabled:
                self.audio_service.osd_requested.connect(self.volume_flyout.show_osd)
            else:
                self.audio_service.osd_requested.disconnect(self.volume_flyout.show_osd)
        except Exception:
            pass
        # Desligado: não engole mais as teclas de volume, então o OSD nativo do Windows volta a aparecer
        self.audio_service.set_intercept_volume_keys(enabled)
        self.status_changed.emit("vol_mixer", enabled)

    def is_volume_mixer_enabled(self) -> bool:
        return self._states.get("vol_mixer", True)

    def trigger_test_volume(self):
        """Abre o Flyout de volume na tela para teste visual."""
        self.volume_flyout.show_osd()

    # --- Controles do Timer Widget ---

    def set_timer_enabled(self, enabled: bool):
        self._states["timer"] = enabled
        config_manager.set_timer_enabled(enabled)
        if enabled:
            self.timer_controller.show()
        else:
            self.timer_controller.hide()
        self.status_changed.emit("timer", enabled)

    def is_timer_enabled(self) -> bool:
        return self._states.get("timer", True)

    def set_timer_skin(self, skin_name: str):
        if skin_name in self.timer_controller.available_skins():
            self.timer_controller.set_skin(skin_name)

    def _on_timer_status_changed(self, is_active: bool):
        self._states["timer"] = is_active
        self.status_changed.emit("timer", is_active)

    def move_timer_to_screen_position(self, pos_key: str):
        """Posiciona a janela do timer em um dos quadrantes de tela."""
        if not self.timer_controller.skin:
            return

        app = QApplication.instance()
        if not app or not app.primaryScreen():
            return

        screen_geo = app.primaryScreen().availableGeometry()
        w = h = self.timer_controller.skin.square_side()   # o quadrado encosta na margem da tela
        margin = 24

        x, y = self._calc_coords(screen_geo, w, h, pos_key, margin)
        self._leave_anchor_group(self.timer_controller.skin)
        self.timer_controller.skin.glide_square_to(x, y)   # na tela, o quadrado desliza até o lugar escolhido
        config_manager.set_timer_position_remembered(True, x, y)

    # --- Controles do Weather Widget ---

    def set_weather_enabled(self, enabled: bool):
        self._states["weather"] = enabled
        config_manager.set_weather("enabled", enabled)
        if enabled:
            self.weather_controller.show()
        else:
            self.weather_controller.hide()
        self.status_changed.emit("weather", enabled)

    def is_weather_enabled(self) -> bool:
        return self._states.get("weather", False)

    def set_weather_skin(self, skin_id: str):
        if skin_id in self.weather_controller.available_skins():
            self.weather_controller.set_skin(skin_id)

    def _on_weather_status_changed(self, is_active: bool):
        self._states["weather"] = is_active
        self.status_changed.emit("weather", is_active)

    def move_weather_to_screen_position(self, pos_key: str):
        """Posiciona o cartão de clima num dos quadrantes da tela."""
        app = QApplication.instance()
        if not app or not app.primaryScreen():
            return
        w, h = self.weather_controller.skin.card_size()
        x, y = self._calc_coords(app.primaryScreen().availableGeometry(), w, h, pos_key, 24)
        self.weather_controller.settle()
        self._leave_anchor_group(self.weather_controller.skin)
        self.weather_controller.skin.glide_card_to(x, y)
        config_manager.set_weather("remember_position", True)
        config_manager.set_weather("position", [x, y])
        self.weather_controller.remember_position_changed.emit(True)

    # --- Controles do Performance Widget ---

    def set_performance_enabled(self, enabled: bool):
        self._states["performance"] = enabled
        config_manager.set_performance("enabled", enabled)
        if enabled:
            self.performance_controller.show()
        else:
            self.performance_controller.hide()
        self.status_changed.emit("performance", enabled)

    def set_performance_skin(self, skin_id: str):
        self.performance_controller.set_skin(skin_id)

    def is_performance_enabled(self) -> bool:
        return self._states.get("performance", False)

    def _on_performance_status_changed(self, is_active: bool):
        self._states["performance"] = is_active
        self.status_changed.emit("performance", is_active)

    def move_performance_to_screen_position(self, pos_key: str):
        """Posiciona o cartão de desempenho num dos quadrantes da tela."""
        app = QApplication.instance()
        if not app or not app.primaryScreen():
            return
        w, h = self.performance_controller.skin.card_size()
        x, y = self._calc_coords(app.primaryScreen().availableGeometry(), w, h, pos_key, 24)
        self.performance_controller.settle()
        self._leave_anchor_group(self.performance_controller.skin)
        self.performance_controller.skin.glide_card_to(x, y)
        config_manager.set_performance("remember_position", True)
        config_manager.set_performance("position", [x, y])
        self.performance_controller.remember_position_changed.emit(True)

    # --- Controles do Storage Widget ---

    def set_storage_enabled(self, enabled: bool):
        self._states["storage"] = enabled
        config_manager.set_storage("enabled", enabled)
        if enabled:
            self.storage_controller.show()
        else:
            self.storage_controller.hide()
        self.status_changed.emit("storage", enabled)

    def is_storage_enabled(self) -> bool:
        return self._states.get("storage", False)

    def _on_storage_status_changed(self, is_active: bool):
        self._states["storage"] = is_active
        self.status_changed.emit("storage", is_active)

    def move_storage_to_screen_position(self, pos_key: str):
        """Posiciona o cartão de armazenamento num dos quadrantes da tela."""
        app = QApplication.instance()
        if not app or not app.primaryScreen():
            return
        w, h = self.storage_controller.skin.card_size()
        x, y = self._calc_coords(app.primaryScreen().availableGeometry(), w, h, pos_key, 24)
        self.storage_controller.settle()
        self._leave_anchor_group(self.storage_controller.skin)
        self.storage_controller.skin.glide_card_to(x, y)
        config_manager.set_storage("remember_position", True)
        config_manager.set_storage("position", [x, y])
        self.storage_controller.remember_position_changed.emit(True)

    # --- Controles do Battery Widget ---

    def set_battery_enabled(self, enabled: bool):
        self._states["battery"] = enabled
        config_manager.set_battery("enabled", enabled)
        if enabled:
            self.battery_controller.show()
        else:
            self.battery_controller.hide()
        self.status_changed.emit("battery", enabled)

    def is_battery_enabled(self) -> bool:
        return self._states.get("battery", False)

    def _on_battery_status_changed(self, is_active: bool):
        self._states["battery"] = is_active
        self.status_changed.emit("battery", is_active)

    def move_battery_to_screen_position(self, pos_key: str):
        """Posiciona o cartão de baterias num dos quadrantes da tela."""
        app = QApplication.instance()
        if not app or not app.primaryScreen():
            return
        w, h = self.battery_controller.skin.card_size()
        x, y = self._calc_coords(app.primaryScreen().availableGeometry(), w, h, pos_key, 24)
        self.battery_controller.settle()
        self._leave_anchor_group(self.battery_controller.skin)
        self.battery_controller.skin.glide_card_to(x, y)
        config_manager.set_battery("remember_position", True)
        config_manager.set_battery("position", [x, y])
        self.battery_controller.remember_position_changed.emit(True)

    def on_theme_changed(self, theme=None):
        """Notifica os widgets sobre alterações de tema global.

        Troca de MODO (claro/escuro): os widgets que seguem o app dissolvem junto com o Hub (300 ms, curva in-out,
        ver `mode_crossfade`). Só a cor de destaque mudando não anima: o arraste do seletor chama isto ~33x/s."""
        from app.core.theme_crossfade import MODE_DURATION_MS, mode_crossfade
        timer_skin = self.timer_controller.skin if getattr(self, "timer_controller", None) else None
        old = getattr(timer_skin, "_hub_theme", None)   # a aparência com que os widgets vinham pintando
        mode_changed = theme is not None and old is not None and old.mode != theme.mode

        def _fade_card(card):
            if mode_changed:
                card.begin_skin_crossfade(MODE_DURATION_MS, mode_switch=True)

        if timer_skin is not None:
            if timer_skin.isVisible() and mode_changed:
                with mode_crossfade(timer_skin):
                    self.timer_controller.update_theme(theme)
            else:
                self.timer_controller.update_theme(theme)
        if hasattr(self, "performance_controller") and self.performance_controller:
            from app.core.theme_loader import APP_ID
            from app.widgets.performance import theme as perf_theme
            from app.widgets.performance.card_state import SKIN_NOTHING_DOT
            if (self.performance_controller.active_skin_name == SKIN_NOTHING_DOT
                    and perf_theme.loader.active_id() == APP_ID):   # só o tema "Aimedget" muda com o app
                _fade_card(self.performance_controller.skin)   # foto ANTES de esquecer a aparência antiga
                perf_theme.invalidate_live_hub_theme()
                self.performance_controller.skin.update()
            else:
                perf_theme.invalidate_live_hub_theme()
        if hasattr(self, "storage_controller") and self.storage_controller:
            from app.widgets.storage.storage_card import invalidate_card_theme as invalidate_storage_theme
            _fade_card(self.storage_controller.skin)
            invalidate_storage_theme()
            self.storage_controller.skin.update()
        if hasattr(self, "battery_controller") and self.battery_controller:
            from app.widgets.battery.battery_card import invalidate_card_theme
            _fade_card(self.battery_controller.skin)
            invalidate_card_theme()
            self.battery_controller.skin.update()

    def cleanup_all(self):
        """Desinstala hooks e encerra recursos em background de forma segura."""
        if hasattr(self, "hotkey_service") and self.hotkey_service:
            self.hotkey_service.cleanup()
        if hasattr(self, "performance_controller") and self.performance_controller:
            self.performance_controller.stop()
        if hasattr(self, "storage_controller") and self.storage_controller:
            self.storage_controller.stop()
        if hasattr(self, "battery_controller") and self.battery_controller:
            self.battery_controller.stop()
        worker = getattr(getattr(self, "music_controller", None), "media_worker", None)
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass

    # --- Helper de Posicionamento Geométrico ---

    @staticmethod
    def _leave_anchor_group(skin):
        """
        Escolher um quadrante no Hub dá ao widget um lugar próprio: ele sai do grupo de ancoragem (os outros ficam
        juntos; se ele estava no meio, o vão fecha deslizando). Sem isso o deslize o levava sozinho, mas o próximo arraste puxava o grupo inteiro.
        """
        mgr = anchor_manager()
        if mgr.is_grouped(skin):
            mgr.detach(skin)

    def _calc_coords(self, screen_geo: QRect, w: int, h: int, pos_key: str, margin: int) -> tuple[int, int]:
        sx = screen_geo.x()
        sy = screen_geo.y()
        sw = screen_geo.width()
        sh = screen_geo.height()

        if pos_key == "tl":
            return (sx + margin, sy + margin)
        elif pos_key == "tc":
            return (sx + (sw - w) // 2, sy + margin)
        elif pos_key == "tr":
            return (sx + sw - w - margin, sy + margin)
        elif pos_key == "bl":
            return (sx + margin, sy + sh - h - margin)
        elif pos_key == "bc":
            return (sx + (sw - w) // 2, sy + sh - h - margin)
        else:  # 'br'
            return (sx + sw - w - margin, sy + sh - h - margin)


# Instância singleton global do bridge
service_bridge: Optional[HubServiceBridge] = None


def get_service_bridge() -> HubServiceBridge:
    global service_bridge
    if service_bridge is None:
        service_bridge = HubServiceBridge()
    return service_bridge
