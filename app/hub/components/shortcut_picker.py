"""
ShortcutPicker - Componente visual e interativo para exibição e personalização de atalhos.
Diretrizes Impeccable (Operate/Tool Mode):
- Tipografia Inter com pesos controlados e renderização antialiased via QPainter (imune a cortes/clipping de DPI).
- Badges de tecla elegantes estilo <kbd> com breathing room proporcional ao avanço horizontal da fonte.
- Layout horizontal e vertical estável: o modo de gravação nunca altera a largura do card nem transborda da janela.
- Instruções secundárias exibidas em linha auxiliar inferior, mantendo alinhamento impecável.
"""

import ctypes
from PySide6.QtCore import Qt, Signal, QSize, QRectF
from PySide6.QtGui import (
    QKeyEvent,
    QFont,
    QFontMetrics,
    QPainter,
    QColor,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)

from app.core.i18n import t
from app.core.typography import get_ui_font
from app.hub.theme import HubTheme, THEME_LIGHT
from app.services.hotkey_service import HotkeyParser

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


class KeyBadge(QWidget):
    """
    Badge de tecla individual renderizado via QPainter.
    Imune a problemas de truncamento de texto, padding css ou DPI scaling no Windows.
    """

    def __init__(self, text: str, theme: HubTheme, parent=None):
        super().__init__(parent)
        self._text = text
        self._theme = theme
        self._font = get_ui_font(12, QFont.Weight.DemiBold)
        self.setFont(self._font)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._font)
        adv = fm.horizontalAdvance(self._text)
        w = max(38, adv + 24)
        return QSize(w, 28)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Fundo do keycap com cantos arredondados
        path = QPainterPath()
        path.addRoundedRect(rect, 5.0, 5.0)
        p.fillPath(path, QColor(self._theme.panel2))

        # Borda sutil de tecla física (leve realce na base)
        p.setPen(QColor(self._theme.line))
        p.drawPath(path)

        # Texto centrado e nítido
        p.setPen(QColor(self._theme.text))
        p.setFont(self._font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class RecordingBadge(QWidget):
    """Badge de status exibido dentro do container durante a gravação de atalho."""

    def __init__(self, theme: HubTheme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._font = get_ui_font(12, QFont.Weight.DemiBold)
        self.setFont(self._font)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(126, 28)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = QRectF(self.rect())

        # Ponto indicador de gravação pulsante/destacado
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._theme.accent))
        p.drawEllipse(rect.left() + 4, rect.center().y() - 4, 8.0, 8.0)

        # Rótulo nítido
        p.setPen(QColor(self._theme.accent))
        p.setFont(self._font)
        text_rect = QRectF(rect.left() + 18, rect.top(), rect.width() - 20, rect.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, t("shortcut_recording"))


