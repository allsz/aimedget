"""
Cartão "Tamanho e escala" do Hub, igual para todo widget (Música, Clima, Desempenho).

Um chip "Automático" (segue a resolução da tela) e um Jelly Slider em % para o tamanho manual. Arrastar o controle sai
do automático; clicar em Automático devolve o controle ao tamanho da tela, e o polegar acompanha o widget enquanto ele
anima até lá (por isso `set_state` não anima: o widget já é o movimento).

Composição: título e legenda à esquerda e o chip à direita, centrado nelas (como nas outras linhas do Hub); o controle
vem abaixo, na largura toda, com a trilha alinhada à borda do texto.
"""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.core.i18n import t
from app.hub.components.tab_pill import ChipGroup
from app.hub.theme import HubTheme
from app.ui_components.jelly_slider import JellySlider
from PySide6.QtCore import Qt

COMMIT_DELAY_MS = 350   # teclado: grava pouco depois da última tecla (o arraste grava ao soltar)


class ScaleCard(QFrame):
    auto_clicked = Signal()
    live_changed = Signal(int)       # % enquanto o controle se move (aplicar sem gravar)
    committed = Signal(int)          # % final (gravar)

    def __init__(self, title_key: str, sub_key: str, theme: HubTheme, pct_min: int, pct_max: int, parent=None):
        super().__init__(parent)
        self.setProperty("class", "HubCard")
        self._title_key, self._sub_key = title_key, sub_key
        self._theme = theme

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 8)   # o controle traz folga própria embaixo (marcas e números)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        self._title = QLabel(t(title_key))
        self._title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self._sub = QLabel(t(sub_key))
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        text.addWidget(self._title)
        text.addWidget(self._sub)
        head.addLayout(text, stretch=1)
        self._auto = ChipGroup([("auto", t("music_scale_auto"))], lambda _k: self._on_auto(), theme, parent=self)
        head.addWidget(self._auto, alignment=Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(head)

        self._slider = JellySlider(minimum=pct_min, maximum=pct_max, value=100, step_minor=5, step_major=25,
                                   theme=theme, parent=self, suffix="%",
                                   headroom=30.0, side_pad=0.0)   # trilha na borda do texto; gota sobe sem folga sobrando
        self._slider.value_changed.connect(self._on_slider_changed)
        self._slider.interaction_finished.connect(self._commit)
        root.addWidget(self._slider)

        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(COMMIT_DELAY_MS)
        self._commit_timer.timeout.connect(self._commit)

    # --- Estado vindo do widget ---

    def set_state(self, auto: bool, pct: int):
        """Reflete o widget: chip Automático marcado ou não e o polegar no tamanho de agora (sem puxar o do usuário)."""
        if self._slider.is_busy() or self._commit_timer.isActive():
            return
        self._auto.set_selected("auto" if auto else None)
        self._slider.set_value(int(pct), animated=False)

    def is_busy(self) -> bool:
        return self._slider.is_busy() or self._commit_timer.isActive()

    # --- Interação ---

    def _on_auto(self):
        self._commit_timer.stop()
        self.auto_clicked.emit()

    def _on_slider_changed(self, pct: int):
        self._auto.set_selected(None)   # mexeu no controle: sai do automático
        self.live_changed.emit(int(pct))
        self._commit_timer.start()

    def _commit(self):
        self._commit_timer.stop()
        self.committed.emit(int(self._slider.value()))

    # --- Aparência ---

    @property
    def chips(self) -> dict:
        return self._auto.buttons

    @property
    def slider(self) -> JellySlider:
        return self._slider

    def retranslate(self):
        self._title.setText(t(self._title_key))
        self._sub.setText(t(self._sub_key))
        self._auto.buttons["auto"].setText(t("music_scale_auto"))

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self._sub.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        self._auto.set_theme(theme)
        self._slider.set_theme(theme)
