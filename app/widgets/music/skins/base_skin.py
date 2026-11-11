import time
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal
from PySide6.QtGui import QImage, QPixmap, QAction, QIcon, QPainter, QPen, QColor, QBrush
from PySide6.QtWidgets import QWidget, QMenu
from app.core.typography import init_app_font
from app.core.config_manager import config_manager
from app.core.widget_animator import SlideFadeAnimator
from app.core.i18n import t
from app.services.repeat_modes import next_repeat_mode
from app.core.colorimetry import (
    ThemePalette,
    get_default_palette,
    extract_palette_from_image,
)
from app.ui_components.fluent_menu import FluentMusicMenu


class BaseMusicSkin(QWidget):
    """
    Classe base para qualquer Skin do Music Widget.
    Fornece:
    - Configuração de janela flutuante transparente sem bordas
    - Sinal unificado `command_requested(action, value)` para enviar comandos ao MediaWorker
    - Sinal `skin_switch_requested(skin_name)` e menu de contexto (clique direito) para alternar skins
    - Sinal `scale_changed(scale)` para ajustes dinâmicos de proporção de resolução
    - Estado comum de faixa (título, artista, duração, tempo atual, capa do álbum e paleta adaptativa)
    """
    command_requested = Signal(str, object)
    skin_switch_requested = Signal(str)
    manage_skins_requested = Signal()
    volume_wheel_requested = Signal(float)  # entalhes da roda (+ = sobe, fracionário em touchpads)

    # Ordem canônica das skins no menu: (id, chave i18n do título)
    SKIN_MENU_ENTRIES = (
        ("vinyl", "skin_vinyl_title"),
        ("fullcover", "skin_fullcover_title"),
        ("ripple", "skin_ripple_title"),
        ("capa_empilhada", "skin_stacked_title"),
    )

    @staticmethod
    def canonical_skin_id(skin_id: str) -> str:
        """Normaliza aliases legados da Capa Empilhada para o id canônico."""
        return "capa_empilhada" if skin_id in ("stacked", "capaEmpilhada") else skin_id
    scale_changed = Signal(float)

    MIN_SAFE_SCALE: float = 0.35  # ~70% do baseline 0.50 (tamanho seguro e legível)
    MAX_SAFE_SCALE: float = 0.80  # ~160% do baseline 0.50 (proporção segura sem estourar limites)
    CARD_RADIUS: float = 44.0

    def __init__(self, base_width: int, base_height: int, scale: float | None = None):
        super().__init__()
        init_app_font()
        self.canvas_w = base_width
        self.canvas_h = base_height
        self.scale = scale if scale is not None else config_manager.get_effective_music_scale()
        # Margem transparente (px, nos 4 lados) em volta do cartão: só skins com tema de figurinhas que passam da borda
        self.art_margin = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(*self._window_size())
        self.setMouseTracking(True)
        self.animator = SlideFadeAnimator(self)

        # Estado base da mídia
        self.title_text = "Nenhuma mídia ativa"
        self.artist_text = "O que vamos ouvir hoje?"
        self.duration = 222.0
        self.current_time = 0.0
        self.is_playing = False
        self.album_pixmap = None
        self._last_thumb_bytes = b""
        self.provider = "generic"

        # Interações de mouse e redimensionamento proporcional fluido
        self._drag_pos = QPoint()
        self._is_resizing = False
        self._resize_start_pos = QPoint()
        self._resize_start_scale = self.scale
        self._hovered = False
        self._resize_hovered = False

        # Estado de Colorimetria Dinâmica (Passo 4)
        self.current_palette: ThemePalette = get_default_palette()
        self.target_palette: ThemePalette = get_default_palette()

    def _update_and_cache_cover(self, thumb_bytes: bytes) -> bool:
        """
        Atualiza o QPixmap da capa e extrai automaticamente a nova paleta de cores dominante.
        Retém a capa anterior durante trocas rápidas de faixa para evitar piscadas.
        """
        if thumb_bytes and thumb_bytes != self._last_thumb_bytes:
            self._last_thumb_bytes = thumb_bytes
            img = QImage.fromData(thumb_bytes)
            if not img.isNull():
                self.album_pixmap = QPixmap.fromImage(img)
                self.target_palette = extract_palette_from_image(img)
                return True
        elif not thumb_bytes and self.title_text == "Nenhuma mídia ativa":
            if self._last_thumb_bytes:
                self._last_thumb_bytes = b""
                self.album_pixmap = None
                self.target_palette = get_default_palette()
                return True
        return False

    def apply_preview_media(self, media):
        """
        Põe a mídia de demonstração (`preview_media.PreviewMedia`) nesta skin para a miniatura do Hub: a capa entra
        como se o player a tivesse enviado, e a paleta do fundo sai do `backdrop` (sem o logo). Serve para qualquer
        skin nova; só uma skin com estado próprio de capa/paleta precisa sobrescrever.
        """
        self._update_and_cache_cover(media.cover_bytes)
        self.target_palette = extract_palette_from_image(media.backdrop)
        self.current_palette = self.target_palette

    def on_media_updated(
        self,
        title: str,
        artist: str,
        is_playing: bool,
        pos: float,
        dur: float,
        thumb_bytes: bytes,
        provider: str = "generic",
    ):
        """Implementado pelas subclasses para reagir à atualização do WindowsMediaWorker."""
        raise NotImplementedError

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        s = max(0, int(seconds))
        return f"{s // 60}:{s % 60:02d}"

    @staticmethod
    def _build_minimal_skin_icon(kind: str, is_dark: bool = True) -> QIcon:
        """Gera ícones vetoriais minimalistas adaptáveis ao tema ativo para o menu de contexto."""
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Cor base adaptativa para modo Claro e Escuro
        c = QColor(255, 255, 255, 230) if is_dark else QColor(31, 30, 29, 230)
        c_sub = QColor(255, 255, 255, 120) if is_dark else QColor(31, 30, 29, 120)
        c_sub2 = QColor(255, 255, 255, 155) if is_dark else QColor(31, 30, 29, 155)
        c_sub3 = QColor(255, 255, 255, 95) if is_dark else QColor(31, 30, 29, 95)
        stacked_bg = QColor(255, 255, 255, 25) if is_dark else QColor(31, 30, 29, 20)

        if kind == "vinyl":
            p.setPen(QPen(c, 2.0))
            p.drawEllipse(QPointF(16, 16), 11, 11)
            p.setPen(QPen(c_sub, 1.4))
            p.drawEllipse(QPointF(16, 16), 6.5, 6.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(16, 16), 2.2, 2.2)
        elif kind == "fullcover":
            p.setPen(QPen(c, 2.0))
            p.drawRoundedRect(QRectF(4, 6, 24, 20), 5, 5)
            p.setPen(QPen(c_sub, 1.6))
            p.drawLine(8, 21, 24, 21)
        elif kind == "ripple":
            # Semiótica minimalista de ondas concêntricas com opacidade progressiva
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(16, 16), 2.2, 2.2)
            base_rgb = (255, 255, 255) if is_dark else (31, 30, 29)
            for r, alpha, w in ((5.2, 220, 1.8), (8.6, 155, 1.5), (12.0, 95, 1.3)):
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(base_rgb[0], base_rgb[1], base_rgb[2], alpha), w))
                p.drawEllipse(QPointF(16, 16), r, r)
        elif kind == "stacked":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(c_sub3, 1.5))
            p.drawRoundedRect(QRectF(12, 8, 15, 16), 3.5, 3.5)
            p.setPen(QPen(c_sub2, 1.7))
            p.drawRoundedRect(QRectF(8, 7, 16, 18), 4.0, 4.0)
            p.setPen(QPen(c, 1.9))
            p.setBrush(stacked_bg)
            p.drawRoundedRect(QRectF(4, 6, 16, 19), 4.0, 4.0)
        elif kind == "pin":
            # Ícone minimalista de pin / fixar posição favorita na tela
            p.setPen(QPen(c, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(16, 11), 5.5, 5.5)
            p.setPen(QPen(c, 2.0))
            p.drawLine(16, 16.5, 16, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(16, 11), 2.2, 2.2)
        elif kind == "skins":
            # Grade 2x2 de quadrados arredondados: coleção de aparências
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(c, 1.9))
            p.drawRoundedRect(QRectF(5, 5, 9.5, 9.5), 2.5, 2.5)
            p.drawRoundedRect(QRectF(17.5, 5, 9.5, 9.5), 2.5, 2.5)
            p.drawRoundedRect(QRectF(5, 17.5, 9.5, 9.5), 2.5, 2.5)
            p.setPen(QPen(c_sub, 1.6))
            p.drawRoundedRect(QRectF(17.5, 17.5, 9.5, 9.5), 2.5, 2.5)
        elif kind == "scale":
            # Ícone minimalista de escala/redimensionamento proporcional
            p.setPen(QPen(c, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(5, 5, 22, 22), 4, 4)
            p.setPen(QPen(c_sub, 1.4))
            p.drawRoundedRect(QRectF(11, 11, 10, 10), 2, 2)

        p.end()
        return QIcon(pm)

    # --- Cartão x janela (margem transparente para arte que passa da borda) ---

    def _card_size(self) -> tuple[int, int]:
        """Tamanho do CARTÃO em px de tela."""
        return int(round(self.canvas_w * self.scale)), int(round(self.canvas_h * self.scale))

    def _window_size(self) -> tuple[int, int]:
        """Tamanho da JANELA: o cartão mais a margem transparente (0 quando o tema não tem arte para fora)."""
        w, h = self._card_size()
        return w + 2 * self.art_margin, h + 2 * self.art_margin

    def card_rect(self) -> QRectF:
        """O cartão em coordenadas da janela."""
        w, h = self._card_size()
        return QRectF(self.art_margin, self.art_margin, w, h)

    def card_origin(self) -> QPoint:
        """Canto superior esquerdo do cartão na tela, sem o deslocamento da animação de surgir/sumir."""
        return self.rest_pos() + QPoint(self.art_margin, self.art_margin)

    def move_card_to(self, x: int, y: int):
        """Põe o CARTÃO em (x, y): as posições salvas e trocas de skin/tema falam do cartão, não da janela."""
        self.move(x - self.art_margin, y - self.art_margin)

    def _wanted_art_margin(self) -> int:
        """Margem que o tema atual pede nesta escala. Skins com tema de figurinhas sobrescrevem."""
        return 0

    def _apply_art_margin(self):
        """
        Confere a margem que o tema pede e, se mudou, redimensiona a janela mantendo o cartão exatamente onde está.
        Devolve True se a janela mudou.
        """
        wanted = self._wanted_art_margin()
        if wanted == self.art_margin:
            return False
        delta = wanted - self.art_margin
        origin = self.pos()
        self.art_margin = wanted
        self.setFixedSize(*self._window_size())
        self.move(origin.x() - delta, origin.y() - delta)   # o cartão fica onde estava
        self._update_hitboxes()
        self.update()
        return True

    def set_scale(self, new_scale: float, save_preference: bool = True):
        """Aplica novo fator de escala ao widget e reposiciona os elementos."""
        new_scale = max(self.MIN_SAFE_SCALE, min(self.MAX_SAFE_SCALE, round(float(new_scale), 4)))
        if abs(self.scale - new_scale) < 0.001:
            return
        self.scale = new_scale
        old_margin = self.art_margin
        self.art_margin = self._wanted_art_margin()
        self.setFixedSize(*self._window_size())
        if self.art_margin != old_margin:   # a margem acompanha a escala: o canto do cartão não pode andar
            self.move(self.x() - (self.art_margin - old_margin), self.y() - (self.art_margin - old_margin))
        self._update_hitboxes()
        if save_preference:
            config_manager.set_music_scale(new_scale)
        self.scale_changed.emit(new_scale)
        self.update()

    def set_scale_auto(self):
        """Restaura a escala para o modo de detecção automática proporcional à tela."""
        config_manager.set_music_scale(None)
        auto_s = config_manager.get_effective_music_scale()
        self.set_scale(auto_s, save_preference=False)

    def get_resize_grip_margin(self) -> float:
        """
        Retorna o recuo seguro da alça em relação ao canto inferior direito da janela,
        calculado proporcionalmente ao raio de curvatura do card para evitar que os pontos
        vazem para fora da borda arredondada.
        """
        corner_r_canvas = getattr(self, "CARD_RADIUS", 44.0)
        corner_r_screen = corner_r_canvas * self.scale
        # Posiciona os pontos confortavelmente dentro da curva circular (recuo de ~54% do raio)
        return max(13.0, corner_r_screen * 0.54)

    def get_resize_grip_rect(self) -> QRectF:
        """Retorna a área de clique interativa para redimensionamento no canto inferior direito."""
        margin = self.get_resize_grip_margin()
        grip_size = max(28.0, margin + 10.0)
        card = self.card_rect()
        return QRectF(card.right() - grip_size, card.bottom() - grip_size, grip_size, grip_size)

    def is_in_resize_grip(self, pos: QPointF | QPoint) -> bool:
        """Verifica se a posição do ponteiro está sobre a área da alça."""
        return self.get_resize_grip_rect().contains(pos)

    def get_resize_grip_color(self) -> QColor:
        """
        Retorna a cor base do grip com contraste inteligente conforme o fundo do card.
        - Em fundos claros (ex: Capa Empilhada / temas pastéis ou capas claras):
          Usa tom escuro refinado (grafite / slate) para manter contraste e legibilidade.
        - Em fundos escuros (ex: Vinil, FullCover, Ripple escuro):
          Usa branco suave.
        """
        if hasattr(self, "pastel_theme") and self.pastel_theme:
            card_bg = getattr(self.pastel_theme, "card_bg", None)
            if card_bg:
                lum = (0.299 * card_bg.red() + 0.587 * card_bg.green() + 0.114 * card_bg.blue()) / 255.0
                if lum > 0.55:
                    return QColor(36, 36, 40)
        elif hasattr(self, "current_palette") and self.current_palette:
            stop0 = getattr(self.current_palette, "stop0", None)
            if stop0:
                lum = (0.299 * stop0.red() + 0.587 * stop0.green() + 0.114 * stop0.blue()) / 255.0
                if lum > 0.60:
                    return QColor(36, 36, 40)
        return QColor(255, 255, 255)

    def paint_resize_grip(self, painter: QPainter):
        """
        Desenha o indicador de redimensionamento no canto inferior direito,
        no estilo clássico de 3 pontos diagonais alinhado com o Timer Widget.
        Oculto quando não em hover ou não em redimensionamento ativo.
        """
        if not self._hovered and not self._is_resizing:
            return

        painter.save()
        painter.resetTransform()

        base_col = self.get_resize_grip_color()
        alpha = 240 if self._resize_hovered else 145
        base_col.setAlpha(alpha)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(base_col))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        margin = self.get_resize_grip_margin()
        card = self.card_rect()
        grip_x = card.right() - margin
        grip_y = card.bottom() - margin
        r = 1.4
        spacing = 4.2

        # 3 pequenos pontos diagonais idênticos aos do Timer
        painter.drawEllipse(QPointF(grip_x, grip_y), r, r)
        painter.drawEllipse(QPointF(grip_x - spacing, grip_y), r, r)
        painter.drawEllipse(QPointF(grip_x, grip_y - spacing), r, r)

        painter.restore()

    def handle_resize_press(self, event) -> bool:
        """Inicia redimensionamento se o clique do mouse for na alça inferior direita."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_in_resize_grip(event.position()):
                self._is_resizing = True
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_scale = self.scale
                return True
        return False

    def handle_resize_move(self, event) -> bool:
        """Atualiza a escala de forma suave e proporcional ao mover o mouse durante resize."""
        if self._is_resizing and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            delta_scale = (delta.x() / self.canvas_w + delta.y() / self.canvas_h) / 2.0
            new_scale = max(self.MIN_SAFE_SCALE, min(self.MAX_SAFE_SCALE, self._resize_start_scale + delta_scale))
            self.set_scale(new_scale, save_preference=False)
            return True
        return False

    def handle_resize_hover(self, pos: QPointF | QPoint) -> bool:
        """Atualiza o cursor e o estado de hover da alça de redimensionamento."""
        in_grip = self.is_in_resize_grip(pos)
        if in_grip:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            if not self._resize_hovered:
                self._resize_hovered = True
                self.update()
            return True
        else:
            if self._resize_hovered:
                self._resize_hovered = False
                self.update()
            return False

    def handle_resize_release(self, event) -> bool:
        """Finaliza o redimensionamento e persiste a escala customizada."""
        if event.button() == Qt.MouseButton.LeftButton and self._is_resizing:
            self._is_resizing = False
            config_manager.set_music_scale(round(self.scale, 4))
            self.scale_changed.emit(self.scale)
            self.update()
            return True
        return False

    def showEvent(self, event):
        """Liga o loop de animação (~60 FPS) só enquanto o widget está visível."""
        timer = getattr(self, "timer", None)
        if timer is not None and not timer.isActive():
            if hasattr(self, "last_tick"):
                self.last_tick = time.perf_counter()  # evita um dt grande no primeiro frame
            timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        """Pausa o loop de animação enquanto oculto: zero wakeups de CPU em segundo plano."""
        timer = getattr(self, "timer", None)
        if timer is not None:
            timer.stop()
        super().hideEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._resize_hovered = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def _update_hitboxes(self):
        """Hook sobrescrito pelas subclasses para atualizar retângulos de colisão."""
        pass

    def _get_skin_effects_title(self) -> str:
        """Título do submenu de efeitos da skin (ex: 'Efeitos da Capa' ou 'Efeitos da Skin')."""
        return "Efeitos da Skin"

    def _get_skin_effects_icon(self, is_dark: bool = True) -> QIcon | None:
        """Ícone minimalista para o submenu de efeitos."""
        return None

    def _populate_skin_effects_menu(self, menu: QMenu, is_dark: bool = True) -> bool:
        """
        Adiciona os efeitos específicos desta skin ao submenu.
        Retorna True se foram adicionadas opções (o submenu será exibido no menu de contexto).
        Retorna False se esta skin não possui efeitos extras (o submenu não será exibido).
        """
        return False

    def _populate_extra_context_menu(self, menu: QMenu, is_dark: bool = True):
        """Hook opcional para skins adicionarem itens diretamente ao menu de contexto."""
        pass

    def wheelEvent(self, event):
        """Rolar sobre qualquer parte do widget ajusta o volume (a lógica fica no bridge)."""
        dy = event.angleDelta().y()
        if dy and config_manager.is_music_wheel_volume_enabled():
            self.volume_wheel_requested.emit(dy / 120.0)
            event.accept()
        else:
            super().wheelEvent(event)

    def contextMenuEvent(self, event):
        menu = FluentMusicMenu(self)
        is_dark = menu._theme.is_dark

        # Submenu "Skins": apenas as skins ativas no Hub, com check na skin em uso
        skins_menu = FluentMusicMenu(t("menu_skins"), menu)
        skins_icon = self._build_minimal_skin_icon("skins", is_dark)
        if not skins_icon.isNull():
            skins_menu.setIcon(skins_icon)

        active_ids = set(config_manager.get_active_widget_skins())
        curr_skin = self.canonical_skin_id(config_manager.get_active_skin("vinyl"))
        for skin_id, title_key in self.SKIN_MENU_ENTRIES:
            if skin_id not in active_ids:
                continue
            act = QAction(t(title_key), self)
            skins_menu.set_trailing_check(act, skin_id == curr_skin)
            act.triggered.connect(lambda chk=False, sid=skin_id: self.skin_switch_requested.emit(sid))
            skins_menu.addAction(act)

        skins_menu.addSeparator()
        act_manage = QAction(t("menu_manage_skins"), self)
        act_manage.triggered.connect(self.manage_skins_requested.emit)
        skins_menu.addAction(act_manage)
        menu.addMenu(skins_menu)

        # Submenu minimalista com seta indicadora para efeitos da skin ativa
        effects_menu = FluentMusicMenu(self._get_skin_effects_title(), menu)
        eff_icon = self._get_skin_effects_icon(is_dark)
        if eff_icon is not None and not eff_icon.isNull():
            effects_menu.setIcon(eff_icon)

        has_effects = self._populate_skin_effects_menu(effects_menu, is_dark)
        if has_effects and len(effects_menu.actions()) > 0:
            menu.addMenu(effects_menu)

        self._populate_extra_context_menu(menu, is_dark)

        # Submenu minimalista de redimensionamento e escala
        from app.core.screen_metrics import MUSIC_SCALE_PRESETS
        scale_menu = FluentMusicMenu("Tamanho", menu)
        scale_icon = self._build_minimal_skin_icon("scale", is_dark)
        if not scale_icon.isNull():
            scale_menu.setIcon(scale_icon)

        is_auto = config_manager.is_music_scale_auto()
        curr_scale = self.scale

        for s_val, s_label in MUSIC_SCALE_PRESETS:
            act_s = QAction(s_label, self)
            is_active = (not is_auto) and abs(curr_scale - s_val) < 0.005
            scale_menu.set_trailing_check(act_s, is_active)
            act_s.triggered.connect(lambda chk=False, s=s_val: self.set_scale(s, save_preference=True))
            scale_menu.addAction(act_s)

        scale_menu.addSeparator()
        act_auto = QAction("Automático (Adaptar à tela)", self)
        scale_menu.set_trailing_check(act_auto, is_auto)
        act_auto.triggered.connect(self.set_scale_auto)
        scale_menu.addAction(act_auto)

        menu.addMenu(scale_menu)

        # Opção de fixar / lembrar posição favorita na tela com check (certo) à direita
        menu.addSeparator()
        is_remembered = config_manager.is_music_position_remembered()
        act_remember_pos = QAction(self._build_minimal_skin_icon("pin", is_dark), "Lembrar posição", self)
        menu.set_trailing_check(act_remember_pos, is_remembered)
        act_remember_pos.triggered.connect(lambda: self._toggle_remember_position(not is_remembered))
        menu.addAction(act_remember_pos)

        menu.exec(event.globalPos())

    # --- Repetição ---

    REPEAT_SYNC_GRACE_S = 1.5   # após um clique, ignora leituras antigas do player

    def next_repeat_mode(self) -> int:
        """Próximo modo ao clicar em repetir, na ordem do player atual (Spotify difere dos demais)."""
        import time

        self._repeat_clicked_at = time.monotonic()
        return next_repeat_mode(getattr(self, "provider", "generic"), getattr(self, "repeat_mode", 0))

    def on_repeat_state(self, mode: int):
        """Sincroniza o ícone com o modo de repetição real do player (-1 = player não informa)."""
        import time

        if mode < 0 or not hasattr(self, "repeat_mode"):
            return
        if time.monotonic() - getattr(self, "_repeat_clicked_at", 0.0) < self.REPEAT_SYNC_GRACE_S:
            return  # o clique acabou de acontecer: o player ainda pode reportar o valor anterior
        if mode != self.repeat_mode:
            self.repeat_mode = mode
            self.update()

    def rest_pos(self) -> QPoint:
        """Posição real da janela, sem o deslocamento da animação de surgir/sumir."""
        return self.animator.rest_pos()

    def _toggle_remember_position(self, checked: bool):
        """Salva a posição atual do cartão como favorita ou remove a preferência se desmarcado."""
        if checked:
            origin = self.card_origin()
            config_manager.set_music_position_remembered(True, origin.x(), origin.y())
        else:
            config_manager.set_music_position_remembered(False)

    def _on_window_drag_finished(self):
        """Atualiza a posição memorizada e ajusta escala automática se trocou de tela."""
        if config_manager.is_music_position_remembered():
            origin = self.card_origin()
            config_manager.save_music_position(origin.x(), origin.y())
        if config_manager.is_music_scale_auto():
            from app.core.screen_metrics import get_auto_music_scale
            target_scale = get_auto_music_scale(widget=self)
            if abs(self.scale - target_scale) >= 0.02:
                self.set_scale(target_scale, save_preference=False)
