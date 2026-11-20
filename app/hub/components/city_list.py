"""
CityList - lista curta e reordenável (as cidades do Weather Widget), com movimento.

Cada linha: alça ⠿ para arrastar, nome + detalhe (estado/país) e ✕ para remover.
- Reordenar: a linha pega pela alça levanta (cresce 3% e ganha sombra) e segue o cursor; as outras deslizam com mola
  para abrir espaço e, ao soltar, ela assenta no lugar com a velocidade que tinha. Emite `moved(de, para)` ao soltar.
  Feito à mão (e não com QListWidget) porque o arrastar interno do QListWidget perde os widgets das linhas.
- Remover (protótipo mockups/weather-city-remove-check.html, valores escolhidos): um clique no ✕ o amassa, ele vira
  um círculo na cor de destaque com um "pop" e um check se desenha; depois de uma pausa a linha sobe e some, e as de
  baixo sobem com mola para fechar o espaço. `removed(i)` é emitido já no clique (o contador e a busca atualizam na
  hora); a animação continua sozinha.
- Adicionar (protótipo mockups/weather-city-list-motion.html, "Unfold and rise" a 1,0×): o espaço abre e o conteúdo
  sobe de dentro de um desfoque.

As linhas têm chave (`set_items([(chave, nome, detalhe)])`): só a que entrou anima a entrada e só a que saiu anima a
saída; o resto da lista não é recriado. Molas no mesmo modelo do protótipo (Euler semi-implícito, massa 1, 4 subpassos).
Com os efeitos de animação do Windows desligados, tudo acontece na hora.
"""

import math
import time

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsBlurEffect, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.core.i18n import t
from app.core.refresh_rate import refresh_interval_ms
from app.core.widget_animator import animations_enabled
from app.hub.theme import HubTheme
from app.widgets.weather.motion import cubic_bezier
from app.core.frame_clock import FrameTimer

ROW_GAP = 6                  # espaço entre linhas (fica DENTRO da linha, para fechar junto com ela ao sair)
FRAME_MS = 16
QWIDGETSIZE_MAX = (1 << 24) - 1

# Molas (rigidez, amortecimento) do botão de referência ("hold button")
MORPH = (320.0, 20.0)        # ✕ -> círculo
PRESS = (520.0, 20.0)        # amassar / pop
LIFT = (260.0, 24.0)         # a linha subindo
GAP = (280.0, 22.0)          # as de baixo subindo para fechar o espaço

# Remoção (valores escolhidos no protótipo)
SQUASH_SCALE = 0.9
SQUASH_S = 0.09
COLOR_S = 0.18               # cinza -> cor de destaque
GLYPH_FADE_S = 0.20          # o ✕ some
CHECK_SHOW_DELAY_S, CHECK_SHOW_S = 0.12, 0.10
CHECK_DRAW_DELAY_S, CHECK_DRAW_S = 0.16, 0.20
PAUSE_S = 0.35
LIFT_PX = 10.0
FADE_S = 0.25

# Entrada "Unfold and rise" (1,0×, sem realce)
OPEN_S = 0.30
RISE_DELAY_S, RISE_S = 0.07, 0.36
RISE_PX, RISE_BLUR = 10.0, 5.0

EASE_SMOOTH_OUT = cubic_bezier(0.22, 1.0, 0.36, 1.0)
EASE_CHECK = cubic_bezier(0.65, 0.0, 0.35, 1.0)

BTN_W, BTN_H, BTN_R = 34.0, 28.0, 7.0

# Reordenar: a linha pega "levanta" (cresce um pouco e ganha sombra), segue o cursor, e as outras deslizam com mola
# para abrir espaço; ao soltar, ela assenta no lugar novo com a velocidade que tinha.
LIFT_UP = (520.0, 30.0)      # 0 -> 1 do "levantar" (quase sem quique)
SLIDE = (420.0, 34.0)        # as vizinhas abrindo espaço (um leve passar do ponto)
SETTLE = (380.0, 30.0)       # a linha solta indo para o lugar
LIFT_SCALE = 0.03            # +3% de tamanho no ar
LIFT_SHADOW_Y = 8.0
DRAG_OVERSHOOT = 6.0         # quanto dá para puxar além da primeira/última posição
OVERLAY_MARGIN = 16          # folga em volta da lista para a sombra e o crescimento


