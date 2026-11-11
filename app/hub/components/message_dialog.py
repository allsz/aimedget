"""
Diálogo de mensagem do Hub: substitui o QMessageBox nativo (que ignora o tema) por uma janela no padrão do app.

Hierarquia (uma única leitura): ícone de estado + mensagem; o título já está na barra da janela, então não se repete
dentro do card. A ação fica numa faixa própria no rodapé, separada por um filete (convenção das janelas do Windows 11).

O ícone é desenhado (círculo + glifo em geometria), antialiased e centrado de forma exata, nunca um caractere de texto.

Uso:
    show_message(parent, theme, t("titulo"), t("texto"), kind="warning")
    if confirm(parent, theme, t("titulo"), t("pergunta"), yes=t("sim"), no=t("nao")): ...
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.core.i18n import t
from app.hub.dwm_helper import apply_windows_dwm_titlebar
from app.hub.theme import HubTheme

CONTENT_WIDTH = 420
ICON_SIZE = 28

# Tom de cada tipo: (escuro, claro). Contraste >= 3:1 do glifo sobre o disco translúcido, nos dois temas.
_TONES = {
    "info": ("#7FB2F0", "#2B63B0"),
    "question": ("#7FB2F0", "#2B63B0"),
    "warning": ("#F0906E", "#B0431F"),
    "error": ("#F0906E", "#B0431F"),
}


class StatusIcon(QWidget):
    """Disco translúcido com um glifo desenhado (i, ! ou ?) no centro exato, em coordenadas de uma grade 24x24."""

    def __init__(self, kind: str, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._kind = kind
        self._color = QColor(color)
        self.setFixedSize(ICON_SIZE, ICON_SIZE)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        scale = self.width() / 24.0
        p.scale(scale, scale)

        disc = QColor(self._color)
        disc.setAlphaF(0.16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(disc)
        p.drawEllipse(QRectF(0, 0, 24, 24))

        pen = QPen(self._color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        dot = 1.15
        if self._kind == "info":
            p.drawLine(QPointF(12, 10.6), QPointF(12, 17.2))    # haste
            self._dot(p, 12, 7.2, dot)
        elif self._kind in ("warning", "error"):
            p.drawLine(QPointF(12, 6.8), QPointF(12, 13.4))     # haste
            self._dot(p, 12, 17.0, dot)
        else:   # question
            hook = QPainterPath()
            rect = QRectF(9.2, 6.2, 5.6, 5.6)
            hook.arcMoveTo(rect, 180)
            hook.arcTo(rect, 180, -250)
            hook.lineTo(12, 13.9)
            p.drawPath(hook)
            self._dot(p, 12, 17.2, dot)
        p.end()

    def _dot(self, p: QPainter, x: float, y: float, r: float):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(QPointF(x, y), r, r)


class MessageDialog(QDialog):
    def __init__(self, parent: QWidget | None, theme: HubTheme, title: str, text: str, kind: str = "info",
                 yes: str | None = None, no: str | None = None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setStyleSheet(f"QDialog {{ background: {theme.bg}; }}")
        self.setFixedWidth(CONTENT_WIDTH)

        dark, light = _TONES.get(kind, _TONES["info"])
        tone = dark if theme.is_dark else light

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Corpo: ícone + mensagem, com o topo do ícone alinhado à primeira linha do texto
        body = QHBoxLayout()
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(16)
        body.addWidget(StatusIcon(kind, tone), 0, Qt.AlignmentFlag.AlignTop)
        message = QLabel(text)
        message.setWordWrap(True)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message.setMinimumHeight(ICON_SIZE)   # uma linha curta fica centrada no ícone
        message.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        message.setStyleSheet(f"color: {theme.text}; font-size: 14px; font-weight: 400;")
        body.addWidget(message, 1)
        root.addLayout(body)

        # Rodapé: faixa própria para a ação
        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer.setStyleSheet(f"QFrame#dialogFooter {{ background: {theme.sidebar_bg}; "
                             f"border-top: 1px solid {theme.line}; }}")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        buttons.setSpacing(8)
        buttons.addStretch()
        if no is not None:
            buttons.addWidget(self._button(no, self.reject))
        ok = self._button(yes or t("dialog_ok"), self.accept, primary=True)
        ok.setDefault(True)
        buttons.addWidget(ok)
        root.addWidget(footer)
        self.btn_ok = ok
        self.adjustSize()

    def showEvent(self, event):
        super().showEvent(event)
        # Barra de título na cor do corpo (o handle só é válido depois de a janela existir)
        apply_windows_dwm_titlebar(int(self.winId()), self._theme.bg, self._theme.text, self._theme.is_dark)

    @staticmethod
    def _button(text: str, slot, primary: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "Chip")
        if primary:
            btn.setProperty("selected", "true")
        btn.setMinimumWidth(88)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn


def show_message(parent: QWidget | None, theme: HubTheme, title: str, text: str, kind: str = "info") -> None:
    MessageDialog(parent, theme, title, text, kind).exec()


def confirm(parent: QWidget | None, theme: HubTheme, title: str, text: str, yes: str, no: str) -> bool:
    """Pergunta sim/não; o padrão (Enter) é a ação principal `yes`, Esc cancela."""
    dialog = MessageDialog(parent, theme, title, text, "question", yes=yes, no=no)
    return dialog.exec() == QDialog.DialogCode.Accepted
