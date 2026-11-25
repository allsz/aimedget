"""Hub: base das páginas do Hub (rolagem e cartão-base). Extraído de `pages.py` (mesmo código, só em arquivo próprio)."""

from typing import Optional
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from app.core.i18n import t
from app.hub.components.chips import chip
from app.hub.components.help_badge import HelpBadge
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.position_picker import PositionPicker
from app.hub.service_bridge import get_service_bridge
from app.hub.theme import HubTheme, THEME_LIGHT
from app.hub.ui_tokens import BADGE_GAP, CARD_MARGINS, INFO_GAP, INLINE_GAP, PAGE_GAP


class HubScrollArea(QScrollArea):
    """QScrollArea com contenção estrita de viewport: nunca rola horizontalmente nem deixa conteúdo vazar."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.widget()
        if w:
            vw = self.viewport().width()
            if vw > 100:
                w.setFixedWidth(vw)


class BaseHubPage(QWidget):
    """Página base com estrutura padronizada, espaçamento arejado e rolagem suave."""

    def __init__(self, title: str, subtitle: str, theme: HubTheme = THEME_LIGHT, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._texts: list[tuple[QLabel, str]] = []   # (rótulo, chave i18n) para retraduzir
        self._subs: list[QLabel] = []                # legendas cinzas (a cor muda com o tema)
        self._help_badges: list = []                 # (HelpBadge, chave i18n)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = HubScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(32, 28, 36, 32)
        self.content_layout.setSpacing(PAGE_GAP)

        # Header padronizado
        self.lbl_title = QLabel(title)
        self.lbl_title.setProperty("class", "SectionTitle")
        self.content_layout.addWidget(self.lbl_title)

        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setProperty("class", "SectionSubtitle")
        self.lbl_sub.setWordWrap(True)
        if not bool(subtitle):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            self.lbl_sub.hide()
        self.content_layout.addWidget(self.lbl_sub)

        self.scroll.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll)

    def showEvent(self, event):
        super().showEvent(event)
        self._lock_card_heights()

    def _lock_card_heights(self):
        """
        Nenhum card cresce além da própria altura quando a janela é alta (tela em pé ou tela cheia): sem isso, um
        espaçador expansivo dentro do card (addStretch) o faz disputar a altura sobrando e engordar. A sobra fica
        no fim da página. Idempotente; vale para cards de qualquer página, inclusive os de páginas futuras.
        """
        for frame in self.content_widget.findChildren(QFrame):
            if frame.property("class") == "HubCard":
                frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    # --- Peças padrão das páginas (uma só versão para todas; espaçamentos de app/hub/ui_tokens.py) ---

    def _card(self, vertical: bool = False):
        card = QFrame()
        card.setProperty("class", "HubCard")
        layout = QVBoxLayout(card) if vertical else QHBoxLayout(card)
        layout.setContentsMargins(*CARD_MARGINS)
        return card, layout

    def _info(self, title_key: str, sub_key: str, title_px: float = 13.5, help_key: str | None = None) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(INFO_GAP)
        title = QLabel(t(title_key))
        title.setStyleSheet(f"font-size: {title_px}px; font-weight: 600;")
        if help_key:
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(BADGE_GAP)
            title_row.addWidget(title)
            badge = HelpBadge(t(help_key), theme=self._theme)
            title_row.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)
            title_row.addStretch()
            box.addLayout(title_row)
            self._help_badges.append((badge, help_key))
        else:
            box.addWidget(title)
        sub_txt = t(sub_key)
        sub = QLabel(sub_txt)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        if not bool(sub_txt):   # sem pai ainda: setVisible(True) abriria uma janela solta; só oculta o vazio
            sub.hide()
        box.addWidget(sub)
        self._texts += [(title, title_key), (sub, sub_key)]
        self._subs.append(sub)
        return box

    @staticmethod
    def _divider() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setProperty("class", "HubDivider")
        return sep

    @staticmethod
    def _chip(text: str, on_click) -> QPushButton:
        return chip(text, on_click)

    def _switch_row(self, col: QVBoxLayout, title_key: str, sub_key: str, checked: bool, on_toggle) -> PillSwitch:
        row = QHBoxLayout()
        row.setSpacing(INLINE_GAP)
        row.addLayout(self._info(title_key, sub_key), stretch=1)
        sw = PillSwitch(checked=checked, theme=self._theme)
        sw.toggled.connect(on_toggle)
        row.addWidget(sw)
        col.addLayout(row)
        return sw

    def set_header(self, title: str, subtitle: str):
        self.lbl_title.setText(title)
        self.lbl_sub.setText(subtitle)
        self.lbl_sub.setVisible(bool(subtitle))

    def retranslate_ui(self):
        pass

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._set_osd_position_theme(theme)

    def _add_osd_position_card(self, flyout: str, sub_key: str, show_preview) -> None:
        """
        Card "Posição na tela" de um flyout de sistema ('keylock' ou 'mixer'), com 8 âncoras. Cada flyout tem a
        sua posição; se os dois escolherem a mesma, eles se empilham.
        """
        bridge = get_service_bridge()
        card = QFrame()
        card.setProperty("class", "HubCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(*CARD_MARGINS)
        row.setSpacing(INLINE_GAP)

        info = QVBoxLayout()
        info.setSpacing(INFO_GAP)
        self.t_osd_pos = QLabel(t("osd_pos_title"))
        self.t_osd_pos.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.s_osd_pos = QLabel(t(sub_key))
        self.s_osd_pos.setWordWrap(True)
        self.s_osd_pos.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        self._osd_pos_sub_key = sub_key
        info.addWidget(self.t_osd_pos)
        info.addWidget(self.s_osd_pos)
        row.addLayout(info, stretch=1)
        row.setAlignment(info, Qt.AlignmentFlag.AlignVCenter)   # título e descrição centralizados ao lado do seletor

        self.osd_pos_picker = PositionPicker(
            current_pos=bridge.get_osd_anchor(flyout), theme=self._theme, parent=card, with_middle_row=True
        )

        def on_picked(anchor: str):
            bridge.set_osd_anchor(flyout, anchor)
            show_preview()   # mostra o flyout já no lugar novo

        def on_external_change(changed: str, anchor: str):
            if changed == flyout:
                self.osd_pos_picker.select(anchor)

        self.osd_pos_picker.position_changed.connect(on_picked)
        bridge.osd_anchor_changed.connect(on_external_change)
        row.addWidget(self.osd_pos_picker)
        self.content_layout.addWidget(card)

    def _retranslate_osd_position_card(self):
        if hasattr(self, "t_osd_pos"):
            self.t_osd_pos.setText(t("osd_pos_title"))
            self.s_osd_pos.setText(t(self._osd_pos_sub_key))

    def _set_osd_position_theme(self, theme: HubTheme):
        if hasattr(self, "osd_pos_picker"):
            self.osd_pos_picker.set_theme(theme)
            self.s_osd_pos.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")

    def scroll_to_widget(self, target: QWidget, focus_widget: Optional[QWidget] = None):
        """Rola a página até a seção alvo, aguardando o layout estabilizar após exibir/trocar de aba."""
        def _apply():
            if not target.isVisible():
                return
            self.content_widget.adjustSize()
            y = target.mapTo(self.content_widget, QPoint(0, 0)).y()
            bar = self.scroll.verticalScrollBar()
            bar.setValue(max(0, min(bar.maximum(), y - 20)))
            if focus_widget is not None and focus_widget.isEnabled() and focus_widget.isVisible():
                focus_widget.setFocus()

        _apply()
        QTimer.singleShot(0, _apply)