class ShortcutPicker(QWidget):
    """
    Componente para exibição e personalização de atalho de teclado global.
    Mantém layout estável sem esticar o card horizontalmente.
    """

    shortcut_changed = Signal(str)

    def __init__(
        self,
        current_shortcut: str = "Win+Alt+M",
        default_shortcut: str = "Win+Alt+M",
        theme: HubTheme = THEME_LIGHT,
        parent=None,
    ):
        super().__init__(parent)
        self._current_shortcut = current_shortcut
        self._default_shortcut = default_shortcut
        self._theme = theme
        self._is_recording = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(4)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Linha 1: Badges + Botão Alterar + Botão Padrão
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_row.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Container dos badges de tecla
        self.badge_box = QFrame(self)
        self.badge_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge_layout = QHBoxLayout(self.badge_box)
        self.badge_layout.setContentsMargins(6, 4, 6, 4)
        self.badge_layout.setSpacing(5)
        self.badge_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.badge_box)

        # Botão Alterar / Cancelar
        self.btn_edit = QPushButton(t("shortcut_edit"), self)
        self.btn_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.clicked.connect(self._toggle_recording)
        top_row.addWidget(self.btn_edit)

        # Botão Restaurar padrão
        self.btn_reset = QPushButton(t("shortcut_reset"), self)
        self.btn_reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_reset.setToolTip(t("shortcut_reset_tooltip", hotkey=self._default_shortcut))
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.clicked.connect(self._reset_to_default)
        top_row.addWidget(self.btn_reset)

        root_layout.addLayout(top_row)

        # Linha 2: Dica auxiliar em modo de gravação (não afeta largura horizontal)
        self.lbl_hint = QLabel(t("shortcut_hint"), self)
        self.lbl_hint.setFont(get_ui_font(11, QFont.Weight.Medium))
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_hint.setVisible(False)
        root_layout.addWidget(self.lbl_hint)

        self._render_badges()
        self._apply_styles()

    def _render_badges(self):
        # Limpa e desvincula widgets anteriores imediatamente do layout para evitar sobreposições
        while self.badge_layout.count():
            item = self.badge_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        if self._is_recording:
            rec_badge = RecordingBadge(self._theme, self.badge_box)
            self.badge_layout.addWidget(rec_badge)
            return

        formatted = HotkeyParser.format_display(self._current_shortcut)
        tokens = [t.strip() for t in formatted.split("+") if t.strip()]

        for i, token in enumerate(tokens):
            badge = KeyBadge(token, self._theme, self.badge_box)
            self.badge_layout.addWidget(badge)
            if i < len(tokens) - 1:
                plus = QLabel("+", self.badge_box)
                plus.setFont(get_ui_font(12, QFont.Weight.Medium))
                plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
                plus.setFixedWidth(14)
                plus.setStyleSheet(f"color: {self._theme.mute}; font-weight: 500;")
                self.badge_layout.addWidget(plus)

    def _apply_styles(self):
        accent = self._theme.accent
        border_color = accent if self._is_recording else self._theme.line
        bg_color = self._theme.panel2 if not self._is_recording else self._theme.panel

        self.badge_box.setStyleSheet(
            f"""
            QFrame {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 7px;
            }}
            """
        )

        chip_css = f"""
            QPushButton {{
                background-color: {self._theme.panel2};
                color: {self._theme.text};
                border: 1px solid {self._theme.line};
                border-radius: 6px;
                min-height: 28px;
                padding: 4px 14px;
                font-family: 'Inter', -apple-system, sans-serif;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {self._theme.line};
                color: {self._theme.text};
            }}
            QPushButton:pressed {{
                background-color: {self._theme.panel};
            }}
        """
        self.btn_edit.setStyleSheet(chip_css)
        self.btn_reset.setStyleSheet(chip_css)

        # Ajusta larguras mínimas baseadas na métrica de texto real
        fm = self.fontMetrics()
        self.btn_edit.setMinimumWidth(max(78, fm.horizontalAdvance("Cancelar") + 28))
        self.btn_reset.setMinimumWidth(max(68, fm.horizontalAdvance("Padrão") + 24))

        self.btn_reset.setVisible(self._current_shortcut != self._default_shortcut and not self._is_recording)

        self.lbl_hint.setStyleSheet(
            f"color: {self._theme.accent}; font-family: 'Inter', sans-serif; font-size: 11px; font-weight: 500;"
        )

    def _toggle_recording(self):
        if self._is_recording:
            self._cancel_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        self._is_recording = True
        self.btn_edit.setText(t("shortcut_cancel"))
        self.lbl_hint.setVisible(True)
        self._render_badges()
        self._apply_styles()
        self.setFocus()

    def _cancel_recording(self):
        self._is_recording = False
        self.btn_edit.setText(t("shortcut_edit"))
        self.lbl_hint.setVisible(False)
        self._render_badges()
        self._apply_styles()

    def retranslate_ui(self):
        if self._is_recording:
            self.btn_edit.setText(t("shortcut_cancel"))
        else:
            self.btn_edit.setText(t("shortcut_edit"))
        self.btn_reset.setText(t("shortcut_reset"))
        self.btn_reset.setToolTip(t("shortcut_reset_tooltip", hotkey=self._default_shortcut))
        self.lbl_hint.setText(t("shortcut_hint"))

    def _reset_to_default(self):
        self._current_shortcut = self._default_shortcut
        self.shortcut_changed.emit(self._default_shortcut)
        self._cancel_recording()

    def mousePressEvent(self, event):
        # Clicar na área de badges também inicia a gravação
        if self.badge_box.geometry().contains(event.pos()):
            if not self._is_recording:
                self._start_recording()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if not self._is_recording:
            super().keyPressEvent(event)
            return

        key = event.key()

        # Cancela gravação se pressionar Escape
        if key == Qt.Key.Key_Escape:
            self._cancel_recording()
            return

        # Aguarda a tecla final de ação se apenas teclas modificadoras forem pressionadas
        if key in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
            Qt.Key.Key_AltGr,
        ):
            return

        # Identifica modificadores ativos
        mods = []
        is_win = bool(event.modifiers() & Qt.KeyboardModifier.MetaModifier)
        if not is_win and user32:
            is_win = bool((user32.GetAsyncKeyState(0x5B) & 0x8000) or (user32.GetAsyncKeyState(0x5C) & 0x8000))

        if is_win:
            mods.append("Win")
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            mods.append("Ctrl")
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            mods.append("Alt")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            mods.append("Shift")

        # Se o usuário não segurou nenhum modificador, adiciona Win+Alt como base padrão segura
        if not mods:
            mods = ["Win", "Alt"]

        # Extrai nome legível da tecla pressionada
        key_name = ""
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            key_name = chr(key).upper()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            key_name = chr(key)
        elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            key_name = f"F{key - Qt.Key.Key_F1 + 1}"
        elif key == Qt.Key.Key_Space:
            key_name = "Space"
        else:
            raw_name = Qt.Key(key).name.replace("Key_", "")
            if len(raw_name) <= 6:
                key_name = raw_name

        if not key_name:
            return

        new_shortcut = "+".join(mods + [key_name])
        self._current_shortcut = new_shortcut
        self.shortcut_changed.emit(new_shortcut)
        self._cancel_recording()

    def focusOutEvent(self, event):
        fw = QApplication.focusWidget()
        if fw and self.isAncestorOf(fw):
            super().focusOutEvent(event)
            return
        if self._is_recording:
            self._cancel_recording()
        super().focusOutEvent(event)

    def set_shortcut(self, shortcut: str):
        self._current_shortcut = shortcut
        self._render_badges()
        self._apply_styles()

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._render_badges()
        self._apply_styles()