class Spring:
    """Mola amortecida (massa 1): `t` é o alvo; `step` avança um subpasso."""

    def __init__(self, x: float, stiffness_damping: tuple):
        self.x = self.t = float(x)
        self.v = 0.0
        self.k, self.c = stiffness_damping

    def step(self, dt: float):
        a = -self.k * (self.x - self.t) - self.c * self.v
        self.v += a * dt
        self.x += self.v * dt

    def settled(self, tol: float = 0.01) -> bool:
        return abs(self.x - self.t) < tol and abs(self.v) < tol * 20


def _prog(now: float, start: float, dur: float) -> float:
    return 0.0 if now <= start else 1.0 if dur <= 0 or now >= start + dur else (now - start) / dur


def _mix(a: QColor, b: QColor, f: float) -> QColor:
    f = max(0.0, min(1.0, f))
    return QColor(round(a.red() + (b.red() - a.red()) * f), round(a.green() + (b.green() - a.green()) * f),
                  round(a.blue() + (b.blue() - a.blue()) * f), round(a.alpha() + (b.alpha() - a.alpha()) * f))


class RemoveButton(QPushButton):
    """O ✕, desenhado à mão: amassa, vira um círculo na cor de destaque e desenha um check."""

    def __init__(self, parent=None, theme: HubTheme | None = None):
        super().__init__(parent)
        self.setFixedSize(int(BTN_W), int(BTN_H))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.theme: HubTheme | None = theme
        self.w, self.h, self.r, self.scale = BTN_W, BTN_H, BTN_R, 1.0
        self.color_f = 0.0      # 0 = cinza do chip, 1 = cor de destaque
        self.glyph_f = 1.0      # opacidade do ✕
        self.check_alpha = 0.0
        self.check_f = 0.0      # quanto do check já foi desenhado
        self._hover = False
        self._keyboard_focus = False

    def set_theme(self, theme: HubTheme):
        self.theme = theme
        self.update()

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                                  Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._keyboard_focus = False
        super().focusOutEvent(event)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        theme = self.theme
        if theme is None:
            return super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent, ink = QColor(theme.accent), QColor(theme.ink)
        idle_bg, idle_border = QColor(theme.panel2), QColor(theme.line)
        glyph = QColor(theme.text)
        if self._hover and self.color_f == 0.0:
            idle_border, glyph = accent, accent
        bg = _mix(idle_bg, accent, self.color_f)
        border = _mix(idle_border, accent, self.color_f)

        c = QPointF(self.width() / 2, self.height() / 2)
        p.translate(c)
        p.scale(self.scale, self.scale)
        rect = QRectF(-self.w / 2 + 0.5, -self.h / 2 + 0.5, self.w - 1, self.h - 1)
        radius = min(self.r, rect.height() / 2)
        p.setPen(QPen(border, 1.0))
        p.setBrush(bg)
        p.drawRoundedRect(rect, radius, radius)
        if self._keyboard_focus and self.hasFocus() and self.color_f == 0.0:
            # Só com o foco vindo do teclado (Tab), como :focus-visible; desenhado por dentro para não ser cortado
            p.setPen(QPen(accent, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), max(1.0, radius - 1.5), max(1.0, radius - 1.5))

        if self.glyph_f > 0.0:   # ✕ (some com um leve encolher, no lugar do desfoque da referência)
            p.save()
            g = glyph
            g.setAlphaF(self.glyph_f)
            s = 0.8 + 0.2 * self.glyph_f
            p.scale(s, s)
            p.setPen(QPen(g, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(-4.2, -4.2), QPointF(4.2, 4.2))
            p.drawLine(QPointF(4.2, -4.2), QPointF(-4.2, 4.2))
            p.restore()

        if self.check_alpha > 0.0 and self.check_f > 0.0:   # check desenhado aos poucos (M5 12.5 l4.5 4.5 L19 7.5)
            unit = 18.0 / 24.0
            pts = [QPointF((x - 12) * unit, (y - 12) * unit) for x, y in ((5, 12.5), (9.5, 17), (19, 7.5))]
            seg = [math.dist((pts[0].x(), pts[0].y()), (pts[1].x(), pts[1].y())),
                   math.dist((pts[1].x(), pts[1].y()), (pts[2].x(), pts[2].y()))]
            remaining = (seg[0] + seg[1]) * self.check_f
            path = QPainterPath(pts[0])
            for i in range(2):
                if remaining <= 0:
                    break
                f = min(1.0, remaining / seg[i])
                a, b = pts[i], pts[i + 1]
                path.lineTo(QPointF(a.x() + (b.x() - a.x()) * f, a.y() + (b.y() - a.y()) * f))
                remaining -= seg[i]
            k = QColor(ink)
            k.setAlphaF(self.check_alpha)
            p.setPen(QPen(k, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.end()


class _Ghost(QWidget):
    """Foto da linha que está saindo: sobe e some por cima de tudo (pode passar do topo da lista)."""

    def __init__(self, parent: QWidget, pixmap: QPixmap):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._pm = pixmap
        self.dy, self.opacity = 0.0, 1.0

    def paintEvent(self, event):
        p = QPainter(self)
        p.setOpacity(self.opacity)
        p.drawPixmap(QPointF(0, LIFT_PX + self.dy), self._pm)
        p.end()


class _CityRow(QWidget):
    def __init__(self, owner: "CityList", key: str, name: str, detail: str):
        super().__init__(owner)
        self._owner = owner
        self.key = key
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, ROW_GAP)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("CityRow")
        outer.addWidget(self.card)
        layout = QHBoxLayout(self.card)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(10)

        self.handle = QLabel("⠿", self.card)
        self.handle.setFixedWidth(16)
        self.handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self.handle.setToolTip(t("weather_city_drag"))
        layout.addWidget(self.handle)

        text = QVBoxLayout()
        text.setSpacing(1)
        self.lbl_name = QLabel(name, self.card)
        self.lbl_detail = QLabel(detail, self.card)
        self.lbl_detail.setVisible(bool(detail))
        text.addWidget(self.lbl_name)
        text.addWidget(self.lbl_detail)
        layout.addLayout(text, stretch=1)

        self.btn_remove = RemoveButton(self.card)
        self.btn_remove.setToolTip(t("weather_city_remove"))
        self.btn_remove.setAccessibleName(t("weather_city_remove"))
        self.btn_remove.clicked.connect(lambda: owner._on_remove_clicked(self))
        layout.addWidget(self.btn_remove)

        self.handle.installEventFilter(self)
        self.anim = None          # animação em curso (_Removal / _Entry)
        self.leaving = False

    def set_texts(self, name: str, detail: str):
        self.lbl_name.setText(name)
        self.lbl_detail.setText(detail)
        self.lbl_detail.setVisible(bool(detail))

    def apply_style(self, theme: HubTheme, dragging: bool = False):
        bg = theme.hover if dragging else theme.panel2
        border = theme.accent if dragging else theme.line
        self.card.setStyleSheet(
            f"QFrame#CityRow {{ background: {bg}; border: 1px solid {border}; border-radius: 9px; }}"
        )
        self.lbl_name.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {theme.text}; background: transparent; border: none;")
        self.lbl_detail.setStyleSheet(f"font-size: 12px; color: {theme.mute}; background: transparent; border: none;")
        self.handle.setStyleSheet(f"font-size: 15px; color: {theme.mute}; background: transparent; border: none;")
        self.btn_remove.theme = theme
        self.btn_remove.update()

    def natural_height(self) -> int:
        return self.card.sizeHint().height() + ROW_GAP

    def lock_height(self, h: float):
        self.setFixedHeight(max(0, int(round(h))))

    def unlock_height(self):
        self.setMinimumHeight(0)
        self.setMaximumHeight(QWIDGETSIZE_MAX)

    # --- Arrastar pela alça ---

    def eventFilter(self, obj, event):
        t_ = event.type()
        if obj is self.handle:
            if t_ == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self._owner._begin_drag(self, event.globalPosition().toPoint()):
                    self.handle.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            if t_ == event.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                self._owner._drag_to(event.globalPosition().toPoint())
                return True
            if t_ == event.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self.handle.setCursor(Qt.CursorShape.OpenHandCursor)
                self._owner._end_drag()
                return True
        return super().eventFilter(obj, event)


class _Removal:
    """✕ -> círculo de destaque + check -> pausa -> a linha sobe e some -> o espaço fecha com mola."""

    def __init__(self, row: _CityRow, owner: "CityList"):
        self.row, self.owner = row, owner
        b = row.btn_remove
        self.W, self.H, self.R = Spring(BTN_W, MORPH), Spring(BTN_H, MORPH), Spring(BTN_R, MORPH)
        self.sc = Spring(1.0, PRESS)
        self.sc.t = SQUASH_SCALE
        self.y = Spring(0.0, LIFT)
        self.gap: Spring | None = None
        self.ghost: _Ghost | None = None
        self.t = 0.0
        self.confirmed = False
        self.leave_at = SQUASH_S + CHECK_DRAW_DELAY_S + CHECK_DRAW_S + PAUSE_S
        self.fade_t = -1.0
        self.gap_h0 = 0.0
        self.done = False
        b.setEnabled(False)
        b.setCursor(Qt.CursorShape.ArrowCursor)

    def tick(self, dt: float) -> bool:
        self.t += dt
        b = self.row.btn_remove
        if not self.confirmed and self.t >= SQUASH_S:
            self.confirmed = True
            self.confirm_t = self.t
            self.W.t, self.H.t, self.R.t = BTN_H, BTN_H, BTN_H / 2   # círculo de 28
            self.sc.t = 1.0
            self.sc.v += 2.5                                          # pop
        sub = dt / 4
        for _ in range(4):
            for s in (self.W, self.H, self.R, self.sc, self.y):
                s.step(sub)
            if self.gap is not None:
                self.gap.step(sub)

        b.w, b.h, b.r, b.scale = self.W.x, self.H.x, self.R.x, self.sc.x
        if self.confirmed:
            ct = self.t - self.confirm_t
            b.color_f = _prog(ct, 0.0, COLOR_S)
            b.glyph_f = 1.0 - _prog(ct, 0.0, GLYPH_FADE_S)
            b.check_alpha = _prog(ct, CHECK_SHOW_DELAY_S, CHECK_SHOW_S)
            b.check_f = EASE_CHECK(_prog(ct, CHECK_DRAW_DELAY_S, CHECK_DRAW_S))
        b.update()

        if self.ghost is None and self.t >= self.leave_at:
            self._start_leaving()
        if self.ghost is not None:
            self.fade_t = min(1.0, self.fade_t + dt / FADE_S)
            e = 1.0 - (1.0 - self.fade_t) ** 3
            self.ghost.dy, self.ghost.opacity = self.y.x, 1.0 - e
            self.ghost.update()
            if self.fade_t >= 1.0 and self.gap is None:
                self.gap_h0 = float(max(1, self.row.height()))
                self.gap = Spring(self.gap_h0, GAP)
                self.gap.t = 0.0
        if self.gap is not None:
            self.row.lock_height(self.gap.x)
            if self.gap.x <= 0.5 and abs(self.gap.v) < 5:
                self.finish()
                return False
        return True

    def _start_leaving(self):
        row = self.row
        host = self.owner.window()
        pm = row.card.grab()
        self.ghost = _Ghost(host, pm)
        pos = row.card.mapTo(host, row.card.rect().topLeft())
        self.ghost.setGeometry(pos.x(), pos.y() - int(LIFT_PX), row.card.width() + 2, row.card.height() + int(LIFT_PX) + 2)
        self.ghost.show()
        self.ghost.raise_()
        row.lock_height(row.height())
        row.card.setVisible(False)
        self.y.t = -LIFT_PX
        self.fade_t = 0.0

    def progress(self) -> float:
        """Quanto do espaço da linha já fechou (0 até o espaço começar a fechar, 1 no fim): os vizinhos que
        aparecem (ex.: "Adicionar minha localização") abrem nesse mesmo ritmo, e a altura do cartão não dá saltos."""
        if self.done:
            return 1.0
        if self.gap is None:
            return 0.0
        return max(0.0, min(1.0, 1.0 - max(0.0, self.gap.x) / self.gap_h0))

    def finish(self):
        self.done = True
        if self.ghost is not None:
            self.ghost.deleteLater()
            self.ghost = None
        self.owner._drop_row(self.row)


class _Entry:
    """Unfold and rise: o espaço abre (300 ms) e o conteúdo sobe de dentro de um desfoque (360 ms, 70 ms depois)."""

    def __init__(self, row: _CityRow):
        self.row = row
        self.t = 0.0
        self.done = False
        self.h = row.natural_height()
        row.lock_height(0)
        self.opacity = QGraphicsOpacityEffect(row)
        self.opacity.setOpacity(0.0)
        row.setGraphicsEffect(self.opacity)
        self.blur = QGraphicsBlurEffect(row.card)
        self.blur.setBlurRadius(RISE_BLUR)
        row.card.setGraphicsEffect(self.blur)
        row.layout().setContentsMargins(0, int(RISE_PX), 0, ROW_GAP)

    def tick(self, dt: float) -> bool:
        self.t += dt
        row = self.row
        row.lock_height(self.h * EASE_SMOOTH_OUT(_prog(self.t, 0.0, OPEN_S)))
        e = EASE_SMOOTH_OUT(_prog(self.t, RISE_DELAY_S, RISE_S))
        self.opacity.setOpacity(e)
        self.blur.setBlurRadius(RISE_BLUR * (1.0 - e))
        row.layout().setContentsMargins(0, int(round(RISE_PX * (1.0 - e))), 0, ROW_GAP)
        if self.t >= max(OPEN_S, RISE_DELAY_S + RISE_S):
            self.finish()
            return False
        return True

    def progress(self) -> float:
        """Quanto do espaço já abriu, na mesma curva da altura da linha (os vizinhos fecham nesse ritmo)."""
        return 1.0 if self.done else EASE_SMOOTH_OUT(_prog(self.t, 0.0, OPEN_S))

    def finish(self):
        self.done = True
        row = self.row
        row.setGraphicsEffect(None)
        row.card.setGraphicsEffect(None)
        row.layout().setContentsMargins(0, 0, 0, ROW_GAP)
        row.unlock_height()


class _ReorderLayer(QWidget):
    """Desenha as linhas durante o arrastar (fotos delas), por cima da lista: as reais ficam transparentes no lugar."""

    def __init__(self, host: QWidget, reorder: "_Reorder"):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._r = reorder

    def paintEvent(self, event):
        r = self._r
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setClipRect(r.clip_rect())
        m = OVERLAY_MARGIN
        for row in r.rows:
            if row is not r.row:
                p.drawPixmap(QPointF(m + row.card.x(), m + r.y[row].x), r.pm[row])
        # A linha pega por último (por cima), com sombra e um pouco maior conforme "levanta"
        row, lift = r.row, max(0.0, r.lift.x)
        pm = r.pm[row]
        w, h = pm.deviceIndependentSize().width(), pm.deviceIndependentSize().height()
        p.save()
        p.translate(m + row.card.x() + w / 2, m + r.y[row].x + h / 2)
        s = 1.0 + LIFT_SCALE * lift
        p.scale(s, s)
        if lift > 0.01:
            for i, (grow, a) in enumerate(((10, 0.05), (6, 0.07), (3, 0.09))):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, round(255 * a * min(1.0, lift))))
                dy = LIFT_SHADOW_Y * lift * (0.6 + 0.2 * i)
                p.drawRoundedRect(QRectF(-w / 2 - grow / 2, -h / 2 + dy - grow / 2 + 2, w + grow, h + grow - 2),
                                  9 + grow / 2, 9 + grow / 2)
        p.drawPixmap(QPointF(-w / 2, -h / 2), pm)   # base opaca; a versão com borda de destaque entra por cima
        p.setOpacity(min(1.0, lift))
        p.drawPixmap(QPointF(-w / 2, -h / 2), r.pm_lifted)
        p.restore()
        p.end()


