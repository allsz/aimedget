import math
import time
from typing import Callable
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen

from app.core.i18n import t
from app.core.typography import get_ui_font
from app.services.audio_endpoint_service import AudioEndpoint
from app.ui_components.fluent_slider import FluentSlider
from app.widgets.volume_mixer.theme import DEFAULT_THEME, MixerTheme
from app.ui_components.pill_switch import PillSwitch


class AppVolumeRow:
    """
    Linha de aplicativo no Mixer de Volume (Windows 11 Fluent) com gaveta de roteamento inline:
    - Linha principal (altura 34.5px): Ícone (mute no clique esquerdo, expande roteamento no clique direito),
      FluentSlider horizontal e percentual numérico.
    - Gaveta inline expansível (Opção B):
      - Animação de transição suave e rápida (cubic-out em ~0.18s a 144 Hz).
      - Cabeçalho exibindo apenas o nome do aplicativo e botão de fechar (✕).
      - Abas compactas em pílula para alternar entre "Saída" e "Entrada".
      - Lista de dispositivos reais com botões PillSwitch animados em modo rádio.
    """

    ICON_SIZE = 16
    ROW_PITCH = 34.5
    MAIN_ROW_CY = 17.25

    EXPAND_DURATION_S = 0.18
    ITEM_H = 28.0

    def __init__(
        self,
        app_id: str,
        name: str,
        volume: int,
        is_muted: bool,
        icon: QImage,
        on_routing_changed: Callable[[str, str, str], None] | None = None,
    ):
        self.app_id = app_id
        self.name = name
        self.volume = volume
        self.is_muted = is_muted
        self.icon_hovered = False
        self.on_routing_changed = on_routing_changed

        self.slider = FluentSlider()
        self.slider.value = volume
        self.slider.is_muted = is_muted
        self.theme: MixerTheme = DEFAULT_THEME

        self._scaled_icon = self._prepare_icon(icon)

        # Estado da gaveta de roteamento inline (Opção B)
        self.is_routing_open = False
        self._expand_t = 0.0          # 0.0 = recolhido, 1.0 = expandido
        self._expand_start_t = 0.0
        self._expand_target_t = 0.0
        self._expand_anim_start = 0.0

        # Altura interna da gaveta e animação suave ao trocar abas de dispositivos
        self._current_drawer_h: float = 120.0
        self._target_drawer_h: float = 120.0

        # Aba ativa: "output" (Saída) ou "input" (Entrada)
        self.active_flow = "output"

        # Dispositivos disponíveis e chaves seletoras PillSwitch
        self.output_endpoints: list[AudioEndpoint] = []
        self.input_endpoints: list[AudioEndpoint] = []
        self.selected_output_id = "__default__"
        self.selected_input_id = "__default__"

        self._output_switches: dict[str, PillSwitch] = {}
        self._input_switches: dict[str, PillSwitch] = {}

        # Armazena coordenadas do último render para hit testing preciso
        self.last_x0 = 0.0
        self.last_y_top = 0.0

        # Estados de hover da gaveta
        self._close_hovered = False
        self._tab_out_hovered = False
        self._tab_in_hovered = False
        self._hovered_dev_id: str | None = None
        self._tab_switch_t = 1.0

    @classmethod
    def _prepare_icon(cls, icon: QImage) -> QImage:
        if icon.isNull():
            return icon
        target_px = cls.ICON_SIZE * 2  # Supersampling 2x para nitidez máxima
        return icon.scaled(
            target_px,
            target_px,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def sync_from_session(self, volume: int, is_muted: bool, icon: QImage):
        if not self.slider.is_dragging:
            self.volume = volume
            self.slider.value = volume
        self.is_muted = is_muted
        self.slider.is_muted = is_muted
        if self._scaled_icon.isNull() and not icon.isNull():
            self._scaled_icon = self._prepare_icon(icon)

    def set_endpoints(
        self,
        outputs: list[AudioEndpoint],
        inputs: list[AudioEndpoint],
        selected_out: str,
        selected_in: str,
    ):
        self.output_endpoints = outputs
        self.input_endpoints = inputs
        self.selected_output_id = selected_out
        self.selected_input_id = selected_in

        # Atualiza/instancia os switches de saída
        for ep in outputs:
            if ep.device_id not in self._output_switches:
                self._output_switches[ep.device_id] = PillSwitch(
                    is_checked=(ep.device_id == selected_out)
                )
                self._output_switches[ep.device_id].accent = QColor(self.theme.switch_on)
            else:
                self._output_switches[ep.device_id].set_checked(ep.device_id == selected_out)

        # Atualiza/instancia os switches de entrada
        for ep in inputs:
            if ep.device_id not in self._input_switches:
                self._input_switches[ep.device_id] = PillSwitch(
                    is_checked=(ep.device_id == selected_in)
                )
                self._input_switches[ep.device_id].accent = QColor(self.theme.switch_on)
            else:
                self._input_switches[ep.device_id].set_checked(ep.device_id == selected_in)

        # Atualiza a altura alvo da gaveta
        self._target_drawer_h = self._calc_drawer_height(self.active_flow)
        if not self.is_routing_open:
            self._current_drawer_h = self._target_drawer_h

    def _calc_drawer_height(self, flow: str) -> float:
        """Calcula a altura interna da gaveta com base no número de dispositivos da aba ativa."""
        endpoints = self.output_endpoints if flow == "output" else self.input_endpoints
        dev_count = max(1, len(endpoints))
        # Header (26px) + Tabs com respiro (34px) + Itens (dev_count * 28px) + Padding inferior (8px)
        return float(26.0 + 34.0 + dev_count * self.ITEM_H + 8.0)

    def _target_drawer_height(self) -> float:
        return self._calc_drawer_height(self.active_flow)

    def toggle_routing(self):
        """Alterna a abertura da gaveta inline com animação rápida e fluida."""
        self.is_routing_open = not self.is_routing_open
        self._expand_start_t = self._expand_t
        self._expand_target_t = 1.0 if self.is_routing_open else 0.0
        self._expand_anim_start = time.perf_counter()
        self._target_drawer_h = self._calc_drawer_height(self.active_flow)
        if self.is_routing_open and self._expand_t <= 0.01:
            self._current_drawer_h = self._target_drawer_h

    def close_routing(self):
        if self.is_routing_open:
            self.toggle_routing()

    def reset_routing(self):
        """Fecha a gaveta de roteamento imediatamente sem animação residual."""
        self.is_routing_open = False
        self._expand_t = 0.0
        self._expand_start_t = 0.0
        self._expand_target_t = 0.0
        self._hovered_dev_id = None
        self._close_hovered = False
        self._tab_switch_t = 1.0
        self._target_drawer_h = self._calc_drawer_height(self.active_flow)
        self._current_drawer_h = self._target_drawer_h

    def get_total_height(self) -> float:
        """Retorna a altura total dinâmica da linha (incluindo o progresso de expansão da gaveta)."""
        if self._expand_t <= 0.001:
            return float(self.ROW_PITCH)
        return float(self.ROW_PITCH + self._current_drawer_h * self._expand_t)

    def get_target_height(self) -> float:
        """Retorna a altura alvo que a linha terá ao terminar a animação."""
        if not self.is_routing_open:
            return float(self.ROW_PITCH)
        return float(self.ROW_PITCH + self._calc_drawer_height(self.active_flow))

    def step_animation(self, dt: float) -> bool:
        """Avança as animações da gaveta, dos sliders e dos switches a 144 Hz."""
        animating = False

        # 1. Animação de expansão/recolhimento da gaveta inline (cubic-out em 0.18s)
        diff = self._expand_target_t - self._expand_t
        if abs(diff) > 0.003:
            raw = min(1.0, max(0.0, (time.perf_counter() - self._expand_anim_start) / self.EXPAND_DURATION_S))
            eased = 1.0 - (1.0 - raw) ** 3
            self._expand_t = self._expand_start_t + (self._expand_target_t - self._expand_start_t) * eased
            animating = True
        else:
            self._expand_t = self._expand_target_t

        # 2. Animação suave e rápida da altura da gaveta (fluida a 144 Hz)
        if self.is_routing_open:
            diff_h = self._target_drawer_h - self._current_drawer_h
            if abs(diff_h) > 0.2:
                h_alpha = 1.0 - math.exp(-34.0 * dt)
                self._current_drawer_h += diff_h * h_alpha
                animating = True
            else:
                self._current_drawer_h = self._target_drawer_h

        # 3. Transição suave de opacidade ao alternar abas de saída e entrada (cross-fade rápido em 110ms)
        if self._tab_switch_t < 1.0:
            self._tab_switch_t = min(1.0, self._tab_switch_t + dt / 0.11)
            animating = True

        # 4. Animação do slider do app
        if self.slider.step_animation(dt):
            animating = True

        # 5. Animação de todos os pill switches
        switches = (
            self._output_switches.values()
            if self.active_flow == "output"
            else self._input_switches.values()
        )
        for sw in switches:
            if sw.step_animation(dt):
                animating = True

        return animating

    # =========================================================================
    # HIT TESTING & EVENTOS DE MOUSE
    # =========================================================================
    def icon_hit_rect(self, x0: float, cy: float) -> QRectF:
        return QRectF(x0 + 13.0, cy - 11.0, 22.0, 22.0)

    def _close_btn_rect(self, x0: float, y_top: float) -> QRectF:
        drawer_y = y_top + self.ROW_PITCH + 1.0
        return QRectF(x0 + 204.0, drawer_y + 4.0, 20.0, 20.0)

    def _tab_rect(self, x0: float, y_top: float, flow: str) -> QRectF:
        drawer_y = y_top + self.ROW_PITCH + 1.0
        tabs_y = drawer_y + 27.0
        if flow == "output":
            return QRectF(x0 + 19.0, tabs_y + 2.0, 100.0, 22.0)
        return QRectF(x0 + 121.0, tabs_y + 2.0, 100.0, 22.0)

    def _item_rect(self, x0: float, y_top: float, index: int) -> QRectF:
        drawer_y = y_top + self.ROW_PITCH + 1.0
        items_y0 = drawer_y + 61.0
        return QRectF(x0 + 17.0, items_y0 + index * self.ITEM_H, 206.0, 26.0)

    def handle_mouse_press(
        self,
        pt: QPointF,
        button: Qt.MouseButton,
        x0: float | None = None,
        y_top: float | None = None,
    ) -> bool:
        """Processa cliques na linha e na gaveta inline."""
        if x0 is not None:
            self.last_x0 = x0
        if y_top is not None:
            self.last_y_top = y_top

        x0 = self.last_x0
        y_top = self.last_y_top
        cy = y_top + self.MAIN_ROW_CY

        # 1. Clique no ícone do aplicativo
        if self.icon_hit_rect(x0, cy).contains(pt):
            if button == Qt.MouseButton.RightButton:
                # Botão DIREITO no ícone: abre/fecha a gaveta inline de roteamento (Opção B)
                self.toggle_routing()
                return True
            # Botão ESQUERDO no ícone é tratado pelo mixer_flyout para silenciar (mute)
            return False

        # 2. Interações dentro da gaveta inline aberta
        if self.is_routing_open and self._expand_t > 0.4:
            # Botão de fechar (✕)
            if self._close_btn_rect(x0, y_top).contains(pt):
                self.close_routing()
                return True

            # Abas Saída / Entrada
            if self._tab_rect(x0, y_top, "output").contains(pt):
                if self.active_flow != "output":
                    self.active_flow = "output"
                    self._target_drawer_h = self._calc_drawer_height("output")
                    self._tab_switch_t = 0.0
                return True

            if self._tab_rect(x0, y_top, "input").contains(pt):
                if self.active_flow != "input":
                    self.active_flow = "input"
                    self._target_drawer_h = self._calc_drawer_height("input")
                    self._tab_switch_t = 0.0
                return True

            # Lista de dispositivos da aba ativa
            endpoints = self.output_endpoints if self.active_flow == "output" else self.input_endpoints
            switches = self._output_switches if self.active_flow == "output" else self._input_switches

            for idx, ep in enumerate(endpoints):
                if self._item_rect(x0, y_top, idx).contains(pt):
                    # Seleciona o dispositivo em modo rádio com animação fluida
                    if self.active_flow == "output":
                        self.selected_output_id = ep.device_id
                    else:
                        self.selected_input_id = ep.device_id

                    # Atualiza os switches com animação de deslizamento
                    for dev_id, sw in switches.items():
                        sw.set_checked(dev_id == ep.device_id, animated=True)

                    if self.on_routing_changed:
                        self.on_routing_changed(self.app_id, self.active_flow, ep.device_id)
                    return True

        return False

    def handle_mouse_move(
        self,
        pt: QPointF,
        x0: float | None = None,
        y_top: float | None = None,
    ) -> bool:
        """Atualiza estados de hover para feedback visual refinado."""
        if x0 is not None:
            self.last_x0 = x0
        if y_top is not None:
            self.last_y_top = y_top

        x0 = self.last_x0
        y_top = self.last_y_top
        cy = y_top + self.MAIN_ROW_CY

        changed = False
        ic_hov = self.icon_hit_rect(x0, cy).contains(pt)
        if ic_hov != self.icon_hovered:
            self.icon_hovered = ic_hov
            changed = True

        if self.is_routing_open and self._expand_t > 0.4:
            cl_hov = self._close_btn_rect(x0, y_top).contains(pt)
            t_out_hov = self._tab_rect(x0, y_top, "output").contains(pt)
            t_in_hov = self._tab_rect(x0, y_top, "input").contains(pt)

            if cl_hov != self._close_hovered:
                self._close_hovered = cl_hov
                changed = True
            if t_out_hov != self._tab_out_hovered:
                self._tab_out_hovered = t_out_hov
                changed = True
            if t_in_hov != self._tab_in_hovered:
                self._tab_in_hovered = t_in_hov
                changed = True

            endpoints = self.output_endpoints if self.active_flow == "output" else self.input_endpoints
            switches = self._output_switches if self.active_flow == "output" else self._input_switches
            hov_id = None
            for idx, ep in enumerate(endpoints):
                item_r = self._item_rect(x0, y_top, idx)
                if item_r.contains(pt):
                    hov_id = ep.device_id
                sw = switches.get(ep.device_id)
                if sw:
                    sw_hov = sw.contains(pt)
                    if sw_hov != sw.is_hovered:
                        sw.is_hovered = sw_hov
                        changed = True

            if hov_id != self._hovered_dev_id:
                self._hovered_dev_id = hov_id
                changed = True

        return changed

    # =========================================================================
    # RENDERIZAÇÃO 1:1 FLUENT DESIGN
    # =========================================================================
    def draw(self, p: QPainter, x0: float, y_top: float):
        self.last_x0 = x0
        self.last_y_top = y_top
        cy = y_top + self.MAIN_ROW_CY

        # ---------------------------------------------------------------------
        # 1. LINHA PRINCIPAL DO APLICATIVO
        # ---------------------------------------------------------------------
        icon_rect = QRectF(
            x0 + 24.0 - self.ICON_SIZE * 0.5,
            cy - self.ICON_SIZE * 0.5,
            float(self.ICON_SIZE),
            float(self.ICON_SIZE),
        )

        # Efeito de hover ou gaveta aberta no ícone
        if self.icon_hovered or self.is_routing_open:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._accent_with_alpha(45) if self.is_routing_open else QColor(255, 255, 255, 22))
            p.drawRoundedRect(icon_rect.adjusted(-4.0, -4.0, 4.0, 4.0), 4.0, 4.0)

        # Desenha ícone nativo
        if not self._scaled_icon.isNull():
            prev_op = p.opacity()
            if self.is_muted:
                p.setOpacity(prev_op * 0.42)
            p.drawImage(icon_rect, self._scaled_icon)
            p.setOpacity(prev_op)

        # Traço vermelho de mudo
        if self.is_muted:
            mute_pen = QPen(QColor(255, 95, 95), 1.5)
            mute_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(mute_pen)
            p.drawLine(
                QPointF(icon_rect.left() + 1.0, icon_rect.top() + 1.0),
                QPointF(icon_rect.right() - 1.0, icon_rect.bottom() - 1.0),
            )

        # Slider horizontal do app (x_rel = 45..186)
        self.slider.set_geometry(x0 + 45.0, x0 + 186.0, cy)
        self.slider.draw(p)

        # Valor numérico do volume do app (x_rel = 198..226)
        p.setFont(get_ui_font(12, QFont.Weight.Normal))
        p.setPen(self.theme.muted_text if self.is_muted else self.theme.text)
        num_rect = QRectF(x0 + 198.0, cy - 10.0, 28.0, 20.0)
        p.drawText(
            num_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            str(self.slider.value),
        )

        # ---------------------------------------------------------------------
        # 2. GAVETA INLINE DE ROTEAMENTO (OPÇÃO B - ACCORDION)
        # ---------------------------------------------------------------------
        if self._expand_t > 0.01:
            self._draw_inline_drawer(p, x0, y_top)

    def apply_theme(self, theme: MixerTheme):
        """Aplica os tokens do tema a esta linha (cores do slider, números e destaques)."""
        self.theme = theme
        self.slider.apply_colors(theme.accent, theme.thumb, theme.thumb_outer, theme.thumb_border, theme.track_inactive)
        for sw in (*self._output_switches.values(), *self._input_switches.values()):
            sw.accent = QColor(theme.switch_on)

    def _accent_with_alpha(self, alpha: int) -> QColor:
        c = QColor(self.theme.accent)
        c.setAlpha(alpha)
        return c

    def _draw_inline_drawer(self, p: QPainter, x0: float, y_top: float):
        current_drawer_h = self._current_drawer_h * self._expand_t

        drawer_x = x0 + 10.0
        drawer_y = y_top + self.ROW_PITCH + 1.0
        drawer_w = 220.0

        p.save()
        # Recorte suave para o conteúdo não vazar enquanto a gaveta anima sua altura
        clip_rect = QRectF(drawer_x, drawer_y, drawer_w, current_drawer_h)
        p.setClipRect(clip_rect, Qt.ClipOperation.IntersectClip)
        p.setOpacity(min(1.0, self._expand_t * 1.25))

        # Fundo da gaveta (#242424 com borda fina #363636) acompanhando a altura dinâmica
        bg_rect = QRectF(drawer_x, drawer_y, drawer_w, self._current_drawer_h)
        p.setPen(QPen(self.theme.drawer_border, 1.0))
        p.setBrush(self.theme.drawer_bg)
        p.drawRoundedRect(bg_rect, 6.0, 6.0)

        # A) Cabeçalho: Nome do Aplicativo formatado (sem a palavra ROTEAMENTO)
        p.setFont(get_ui_font(12, QFont.Weight.DemiBold))
        p.setPen(QColor(248, 248, 248))
        disp_name = self.name.capitalize() if self.name.islower() else self.name
        title_rect = QRectF(drawer_x + 9.0, drawer_y + 4.0, drawer_w - 38.0, 20.0)
        p.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            disp_name,
        )

        # Botão de fechar (✕) no canto direito do cabeçalho (Branco nítido no tema escuro)
        close_r = self._close_btn_rect(x0, y_top)
        if self._close_hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 32))
            p.drawRoundedRect(close_r, 4.0, 4.0)

        close_pen = QPen(QColor(255, 255, 255), 1.5)
        close_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        close_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(close_pen)
        cx = close_r.center().x()
        cy = close_r.center().y()
        p.drawLine(QPointF(cx - 3.8, cy - 3.8), QPointF(cx + 3.8, cy + 3.8))
        p.drawLine(QPointF(cx + 3.8, cy - 3.8), QPointF(cx - 3.8, cy + 3.8))

        # B) Abas Segmentadas (Fluent Segmented Pivot): [ Saída ]  [ Entrada ]
        tabs_track = QRectF(x0 + 17.0, drawer_y + 27.0, 206.0, 26.0)
        p.setPen(QPen(self.theme.tabs_border, 1.0))
        p.setBrush(self.theme.tabs_bg)
        p.drawRoundedRect(tabs_track, 5.0, 5.0)

        tab_out_r = self._tab_rect(x0, y_top, "output")
        tab_in_r = self._tab_rect(x0, y_top, "input")

        # Aba Saída
        is_out = (self.active_flow == "output")
        p.setPen(Qt.PenStyle.NoPen)
        if is_out:
            p.setBrush(self.theme.accent)  # Aba ativa (padrão #54aff4)
            p.drawRoundedRect(tab_out_r, 4.0, 4.0)
            p.setFont(get_ui_font(11, QFont.Weight.DemiBold))
            p.setPen(self.theme.on_accent)
        elif self._tab_out_hovered:
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(tab_out_r, 4.0, 4.0)
            p.setFont(get_ui_font(11, QFont.Weight.Normal))
            p.setPen(QColor(240, 240, 240))
        else:
            p.setFont(get_ui_font(11, QFont.Weight.Normal))
            p.setPen(QColor(165, 165, 165))
        p.drawText(tab_out_r, Qt.AlignmentFlag.AlignCenter, t("volume_tab_output"))

        # Aba Entrada
        is_in = (self.active_flow == "input")
        p.setPen(Qt.PenStyle.NoPen)
        if is_in:
            p.setBrush(self.theme.accent)
            p.drawRoundedRect(tab_in_r, 4.0, 4.0)
            p.setFont(get_ui_font(11, QFont.Weight.DemiBold))
            p.setPen(self.theme.on_accent)
        elif self._tab_in_hovered:
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(tab_in_r, 4.0, 4.0)
            p.setFont(get_ui_font(11, QFont.Weight.Normal))
            p.setPen(QColor(240, 240, 240))
        else:
            p.setFont(get_ui_font(11, QFont.Weight.Normal))
            p.setPen(QColor(165, 165, 165))
        p.drawText(tab_in_r, Qt.AlignmentFlag.AlignCenter, t("volume_tab_input"))

        # C) Lista de Dispositivos com PillSwitch
        endpoints = self.output_endpoints if is_out else self.input_endpoints
        switches = self._output_switches if is_out else self._input_switches
        active_id = self.selected_output_id if is_out else self.selected_input_id

        p.save()
        if self._tab_switch_t < 1.0:
            p.setOpacity(p.opacity() * max(0.0, min(1.0, self._tab_switch_t)))

        fm = QFontMetricsF(get_ui_font(11, QFont.Weight.Normal))

        for idx, ep in enumerate(endpoints):
            item_r = self._item_rect(x0, y_top, idx)
            is_active = (ep.device_id == active_id)

            # Efeito de hover na linha do dispositivo (transparente em repouso)
            if self._hovered_dev_id == ep.device_id:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 14))
                p.drawRoundedRect(item_r, 4.0, 4.0)

            # Nome do dispositivo truncado com '...' se necessário
            p.setFont(get_ui_font(11, QFont.Weight.DemiBold if is_active else QFont.Weight.Normal))
            p.setPen(QColor(255, 255, 255) if is_active else QColor(175, 175, 175))

            avail_w = item_r.width() - 44.0
            elided_name = fm.elidedText(ep.name, Qt.TextElideMode.ElideRight, avail_w)
            text_r = QRectF(item_r.left() + 7.0, item_r.top(), avail_w, item_r.height())
            p.drawText(
                text_r,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided_name,
            )

            # PillSwitch animado à direita (28x15px)
            sw = switches.get(ep.device_id)
            if sw:
                sw_x = item_r.right() - sw.WIDTH - 5.0
                sw_y = item_r.top() + (item_r.height() - sw.HEIGHT) * 0.5
                sw.set_geometry(sw_x, sw_y)
                sw.draw(p)

        p.restore()

        p.restore()
