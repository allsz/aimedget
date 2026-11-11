"""
HubServiceBridge - Ponte central de comunicação entre o Aimedget Hub e os serviços de background.
Gerencia instâncias únicas de MusicController, KeyLockService/Flyout e AudioMixerService/Flyout.
"""

from typing import Optional
from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtWidgets import QApplication

from app.core.config_manager import config_manager
from app.core.osd_anchor import link_flyouts
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

        # 5. Serviço Global de Atalhos (Hotkeys)
        self.hotkey_service = get_hotkey_service()
        self._init_hotkeys()

        # Estados de ativação
        self._states = {
            "music_vinyl": config_manager.is_music_enabled(),
            "keys_osd": True,
            "vol_mixer": True,
            "timer": config_manager.is_timer_show_on_startup(),
        }

    def start_all(self):
        """Inicializa os widgets no desktop de acordo com as preferências salvas."""
        # Se o widget de música estiver ativado, exibe ou inicia modo auto
        if self._states.get("music_vinyl", True):
            self.music_controller.start()

        # O timer só aparece ao iniciar se o usuário optou; caso contrário, fica
        # disponível pelo atalho global (Win+Alt+T)
        if config_manager.is_timer_show_on_startup():
            self.timer_controller.start()

    # --- Atalhos Globais e Ações de Toggle ---

    def _init_hotkeys(self):
        # Music Player (padrão Win+Alt+M)
        music_hk = config_manager.get_music_hotkey("Win+Alt+M")
        self.hotkey_service.register("music_toggle", music_hk, self.toggle_music_widget)

        # Timer Widget (padrão Win+Alt+T)
        timer_hk = config_manager.get_timer_hotkey("Win+Alt+T")
        self.hotkey_service.register("timer_toggle", timer_hk, self.toggle_timer_widget)

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
        if self.timer_controller.skin and self.timer_controller.skin.isVisible():
            self.set_timer_enabled(False)
        else:
            self.set_timer_enabled(True)
            if self.timer_controller.skin:
                self.timer_controller.skin.show()
                self.timer_controller.skin.raise_()
                self.timer_controller.skin.activateWindow()

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
            self.set_music_skin(stacked)   # a skin nova já nasce com o tema escolhido
        skin = self.music_controller.skin
        if skin is not None and hasattr(skin, "reload_skin_theme"):
            skin.reload_skin_theme()

    def apply_timer_theme(self):
        """Aplica o tema do Timer escolhido no Hub ao widget vivo."""
        skin = self.timer_controller.skin
        if skin is not None and hasattr(skin, "reload_skin_theme"):
            skin.reload_skin_theme()

    def theme_appliers(self) -> dict:
        """O que fazer em cada destino depois de escolher/importar um tema: flyouts aparecem para teste,
        widgets aplicam ao vivo."""
        return {
            "keylock": lambda: self.trigger_test_keylock("Caps Lock", True),
            "mixer": self.trigger_test_volume,
            "music": self.apply_music_theme,
            "timer": self.apply_timer_theme,
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
        self.music_controller.skin.move_card_to(x, y)
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
        if skin_name in self.timer_controller.AVAILABLE_SKINS:
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
        self.timer_controller.skin.move_square_to(x, y)
        config_manager.set_timer_position_remembered(True, x, y)

    def on_theme_changed(self, theme=None):
        """Notifica os widgets sobre alterações de tema global."""
        if hasattr(self, "timer_controller") and self.timer_controller:
            self.timer_controller.update_theme(theme)

    def cleanup_all(self):
        """Desinstala hooks e encerra recursos em background de forma segura."""
        if hasattr(self, "hotkey_service") and self.hotkey_service:
            self.hotkey_service.cleanup()
        worker = getattr(getattr(self, "music_controller", None), "media_worker", None)
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass

    # --- Helper de Posicionamento Geométrico ---

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
