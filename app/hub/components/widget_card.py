"""
WidgetCard - Card de exibição da galeria de widgets do Hub.
Tipografia Notion: Sem negritos berrantes, espaçamento equilibrado e rótulos de status refinados.
Suporta pré-visualizações vetoriais puras via PreviewStage e especificações declarativas.
"""

from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.i18n import t
from app.core.preview_registry import WidgetSpec, SkinSpec
from app.hub.components.pill_switch import PillSwitch
from app.hub.components.preview_stage import PreviewStage
from app.hub.theme import HubTheme, THEME_LIGHT


class WidgetCard(QFrame):
    toggled = Signal(str, bool)
    customize = Signal(str)

    def __init__(
        self,
        widget_id: str,
        name: str,
        category: str,
        skin_label: str,
        spec: Optional[WidgetSpec | SkinSpec] = None,
        preview_widget: Optional[QWidget] = None,
        is_active: bool = True,
        theme: HubTheme = THEME_LIGHT,
        parent=None,
    ):
        super().__init__(parent)
        self.widget_id = widget_id
        self.widget_name = name
        self.category = category
        self.skin_label = skin_label
        self._spec = spec
        self.is_active = is_active
        self._theme = theme

        self.setProperty("class", "HubCard")
        self._build_ui(preview_widget)

    def _build_ui(self, preview_widget: Optional[QWidget]):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Cabeçalho: Título + Categoria/Skin + Switch
        header = QHBoxLayout()
        header.setSpacing(8)

        info_box = QVBoxLayout()
        info_box.setSpacing(2)

        self.lbl_title = QLabel(self.widget_name)
        self.lbl_title.setStyleSheet(f"color: {self._theme.text}; font-size: 14.5px; font-weight: 600;")
        info_box.addWidget(self.lbl_title)

        self.lbl_subtitle = QLabel(f"{self.category} · {self.skin_label}")
        self.lbl_subtitle.setStyleSheet(f"color: {self._theme.mute}; font-size: 12px; font-weight: 400;")
        info_box.addWidget(self.lbl_subtitle)

        header.addLayout(info_box, stretch=1)

        # Pill switch com animação suave
        self.switch = PillSwitch(checked=self.is_active, theme=self._theme, parent=self)
        self.switch.toggled_value.connect(self._on_switch_toggled)
        header.addWidget(self.switch)

        main_layout.addLayout(header)

        # Palco neutro da miniatura
        self.stage = QFrame(self)
        self.stage.setProperty("class", "StageCard")
        self.stage.setFixedHeight(128)

        stage_layout = QVBoxLayout(self.stage)
        stage_layout.setContentsMargins(8, 8, 8, 8)
        stage_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self._spec:
            self.stage_preview = PreviewStage(spec=self._spec, theme=self._theme, parent=self.stage)
            stage_layout.addWidget(self.stage_preview)
        elif preview_widget:
            self.preview_widget = preview_widget
            stage_layout.addWidget(preview_widget)

        main_layout.addWidget(self.stage)

        # Rodapé: Botão Configurar
        footer = QHBoxLayout()
        self.btn_customize = QPushButton(t("card_configure"), self)
        self.btn_customize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_customize.setStyleSheet(
            f"""
            QPushButton {{
                background: none;
                border: none;
                color: {self._theme.mute};
                font-weight: 500;
                font-size: 12.5px;
                text-align: left;
                padding: 2px 0px;
            }}
            QPushButton:hover {{
                color: {self._theme.text};
            }}
            """
        )
        self.btn_customize.clicked.connect(lambda: self.customize.emit(self.widget_id))
        footer.addWidget(self.btn_customize)
        footer.addStretch()

        main_layout.addLayout(footer)

    def set_spec(self, spec: WidgetSpec | SkinSpec, skin_label: Optional[str] = None):
        """Atualiza dinamicamente a especificação visual e o rótulo do card."""
        self._spec = spec
        if skin_label:
            self.skin_label = skin_label
            self.lbl_subtitle.setText(f"{self.category} · {self.skin_label}")
        if hasattr(self, "stage_preview"):
            self.stage_preview.set_spec(spec)

    def retranslate_ui(self, name: Optional[str] = None, skin_label: Optional[str] = None):
        if name:
            self.widget_name = name
            self.lbl_title.setText(name)
        if skin_label:
            self.skin_label = skin_label
        self.lbl_subtitle.setText(f"{self.category} · {self.skin_label}")
        self.btn_customize.setText(t("card_configure"))

    def _on_switch_toggled(self, checked: bool):
        self.is_active = checked
        self.toggled.emit(self.widget_id, checked)

    def set_theme(self, theme: HubTheme):
        self._theme = theme
        self.switch.set_theme(theme)
        if hasattr(self, "stage_preview"):
            self.stage_preview.set_theme(theme)
        self.lbl_title.setStyleSheet(f"color: {self._theme.text}; font-size: 14.5px; font-weight: 600;")
        self.lbl_subtitle.setStyleSheet(f"color: {self._theme.mute}; font-size: 12px; font-weight: 400;")
        self.btn_customize.setStyleSheet(
            f"""
            QPushButton {{
                background: none;
                border: none;
                color: {self._theme.mute};
                font-weight: 500;
                font-size: 12.5px;
                text-align: left;
                padding: 2px 0px;
            }}
            QPushButton:hover {{
                color: {self._theme.text};
            }}
            """
        )