class _Reorder:
    """
    Um arrastar pela alça, do clique até a linha assentar. As linhas reais ficam no layout (alturas travadas, cartão
    transparente, a alça continua recebendo o mouse) e uma camada desenha as fotos delas nas posições das molas.
    """

    def __init__(self, owner: "CityList", row: _CityRow, global_pos):
        self.owner, self.row = owner, row
        self.rows = list(owner._rows)
        self.from_index = self.rows.index(row)
        self.dragging = True
        self.pm, self.y = {}, {}
        for r in self.rows:
            r.lock_height(r.height())
            self.pm[r] = r.card.grab()
        row.apply_style(owner._theme, dragging=True)
        self.pm_lifted = row.card.grab()
        slots = self._slots()
        for r in self.rows:
            self.y[r] = Spring(slots[r], SETTLE if r is row else SLIDE)
            effect = QGraphicsOpacityEffect(r.card)
            effect.setOpacity(0.0)
            r.card.setGraphicsEffect(effect)
        self.lift = Spring(0.0, LIFT_UP)
        self.lift.t = 1.0
        self.grab_dy = owner.mapFromGlobal(global_pos).y() - slots[row]
        self.drag_y = slots[row]
        self.layer = _ReorderLayer(owner.window(), self)
        self._place_layer()
        self.layer.show()
        self.layer.raise_()

    def _slots(self) -> dict:
        y, out = 0.0, {}
        for r in self.rows:
            out[r] = y
            y += r.height()
        return out

    def _place_layer(self):
        host = self.layer.parentWidget()
        top_left = self.owner.mapTo(host, self.owner.rect().topLeft()) if host is not self.owner else self.owner.rect().topLeft()
        m = OVERLAY_MARGIN
        self.layer.setGeometry(top_left.x() - m, top_left.y() - m, self.owner.width() + 2 * m, self.owner.height() + 2 * m)

    def clip_rect(self) -> QRectF:
        """A parte visível da lista (pode estar rolada), com folga para a sombra só nas bordas que estão à mostra."""
        r, v, m = self.owner.rect(), self.owner.visibleRegion().boundingRect(), OVERLAY_MARGIN
        left = v.left() - (m if v.left() <= r.left() else 0)
        top = v.top() - (m if v.top() <= r.top() else 0)
        right = v.right() + 1 + (m if v.right() >= r.right() else 0)
        bottom = v.bottom() + 1 + (m if v.bottom() >= r.bottom() else 0)
        return QRectF(left + m, top + m, right - left, bottom - top)

    def move_to(self, global_pos):
        row = self.row
        total = sum(r.height() for r in self.rows)
        y = self.owner.mapFromGlobal(global_pos).y() - self.grab_dy
        self.drag_y = max(-DRAG_OVERSHOOT, min(total - row.height() + DRAG_OVERSHOOT, y))
        center = self.drag_y + row.height() / 2
        # Passou do meio da vizinha: troca de lugar com ela (várias de uma vez se o mouse correu)
        while True:
            slots = self._slots()
            i = self.rows.index(row)
            if i > 0 and center < slots[self.rows[i - 1]] + self.rows[i - 1].height() / 2:
                self.rows.insert(i - 1, self.rows.pop(i))
            elif i < len(self.rows) - 1 and center > slots[self.rows[i + 1]] + self.rows[i + 1].height() / 2:
                self.rows.insert(i + 1, self.rows.pop(i))
            else:
                break
        slots = self._slots()
        for r in self.rows:
            self.y[r].t = slots[r]

    def drop(self):
        self.dragging = False
        self.y[self.row].t = self._slots()[self.row]
        self.lift.t = 0.0

    def tick(self, dt: float) -> bool:
        if self.dragging:   # a linha pega segue o cursor; a velocidade fica guardada para o assentar
            s = self.y[self.row]
            s.v = (self.drag_y - s.x) / dt if dt > 0 else 0.0
            s.x = s.t = self.drag_y
        sub = dt / 4
        for _ in range(4):
            self.lift.step(sub)
            for r in self.rows:
                if not (self.dragging and r is self.row):
                    self.y[r].step(sub)
        if self.dragging:
            self.y[self.row].t = self.drag_y
        self._place_layer()
        self.layer.update()
        if not self.dragging and self.lift.settled(0.005) and all(s.settled(0.3) for s in self.y.values()):
            self.finish()
            return False
        return True

    def finish(self):
        for r in self.rows:
            r.card.setGraphicsEffect(None)
            r.unlock_height()
        self.row.apply_style(self.owner._theme)
        self.layer.hide()
        self.layer.deleteLater()
        if self.owner._reorder is self:
            self.owner._reorder = None


