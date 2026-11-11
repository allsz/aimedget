from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtWidgets import QApplication
from app.core.config_manager import config_manager
from app.services.media_worker import WindowsMediaWorker
from app.widgets.music.auto_open_guard import AutoOpenDismissal
from app.widgets.music.skins.vinyl_skin import VinylMusicSkin
from app.widgets.music.skins.fullcover_skin import FullCoverSkin
from app.widgets.music.skins.ripple_skin import RippleSkin
from app.widgets.music.skins.capa_empilhada_skin import CapaEmpilhadaSkin


class MusicWidgetController(QObject):
    """
    Controlador do Music Widget:
    - Instancia o `WindowsMediaWorker` (único serviço em background).
    - Gerencia a skin ativa (`VinylMusicSkin`, `FullCoverSkin`, `RippleSkin` ou `CapaEmpilhadaSkin`) preservando estado de mídia e posição na tela.
    - Conecta os sinais de mídia, comandos e troca de skin.
    - Suporta memorização da posição favorita na tela persistida via ConfigManager.
    """
    skin_changed = Signal(str)
    scale_changed = Signal(object)

    # Tempos da animação de surgir/sumir (ms). O timeout é mais lento: ninguém pediu, então
    # o widget se retira sem chamar atenção. Pelo atalho/Hub a resposta é seca.
    APPEAR_MS = 200
    HIDE_MS = 160
    SOFT_HIDE_MS = 320
    manage_skins_requested = Signal()
    volume_wheel_requested = Signal(float)
    AVAILABLE_SKINS = {
        "vinyl": VinylMusicSkin,
        "fullcover": FullCoverSkin,
        "ripple": RippleSkin,
        "capa_empilhada": CapaEmpilhadaSkin,
        "capaEmpilhada": CapaEmpilhadaSkin,
    }

    def __init__(self, skin_name: str | None = None, media_worker: WindowsMediaWorker | None = None):
        super().__init__()
        self.media_worker = media_worker or WindowsMediaWorker()
        self.skin = None
        self.is_enabled = config_manager.is_music_enabled()
        # Controla se o widget foi aberto pelo usuário intencionalmente
        # e se alguma música já foi reproduzida nesta sessão de exibição
        self._manually_opened = False
        self._has_played_since_shown = False
        # Dispensa da abertura automática (usuário escondeu o widget com música em andamento)
        self._dismissal = AutoOpenDismissal()
        self._media_has_session = False
        self._media_playing = False
        saved_skin = config_manager.get_active_skin("vinyl")
        initial_skin = skin_name or saved_skin
        if initial_skin not in self.AVAILABLE_SKINS:
            initial_skin = "vinyl"
        initial_skin = self._resolve_active_skin(initial_skin)
        self.active_skin_name = initial_skin
        self.set_skin(initial_skin)

        # Timer de auto-hide com histerese (4 segundos de música pausada)
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.setInterval(4000)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide_timeout)

        # Monitora ciclo de vida de reprodução para suporte ao Launch Automático por detecção
        self.media_worker.media_updated.connect(self._handle_auto_launch_lifecycle)

    def _resolve_active_skin(self, skin_name: str) -> str:
        """Retorna a skin informada se estiver ativa no Hub; senão, a primeira skin ativa."""
        canon = CapaEmpilhadaSkin.canonical_skin_id(skin_name)
        active = config_manager.get_active_widget_skins()
        if canon in active:
            return skin_name
        for skin_id, _ in CapaEmpilhadaSkin.SKIN_MENU_ENTRIES:
            if skin_id in active and skin_id in self.AVAILABLE_SKINS:
                return skin_id
        return skin_name

    def ensure_active_skin_valid(self):
        """Fallback: se a skin em uso foi desativada no Hub, aplica a primeira skin ativa."""
        target = self._resolve_active_skin(self.active_skin_name)
        if target != self.active_skin_name:
            self.set_skin(target)

    def set_skin(self, skin_name: str):
        skin_cls = self.AVAILABLE_SKINS.get(skin_name, FullCoverSkin)
        self.active_skin_name = skin_name
        config_manager.set_active_skin(skin_name)
        old_pos = None
        was_visible = False
        last_state = None

        if self.skin is not None:
            old_pos = self.skin.card_origin()   # posição do CARTÃO: a skin nova pode ter margem diferente
            was_visible = self._is_shown()
            last_state = (
                self.skin.title_text,
                self.skin.artist_text,
                self.skin.is_playing,
                self.skin.current_time,
                self.skin.duration,
                self.skin._last_thumb_bytes,
                self.skin.provider,
            )
            try:
                self.media_worker.media_updated.disconnect(self.skin.on_media_updated)
                self.skin.command_requested.disconnect(self.media_worker.send_command)
                self.skin.skin_switch_requested.disconnect(self.set_skin)
                self.skin.manage_skins_requested.disconnect(self.manage_skins_requested.emit)
                self.skin.volume_wheel_requested.disconnect(self.volume_wheel_requested.emit)
                repeat_signal = getattr(self.media_worker, "repeat_state_changed", None)
                if repeat_signal is not None:
                    repeat_signal.disconnect(self.skin.on_repeat_state)
                self.skin.scale_changed.disconnect(self._on_skin_scale_changed)
            except Exception:
                pass
            self.skin.close()
            self.skin.deleteLater()

        self.skin = skin_cls()
        self.media_worker.media_updated.connect(self.skin.on_media_updated)
        self.skin.command_requested.connect(self.media_worker.send_command)
        self.skin.skin_switch_requested.connect(self.set_skin)
        self.skin.manage_skins_requested.connect(self.manage_skins_requested.emit)
        self.skin.volume_wheel_requested.connect(self.volume_wheel_requested.emit)
        repeat_signal = getattr(self.media_worker, "repeat_state_changed", None)
        if repeat_signal is not None:
            repeat_signal.connect(self.skin.on_repeat_state)
            self.skin.on_repeat_state(getattr(self.media_worker, "_last_repeat_ui", -1))
        self.skin.scale_changed.connect(self._on_skin_scale_changed)

        if last_state is not None:
            self.skin.on_media_updated(*last_state)

        if old_pos is not None:
            self.skin.move_card_to(old_pos.x(), old_pos.y())
            if config_manager.is_music_position_remembered():
                config_manager.save_music_position(old_pos.x(), old_pos.y())
        else:
            self.restore_or_center_position()

        if was_visible:
            self.skin.show()

        self.skin_changed.emit(skin_name)

    def _on_skin_scale_changed(self, scale: float):
        self.scale_changed.emit(scale)

    def set_scale(self, scale: float | None):
        """Atualiza a escala da skin ativa e persiste a preferência."""
        config_manager.set_music_scale(scale)
        if self.skin:
            effective = config_manager.get_effective_music_scale(screen=self.skin.screen() if hasattr(self.skin, "screen") else None)
            self.skin.set_scale(effective, save_preference=False)
        self.scale_changed.emit(scale)

    def restore_or_center_position(self):
        """Restaura a posição favorita salva pelo usuário ou centraliza na tela primária."""
        if not self.skin:
            return
        self.settle()
        if config_manager.is_music_position_remembered():
            pos = config_manager.get_music_saved_position()
            card_w, card_h = self.skin._card_size()
            if pos is not None and self._is_position_on_screen(pos[0], pos[1], card_w, card_h):
                self.skin.move_card_to(pos[0], pos[1])
                return
        self.center_on_screen()

    def _is_position_on_screen(self, x: int, y: int, w: int, h: int) -> bool:
        """Verifica se uma porção substancial do widget estará visível em monitores ativos."""
        app = QApplication.instance()
        if not app:
            return True
        widget_rect = QRect(x, y, max(1, w), max(1, h))
        for screen in app.screens():
            inter = screen.geometry().intersected(widget_rect)
            if inter.width() >= min(w, 60) and inter.height() >= min(h, 60):
                return True
        return False

    def center_on_screen(self):
        app = QApplication.instance()
        if app and app.primaryScreen() and self.skin:
            self.settle()
            # Coordenadas virtuais: com o monitor primário fora da origem (ex.: à direita de outro), x/y não são 0
            screen = app.primaryScreen().geometry()
            card_w, card_h = self.skin._card_size()
            x = screen.x() + (screen.width() - card_w) // 2
            y = screen.y() + (screen.height() - card_h) // 2
            self.skin.move_card_to(x, y)

    def set_enabled(self, enabled: bool):
        """Ativa ou desativa o módulo do Music Widget pelo Hub."""
        self.is_enabled = enabled
        self._dismissal.clear()
        config_manager.set_music_enabled(enabled)
        if not enabled:
            self._auto_hide_timer.stop()
            self.hide()
        else:
            if config_manager.is_auto_launch_enabled():
                last_is_playing = getattr(self.media_worker, "_last_is_playing", False)
                last_title = getattr(self.media_worker, "_last_title", "")
                if last_is_playing and last_title and last_title != "Nenhuma mídia ativa":
                    self.restore_or_center_position()
                    self.show()
            else:
                self.restore_or_center_position()
                self.show()

    def start(self):
        """
        Ponto de entrada do ciclo de vida:
        - Se widget estiver desativado: permanece recolhido.
        - Se launch_mode == 'auto': permanece em standby até que reprodução ativa seja detectada.
        - Se launch_mode == 'manual': abre o widget imediatamente na tela.
        """
        if not self.is_enabled:
            return

        if config_manager.is_auto_launch_enabled():
            # Standby: só abre se já houver música tocando ativamente no momento da inicialização
            last_is_playing = getattr(self.media_worker, "_last_is_playing", False)
            last_title = getattr(self.media_worker, "_last_title", "")
            if last_is_playing and last_title and last_title != "Nenhuma mídia ativa":
                self.show()
        else:
            self.show()

    def _handle_auto_launch_lifecycle(
        self,
        title: str,
        artist: str,
        is_playing: bool,
        pos: float,
        dur: float,
        thumb_bytes: bytes,
        provider: str = "generic",
    ):
        """Gerencia exibição/ocultação dinâmica baseada em auto_launch e auto_hide."""
        has_media = bool(title) and title != "Nenhuma mídia ativa"
        self._media_has_session = has_media
        self._media_playing = bool(is_playing and has_media)
        self._dismissal.observe(has_media, self._media_playing, self._current_source())

        if not self.is_enabled:
            return

        auto_launch = config_manager.is_auto_launch_enabled()
        auto_hide = config_manager.is_auto_hide_enabled()

        has_active_music = is_playing and title != "Nenhuma mídia ativa"
        if has_active_music:
            self._auto_hide_timer.stop()
            self._has_played_since_shown = True
            # Se uma música tocou, a abertura manual cumpriu seu papel de espera
            self._manually_opened = False

            if auto_launch and self.skin and not self._is_shown() and not self._dismissal.active:
                if not self.is_hiding():
                    self.restore_or_center_position()
                self.show()
        else:
            # Ausência de reprodução ativa (música pausada ou nenhuma mídia)
            # Se foi aberto manualmente e nenhuma música tocou ainda, respeita a intenção do usuário e NÃO fecha!
            if self._manually_opened and not self._has_played_since_shown:
                self._auto_hide_timer.stop()
                return

            if auto_hide:
                if title == "Nenhuma mídia ativa":
                    self._auto_hide_timer.stop()
                    # Só oculta se o widget já estava aberto após ter tocado alguma música
                    if self._has_played_since_shown and self._is_shown():
                        self.hide(soft=True)
                elif not is_playing and self._is_shown():
                    # Pausado após reprodução: inicia contagem regressiva de tolerância de 4s
                    if self._has_played_since_shown and not self._auto_hide_timer.isActive():
                        self._auto_hide_timer.start()
            else:
                self._auto_hide_timer.stop()

    def _on_auto_hide_timeout(self):
        if config_manager.is_auto_hide_enabled() and self._is_shown():
            if not self._manually_opened or self._has_played_since_shown:
                self.hide(soft=True)

    def on_auto_hide_changed(self, enabled: bool):
        """Reage imediatamente à alteração da preferência de auto-hide no Hub."""
        if not self.is_enabled:
            return
        if enabled:
            # Se foi aberto manualmente sem música, continua aberto
            if self._manually_opened and not self._has_played_since_shown:
                return

            last_is_playing = getattr(self.media_worker, "_last_is_playing", False)
            last_title = getattr(self.media_worker, "_last_title", "")
            if (not last_is_playing or last_title == "Nenhuma mídia ativa") and self._is_shown():
                if self._has_played_since_shown and not self._auto_hide_timer.isActive():
                    self._auto_hide_timer.start()
        else:
            self._auto_hide_timer.stop()

    def on_auto_launch_changed(self, enabled: bool):
        """Reage imediatamente à alteração da preferência de abertura automática no Hub."""
        self._dismissal.clear()
        if not self.is_enabled:
            return
        if enabled:
            last_is_playing = getattr(self.media_worker, "_last_is_playing", False)
            last_title = getattr(self.media_worker, "_last_title", "")
            has_active = last_is_playing and last_title and (last_title != "Nenhuma mídia ativa")
            if not has_active and self._is_shown():
                # Só fecha se não foi aberto intencionalmente pelo usuário
                if not (self._manually_opened and not self._has_played_since_shown):
                    self._auto_hide_timer.stop()
                    self.hide()
        else:
            self._auto_hide_timer.stop()
            if self.skin and not self._is_shown():
                if not self.is_hiding():
                    self.restore_or_center_position()
                self.show()

    # --- Visibilidade animada ---

    def _is_shown(self) -> bool:
        """Visível e não em retirada (durante o fade-out o widget ainda está na tela)."""
        return bool(self.skin and self.skin.isVisible() and not self.skin.animator.is_hiding())

    def is_shown(self) -> bool:
        return self._is_shown()

    def is_hiding(self) -> bool:
        return bool(self.skin and self.skin.animator.is_hiding())

    def settle(self):
        """Conclui qualquer animação em curso antes de mover/trocar o widget."""
        if self.skin:
            self.skin.animator.settle()

    def show(self, is_manual: bool = False):
        if is_manual:
            self._manually_opened = True
            self._has_played_since_shown = False
            self._auto_hide_timer.stop()
            self._dismissal.clear()  # o manual sempre vence
        if self.skin:
            self.skin.animator.show(self.APPEAR_MS)

    def _current_source(self) -> str:
        """Identificador do app/player de origem da mídia atual."""
        worker = self.media_worker
        return getattr(worker, "current_source_app_id", "") or getattr(worker, "_last_provider", "") or ""

    def hide(self, soft: bool = False, by_user: bool = False):
        """
        Oculta com animação. `soft=True` (timeout sem música) usa a saída mais lenta.
        `by_user=True` (atalho): se há uma sessão de escuta, a abertura automática fica suspensa
        até ela terminar, para o widget não reaparecer porque "a música está tocando".
        """
        if by_user and self._media_has_session:
            self._dismissal.dismiss(self._current_source(), self._media_playing)
        self._auto_hide_timer.stop()
        self._manually_opened = False
        self._has_played_since_shown = False
        if self.skin:
            self.skin.animator.hide(self.SOFT_HIDE_MS if soft else self.HIDE_MS)