class CityList(QWidget):
    moved = Signal(int, int)    # (de, para)
    removed = Signal(int)       # emitido já no clique do ✕ (a linha some com animação depois)
    frame = Signal()            # a cada quadro das animações (vizinhos seguem `current_change().progress`)

    def __init__(self, theme: HubTheme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._rows: list = []          # linhas da lista, na ordem (sem as que estão saindo)
        self._leaving: list = []       # linhas animando a saída (ainda no layout)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._drag_row: _CityRow | None = None
        self._drag_from = -1
        self._reorder: _Reorder | None = None
        self._last_change = None       # última entrada/saída iniciada (os vizinhos acompanham o progresso dela)
        self._populated = False
        self._clock = FrameTimer(self)
        self._clock.setTimerType(Qt.TimerType.PreciseTimer)
        self._clock.setInterval(FRAME_MS)
        self._clock.timeout.connect(self._on_frame)
        self._last = 0.0

    # --- Conteúdo ---

    def set_items(self, items: list, animate: bool = True):
        """
        items: [(chave, nome, detalhe)] na ordem do cartão. Linhas que já existem só atualizam o texto e a ordem;
        uma chave nova entra com animação; uma que sumiu sai com animação (se ainda não estiver saindo).
        """
        animate = animate and self._populated and animations_enabled()
        wanted = [k for k, _n, _d in items]
        if self._reorder is not None and wanted != [r.key for r in self._rows]:
            self._reorder.finish()   # a lista mudou por fora no meio do assentar: termina na hora
        for row in list(self._rows):
            if row.key not in wanted:
                self._rows.remove(row)
                if animate:
                    self._start(row, _Removal(row, self))
                    row.leaving = True
                    self._leaving.append(row)
                else:
                    self._drop_row(row)
        by_key = {r.key: r for r in self._rows}
        new_rows = []
        for key, name, detail in items:
            row = by_key.get(key)
            if row is None:
                row = _CityRow(self, key, name, detail)
                row.apply_style(self._theme)
                self._layout.addWidget(row)
                if animate:
                    self._start(row, _Entry(row))
            else:
                row.set_texts(name, detail)
            new_rows.append(row)
        in_layout = [self._layout.itemAt(i).widget() for i in range(self._layout.count())]
        if [w for w in in_layout if w in new_rows] != new_rows:   # ordem mudou por fora (ex.: menu do cartão)
            for i, row in enumerate(new_rows):
                self._layout.removeWidget(row)
                self._layout.insertWidget(i, row)
        self._rows = new_rows
        for row in self._rows:
            row.handle.setVisible(len(self._rows) > 1)   # uma cidade só não tem o que reordenar
        self._populated = True

    def count(self) -> int:
        return len(self._rows)

    def index_of(self, row) -> int:
        return self._rows.index(row) if row in self._rows else -1

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        for row in self._rows + self._leaving:
            row.apply_style(theme)

    def is_animating(self) -> bool:
        return self._clock.isActive()

    def is_reordering(self) -> bool:
        return self._reorder is not None

    def current_change(self):
        """A entrada/saída de linha em curso (tem `progress()` 0..1), ou None se nada está mudando."""
        anim = self._last_change
        return anim if anim is not None and not anim.done else None

    def follow_current_change(self):
        """Para `Fold.set_open(..., follow)`: acompanha a mudança em curso; None (na hora) se não há nenhuma."""
        anim = self.current_change()
        return (self.frame, anim.progress) if anim is not None else None

    # --- Remover ---

    def _on_remove_clicked(self, row: _CityRow):
        index = self.index_of(row)
        if index < 0 or row.leaving:
            return
        if self._reorder is not None:
            self._reorder.finish()
        self._rows.remove(row)
        row.leaving = True
        self._leaving.append(row)
        if animations_enabled():
            self._start(row, _Removal(row, self))
        else:
            self._drop_row(row)
        for r in self._rows:
            r.handle.setVisible(len(self._rows) > 1)
        self.removed.emit(index)

    def _drop_row(self, row: _CityRow):
        if row in self._leaving:
            self._leaving.remove(row)
        if row in self._rows:
            self._rows.remove(row)
        cut = row.anim is not None and not row.anim.done
        if cut:
            row.anim.done = True   # interrompida: quem acompanhava o progresso dela termina já
        row.anim = None
        row.hide()   # nunca setParent(None): um widget solto vira janela própria por um instante, fora do Hub
        self._layout.removeWidget(row)
        row.deleteLater()
        if cut:
            self.frame.emit()

    # --- Relógio das animações ---

    def _start(self, row: _CityRow | None, anim):
        if row is not None:
            row.anim = anim
            self._last_change = anim
        if not self._clock.isActive():
            self._last = time.perf_counter()
            self._clock.setInterval(refresh_interval_ms(self))   # taxa do monitor onde a lista está agora
            self._clock.start()

    def _on_frame(self):
        now = time.perf_counter()
        dt = min(now - self._last, 1 / 30)
        self._last = now
        alive = False
        if self._reorder is not None and self._reorder.tick(dt):
            alive = True
        for row in list(self._rows) + list(self._leaving):
            anim = row.anim
            if anim is None:
                continue
            if anim.tick(dt):
                alive = True
            elif row.anim is anim:
                row.anim = None
        if not alive:
            self._clock.stop()
        # A altura nova da lista sai já neste quadro (senão ela chega uma passada de layout depois dos vizinhos e o
        # cartão dá um dente); depois os vizinhos leem o mesmo progresso.
        self._layout.activate()
        self.updateGeometry()
        self.frame.emit()
        self._flush_parent_layouts()

    def _flush_parent_layouts(self):
        """
        Faz o cartão, a página e a rolagem recalcularem NESTE quadro. `updateGeometry` só posta um pedido de layout: o
        Qt desenha a janela antes de atendê-lo, então a linha já estava no lugar novo e o cartão (e tudo abaixo dele)
        ainda na altura velha por um quadro: o tremor ao adicionar/remover. Atendendo os pedidos de baixo para cima,
        o contêiner e o conteúdo andam juntos.
        """
        w = self.parentWidget()
        while w is not None and not w.isWindow():
            QCoreApplication.sendPostedEvents(w, QEvent.Type.LayoutRequest)
            w = w.parentWidget()

    # --- Arrastar ---

    def _begin_drag(self, row: _CityRow, global_pos=None) -> bool:
        if self._leaving or row.anim is not None:   # no meio de uma animação o layout está mudando: espera
            return False
        if self._reorder is not None:                # pegou outra antes da anterior assentar
            self._reorder.finish()
        self._drag_row = row
        self._drag_from = self.index_of(row)
        if animations_enabled():
            if global_pos is None:
                global_pos = row.mapToGlobal(row.rect().center())
            self._reorder = _Reorder(self, row, global_pos)
            self._start(None, None)
        else:
            row.apply_style(self._theme, dragging=True)
        return True

    def _drag_to(self, global_pos):
        row = self._drag_row
        if row is None:
            return
        if self._reorder is not None:
            self._reorder.move_to(global_pos)
            order = self._reorder.rows
            if order != self._rows:   # o layout acompanha a ordem (as linhas reais estão transparentes)
                self._rows = list(order)
                for i, r in enumerate(order):
                    self._layout.removeWidget(r)
                    self._layout.insertWidget(i, r)
            return
        y = self.mapFromGlobal(global_pos).y()
        current = self.index_of(row)
        target = current
        # Passou do meio da vizinha: troca de lugar com ela
        if current > 0 and y < self._rows[current - 1].geometry().center().y():
            target = current - 1
        elif current < len(self._rows) - 1 and y > self._rows[current + 1].geometry().center().y():
            target = current + 1
        if target != current:
            self._rows.insert(target, self._rows.pop(current))
            self._layout.removeWidget(row)
            self._layout.insertWidget(target, row)

    def _end_drag(self):
        row = self._drag_row
        if row is None:
            return
        self._drag_row = None
        if self._reorder is not None:
            self._reorder.drop()   # assenta com mola; o estilo volta ao normal quando terminar
            self._start(None, None)
        else:
            row.apply_style(self._theme)
        final = self.index_of(row)
        if final != self._drag_from and final >= 0:
            self.moved.emit(self._drag_from, final)
