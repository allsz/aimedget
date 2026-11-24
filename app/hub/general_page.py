"""Hub: página Geral. Extraído de `pages.py` (mesmo código, só em arquivo próprio)."""

from typing import Optional
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget
from app.core.config_manager import config_manager
from app.core.i18n import i18n, t
from app.core.version import __version__
from app.services.updater_service import UpdateInfo, is_installed_build, updater_service
from app.hub.components.accent_entry import AccentEntryRow
from app.hub.components.tab_pill import ChipGroup
from app.hub.components.theme_swatch import ThemeSwatchGroup
from app.hub.components.hue_slider import MARGIN as SLIDER_MARGIN, HueSlider
from app.hub.components.theme_import_dialog import warning_color
from app.hub.components.pill_switch import PillSwitch
from app.hub.theme import (
    DEFAULT_ACCENT_HUE,
    HubTheme,
    THEME_DARK,
    THEME_LIGHT,
    derive_accent,
    fit_accent,
    hue_of,
    parse_color,
)
from app.hub.base_page import BaseHubPage
from app.hub.ui_tokens import CARD_MARGINS, ROWS_GAP


ACCENT_BOX_W = 272   # largura do bloco da cor de destaque (barra + campo + restaurar)


class GeneralPage(BaseHubPage):
    """Página de preferências gerais com seletores de aparência e idioma refinados."""

    def __init__(
        self,
        on_theme_change=None,
        on_language_change=None,
        on_accent_change=None,
        current_pref: str = "system",
        current_lang: str | None = None,
        theme: HubTheme = THEME_LIGHT,
        parent=None,
    ):
        super().__init__(
            title=t("gen_title"),
            subtitle="",
            theme=theme,
            parent=parent,
        )
        self._on_theme_change = on_theme_change
        self._on_language_change = on_language_change
        self._on_accent_change = on_accent_change
        self._current_pref = current_pref
        self._current_lang = current_lang or config_manager.get_language("pt")
        self._build_settings()

    def _build_settings(self):
        card = QFrame()
        card.setProperty("class", "HubCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(*CARD_MARGINS)
        c_layout.setSpacing(ROWS_GAP)

        # Iniciar com o Windows
        row1 = QHBoxLayout()
        info1 = QVBoxLayout()
        info1.setSpacing(2)
        self.t1 = QLabel(t("gen_startup_title"))
        self.t1.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d1 = QLabel(t("gen_startup_sub"))
        self.d1.setWordWrap(True)
        self.d1.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info1.addWidget(self.t1)
        info1.addWidget(self.d1)
        self.s1 = PillSwitch(checked=config_manager.is_start_with_windows_enabled(), theme=self._theme)
        self.s1.toggled_value.connect(config_manager.set_start_with_windows_enabled)
        row1.addLayout(info1, stretch=1)
        row1.addWidget(self.s1)
        c_layout.addLayout(row1)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setProperty("class", "HubDivider")
        c_layout.addWidget(sep1)

        # Iniciar minimizado
        row_min = QHBoxLayout()
        info_min = QVBoxLayout()
        info_min.setSpacing(2)
        self.t_min = QLabel(t("gen_start_minimized_title"))
        self.t_min.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d_min = QLabel(t("gen_start_minimized_sub"))
        self.d_min.setWordWrap(True)
        self.d_min.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_min.addWidget(self.t_min)
        info_min.addWidget(self.d_min)
        self.s_min = PillSwitch(checked=config_manager.is_start_minimized_enabled(), theme=self._theme)
        self.s_min.toggled_value.connect(config_manager.set_start_minimized_enabled)
        row_min.addLayout(info_min, stretch=1)
        row_min.addWidget(self.s_min)
        c_layout.addLayout(row_min)

        sep_min = QFrame()
        sep_min.setFrameShape(QFrame.Shape.HLine)
        sep_min.setProperty("class", "HubDivider")
        c_layout.addWidget(sep_min)

        # Permanecer no Tray
        row2 = QHBoxLayout()
        info2 = QVBoxLayout()
        info2.setSpacing(2)
        self.t2 = QLabel(t("gen_tray_title"))
        self.t2.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d2 = QLabel(t("gen_tray_sub"))
        self.d2.setWordWrap(True)
        self.d2.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info2.addWidget(self.t2)
        info2.addWidget(self.d2)
        self.s2 = PillSwitch(checked=config_manager.is_keep_in_tray_enabled(), theme=self._theme)
        self.s2.toggled_value.connect(config_manager.set_keep_in_tray_enabled)
        row2.addLayout(info2, stretch=1)
        row2.addWidget(self.s2)
        c_layout.addLayout(row2)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setProperty("class", "HubDivider")
        c_layout.addWidget(sep2)

        # Modo de Aparência (círculos com a cor real do modo; Sistema dividido 50/50 na diagonal)
        row3 = QHBoxLayout()
        self.t3 = QLabel(t("gen_theme_title"))
        self.t3.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        row3.addWidget(self.t3, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._theme_modes = [
            ("light", "gen_theme_light"),
            ("dark", "gen_theme_dark"),
            ("true_dark", "gen_theme_true_dark"),
            ("system", "gen_theme_system"),
        ]
        self._theme_group = ThemeSwatchGroup(
            [(k, t(i)) for k, i in self._theme_modes],
            self._set_theme_mode,
            self._theme,
            selected=self._current_pref,
        )
        self._theme_chips = self._theme_group.buttons
        row3.addWidget(self._theme_group, alignment=Qt.AlignmentFlag.AlignVCenter)
        c_layout.addLayout(row3)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setProperty("class", "HubDivider")
        c_layout.addWidget(sep3)

        # Cor de destaque (matiz): ao vivo ao arrastar, salva ao soltar
        row_acc = QHBoxLayout()
        row_acc.setSpacing(16)
        info_acc = QVBoxLayout()
        info_acc.setSpacing(2)
        self.t_acc = QLabel(t("gen_accent_title"))
        self.t_acc.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d_acc = QLabel(t("gen_accent_sub"))
        self.d_acc.setWordWrap(True)
        self.d_acc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_acc.addWidget(self.t_acc)
        info_acc.addWidget(self.d_acc)
        row_acc.addLayout(info_acc, stretch=1)
        # Bloco de texto centralizado na altura da coluna do seletor. Alinhamento, não addStretch: espaçador
        # expansivo faz o card inteiro crescer quando a janela é alta (tela em pé)
        row_acc.setAlignment(info_acc, Qt.AlignmentFlag.AlignVCenter)

        self._accent_spec = config_manager.get_hub_accent()   # None | matiz | "#RRGGBB"
        # Um só controle: a barra ocupa a largura do bloco; sem cor personalizada, o campo fica alinhado à direita
        # da trilha; com ela, desliza para a esquerda formando um par centralizado com o "Redefinir".
        # O HueSlider reserva HEADROOM (26px) acima da trilha para a onda do arraste; para não criar um vão vazio
        # acima da linha em repouso, o layout reserva só a altura em repouso (30px) e o slider fica ancorado no card
        # (sem recortar a onda ao arrastar e sem invadir a linha de Aparência acima).
        self._general_card = card
        accent_box = QWidget()
        accent_box.setFixedWidth(ACCENT_BOX_W)
        right = QVBoxLayout(accent_box)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        spec = self._accent_spec
        start_hue = DEFAULT_ACCENT_HUE if spec is None else (hue_of(spec) if isinstance(spec, str) else spec)
        self._hue_slot = QWidget(accent_box)
        self._hue_slot.setFixedHeight(30)
        self._hue_slot.installEventFilter(self)
        right.addWidget(self._hue_slot)

        self.hue_slider = HueSlider(hue=start_hue, theme=self._theme, parent=card)
        self.hue_slider.setAccessibleName(t("gen_accent_title"))
        self.hue_slider.hueChanged.connect(lambda h: self._accent_moved(h, False))
        self.hue_slider.hueCommitted.connect(lambda h: self._accent_moved(h, True))
        self.hue_slider.raise_()
        card.installEventFilter(self)

        self.accent_edit = QLineEdit()
        self.accent_edit.setObjectName("AccentField")
        self.accent_edit.setFixedWidth(112)
        self.accent_edit.setMaxLength(40)
        self.accent_edit.setPlaceholderText("#RRGGBB")
        self.accent_edit.setAccessibleName(t("gen_accent_title"))
        self.accent_edit.textEdited.connect(self._accent_text_edited)
        self.accent_edit.editingFinished.connect(self._accent_text_committed)
        # Amostra da cor APLICADA dentro do campo (mostra o ajuste de legibilidade, se houver)
        self._accent_swatch = self.accent_edit.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        self.btn_accent_reset = QPushButton()
        self._apply_accent_reset_texts()
        self.btn_accent_reset.setProperty("class", "Chip")
        self.btn_accent_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_accent_reset.clicked.connect(self._reset_accent)
        # Campo sozinho à direita; com cor personalizada, desliza e o "Redefinir" sai de trás dele (par centralizado)
        self.accent_entry = AccentEntryRow(self.accent_edit, self.btn_accent_reset, inset=int(SLIDER_MARGIN),
                                           shown=spec is not None)
        right.addWidget(self.accent_entry)
        row_acc.addWidget(accent_box)
        self._accent_invalid = False
        self._style_accent_field()
        self._sync_accent_field()
        c_layout.addLayout(row_acc)

        sep_acc = QFrame()
        sep_acc.setFrameShape(QFrame.Shape.HLine)
        sep_acc.setProperty("class", "HubDivider")
        c_layout.addWidget(sep_acc)

        # Seletor de Idioma
        row4 = QHBoxLayout()
        self.t4 = QLabel(t("gen_language_title"))
        self.t4.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        row4.addWidget(self.t4, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._lang_group = ChipGroup([("pt", "Português"), ("en", "English")], self._set_language, self._theme,
                                     selected=self._current_lang)
        self._lang_chips = self._lang_group.buttons
        row4.addWidget(self._lang_group, alignment=Qt.AlignmentFlag.AlignVCenter)
        c_layout.addLayout(row4)

        self.content_layout.addWidget(card)

        # Card de Atualizações do Sistema
        self._pending_update_info: Optional[UpdateInfo] = None
        card_update = QFrame()
        card_update.setProperty("class", "HubCard")
        up_layout = QVBoxLayout(card_update)
        up_layout.setContentsMargins(*CARD_MARGINS)
        up_layout.setSpacing(10)

        row_up = QHBoxLayout()
        info_up = QVBoxLayout()
        info_up.setSpacing(2)
        self.t_update = QLabel(t("gen_updates_title"))
        self.t_update.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d_update = QLabel(t("gen_updates_installed").format(version=__version__))
        self.d_update.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_up.addWidget(self.t_update)
        info_up.addWidget(self.d_update)
        row_up.addLayout(info_up, stretch=1)

        self.btn_check_update = QPushButton(t("gen_updates_btn_check"))
        self.btn_check_update.setProperty("class", "Chip")
        self.btn_check_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_update.clicked.connect(self._check_for_updates)
        row_up.addWidget(self.btn_check_update)

        self.btn_apply_update = QPushButton(t("gen_updates_btn_download"))
        self.btn_apply_update.setProperty("class", "Chip")
        self.btn_apply_update.setProperty("selected", "true")
        self.btn_apply_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_update.setVisible(False)
        self.btn_apply_update.clicked.connect(self._apply_update)
        row_up.addWidget(self.btn_apply_update)

        up_layout.addLayout(row_up)

        # Verificação automática (1x por dia, ao abrir o app): o usuário decide se o app fala com o GitHub sozinho
        sep_auto = QFrame()
        sep_auto.setFrameShape(QFrame.Shape.HLine)
        sep_auto.setProperty("class", "HubDivider")
        up_layout.addWidget(sep_auto)

        row_auto = QHBoxLayout()
        info_auto = QVBoxLayout()
        info_auto.setSpacing(2)
        self.t_auto_update = QLabel(t("gen_updates_auto_title"))
        self.t_auto_update.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.d_auto_update = QLabel(t("gen_updates_auto_sub"))
        self.d_auto_update.setWordWrap(True)
        self.d_auto_update.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        info_auto.addWidget(self.t_auto_update)
        info_auto.addWidget(self.d_auto_update)
        row_auto.addLayout(info_auto, stretch=1)
        self.sw_auto_update = PillSwitch(checked=config_manager.is_auto_update_check_enabled(), theme=self._theme)
        self.sw_auto_update.toggled.connect(config_manager.set_auto_update_check_enabled)
        row_auto.addWidget(self.sw_auto_update)
        up_layout.addLayout(row_auto)

        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setStyleSheet(f"color: {self._theme.mute}; font-size: 12px;")
        self.lbl_update_status.setVisible(False)
        up_layout.addWidget(self.lbl_update_status)

        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setTextVisible(False)
        self.update_progress.setFixedHeight(6)
        self.update_progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {self._theme.line};
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {self._theme.accent};
                border-radius: 3px;
            }}
        """)
        self.update_progress.setVisible(False)
        up_layout.addWidget(self.update_progress)

        self.content_layout.addWidget(card_update)
        self.content_layout.addStretch()

    def _check_for_updates(self):
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText(t("gen_updates_checking"))
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(t("gen_updates_checking"))
        self._pending_update_info = None

        updater_service.check_for_updates(
            on_update_found=self._on_update_found,
            on_up_to_date=self._on_up_to_date,
            on_error=self._on_update_error,
        )

    def _on_update_found(self, info: UpdateInfo):
        self._pending_update_info = info
        self.btn_check_update.setVisible(False)
        self.btn_apply_update.setVisible(True)
        self.btn_apply_update.setEnabled(True)
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(t("gen_updates_found").format(version=info.latest_version))

    def start_update(self, info: UpdateInfo):
        """O usuário aceitou o aviso de versão nova (janela principal): segue o mesmo caminho do botão Atualizar."""
        self._on_update_found(info)
        self._apply_update()

    def _on_up_to_date(self, current_ver: str):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(t("gen_updates_btn_check"))
        self.btn_apply_update.setVisible(False)
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(t("gen_updates_up_to_date"))

    def _on_update_error(self, err_msg: str):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(t("gen_updates_btn_check"))
        self.lbl_update_status.setVisible(True)
        self.lbl_update_status.setText(f"{t('gen_updates_err')} ({err_msg})")

    def _apply_update(self):
        info = self._pending_update_info
        if not info:
            return
        # Portátil (ou release sem instalador): o app não se sobrescreve; o download é pela página da release
        if not info.download_url or not is_installed_build():
            QDesktopServices.openUrl(QUrl(info.page_url))
            self.lbl_update_status.setText(t("gen_updates_manual"))
            return
        self.btn_apply_update.setEnabled(False)
        self.update_progress.setVisible(True)
        self.update_progress.setValue(0)
        self.lbl_update_status.setText(t("gen_updates_downloading").format(percent=0))

        updater_service.start_download(
            download_url=info.download_url,
            on_progress=self._on_download_progress,
            on_finished=self._on_download_finished,
            on_error=self._on_download_error,
            expected_sha256=info.sha256,
        )

    def _on_download_progress(self, percent: int):
        self.update_progress.setValue(percent)
        self.lbl_update_status.setText(t("gen_updates_downloading").format(percent=percent))

    def _on_download_finished(self, temp_path: str):
        self.lbl_update_status.setText(t("gen_updates_applying"))
        updater_service.apply_update_and_restart(temp_path)

    def _on_download_error(self, err_msg: str):
        self.update_progress.setVisible(False)
        self.btn_apply_update.setEnabled(True)
        self.lbl_update_status.setText(f"{t('gen_updates_download_err')}: {err_msg}")

    def _sync_hue_slider_geom(self):
        if not hasattr(self, "_hue_slot") or not hasattr(self, "_general_card"):
            return
        pos = self._hue_slot.mapTo(self._general_card, QPoint(0, 0))
        h = self.hue_slider.height()
        slot_h = self._hue_slot.height()
        # Mantém a base do HueSlider alinhada à base do slot; a folga da onda (24px) sobe para o vão do divisor.
        self.hue_slider.setGeometry(pos.x(), pos.y() - (h - slot_h), self._hue_slot.width(), h)
        self.hue_slider.raise_()

    def eventFilter(self, obj, event):
        if obj in (getattr(self, "_hue_slot", None), getattr(self, "_general_card", None)):
            if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
                self._sync_hue_slider_geom()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_hue_slider_geom()
        QTimer.singleShot(0, self._sync_hue_slider_geom)

    def _set_theme_mode(self, mode: str):
        self._current_pref = mode
        self._theme_group.set_selected(mode)
        if self._on_theme_change:
            self._on_theme_change(mode)

    # --- Cor de destaque ---

    def _shown_accent(self) -> str:
        """A cor de destaque em uso, como o campo de texto a mostra."""
        spec = self._accent_spec
        if spec is None:
            return (THEME_DARK if self._theme.is_dark else THEME_LIGHT).accent
        if isinstance(spec, str):
            return spec
        return derive_accent(spec, self._theme.is_dark)[0]

    def _applied_accent(self) -> str:
        """A cor que o app realmente usa no modo atual (uma cor colada pode ter sido ajustada para legibilidade)."""
        spec = self._accent_spec
        if isinstance(spec, str):
            return fit_accent(spec, self._theme.is_dark)[0]
        return self._shown_accent()

    def _update_accent_swatch(self):
        dpr = max(1.0, self.devicePixelRatioF())
        size = 14
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(self._theme.line))
        p.setBrush(QColor(self._applied_accent()))
        p.drawEllipse(1, 1, size - 2, size - 2)
        p.end()
        self._accent_swatch.setIcon(QIcon(pm))

    def _sync_accent_field(self):
        self._update_accent_swatch()
        if not self.accent_edit.hasFocus():
            self.accent_edit.setText(self._shown_accent())
            self._set_accent_invalid(False)

    def _apply_accent_reset_texts(self):
        """Rótulo curto ("Redefinir"); a dica e o nome acessível dizem o que ele redefine (criar e trocar de idioma)."""
        self.btn_accent_reset.setText(t("gen_accent_reset"))
        self.btn_accent_reset.setToolTip(t("gen_accent_reset_tip"))
        self.btn_accent_reset.setAccessibleName(t("gen_accent_reset_tip"))

    def _style_accent_field(self):
        th = self._theme
        border = warning_color(th) if self._accent_invalid else th.line
        self.accent_edit.setStyleSheet(
            f"QLineEdit#AccentField {{ background: {th.panel}; color: {th.text}; border: 1px solid {border};"
            f" border-radius: 6px; padding: 5px 8px; font-size: 12.5px; selection-background-color: {th.accent};"
            f" selection-color: {th.ink}; }}"
            f"QLineEdit#AccentField:focus {{ border: 1px solid {border if self._accent_invalid else th.accent}; }}")

    def _set_accent_invalid(self, invalid: bool):
        if invalid == self._accent_invalid:
            return
        self._accent_invalid = invalid
        self._style_accent_field()
        if invalid:
            self.d_acc.setText(t("gen_accent_invalid"))
            self.d_acc.setStyleSheet(f"color: {warning_color(self._theme)}; font-size: 12.5px;")
        else:
            self.d_acc.setText(t("gen_accent_sub"))
            self.d_acc.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")

    def _emit_accent(self, accent, committed: bool):
        self._accent_spec = accent
        # O trabalho pesado (snapshot + reaplicar o estilo, ~70 ms) roda ANTES de a animação do "Redefinir" começar:
        # se rodasse depois, congelaria os primeiros quadros do movimento (parece travado).
        if self._on_accent_change:
            self._on_accent_change(accent, committed)
        self.accent_entry.set_reset_shown(accent is not None)

    def _accent_moved(self, hue: int, committed: bool):
        self._emit_accent(hue, committed)
        self.accent_edit.clearFocus()
        self._sync_accent_field()

    def _accent_text_edited(self, _text: str):
        self._set_accent_invalid(False)

    def _accent_text_committed(self):
        text = self.accent_edit.text().strip()
        if not text or text.upper() == self._shown_accent().upper():
            self._set_accent_invalid(False)
            if not self.accent_edit.hasFocus():
                self._sync_accent_field()
            return
        color = parse_color(text)
        if color is None:
            self._set_accent_invalid(True)
            if not self.accent_edit.hasFocus():   # saiu do campo sem corrigir: volta para a cor em uso
                self._sync_accent_field()
            return
        self._set_accent_invalid(False)
        self.hue_slider.set_hue(hue_of(color))
        self._emit_accent(color, True)
        self.accent_edit.setText(color)
        self._update_accent_swatch()

    def _reset_accent(self):
        self.hue_slider.set_hue(DEFAULT_ACCENT_HUE)
        self._emit_accent(None, True)
        self.accent_edit.clearFocus()
        self._sync_accent_field()

    def _set_language(self, lang_code: str):
        if lang_code == self._current_lang:
            return
        self._current_lang = lang_code
        self._lang_group.set_selected(lang_code)
        from app.core.i18n import i18n
        i18n.set_language(lang_code)
        if self._on_language_change:
            self._on_language_change(lang_code)

    def retranslate_ui(self):
        self.set_header(t("gen_title"), "")
        if hasattr(self, "t1"):
            self.t1.setText(t("gen_startup_title"))
        if hasattr(self, "d1"):
            self.d1.setText(t("gen_startup_sub"))
        if hasattr(self, "t_min"):
            self.t_min.setText(t("gen_start_minimized_title"))
        if hasattr(self, "d_min"):
            self.d_min.setText(t("gen_start_minimized_sub"))
        if hasattr(self, "t2"):
            self.t2.setText(t("gen_tray_title"))
        if hasattr(self, "d2"):
            self.d2.setText(t("gen_tray_sub"))
        if hasattr(self, "t3"):
            self.t3.setText(t("gen_theme_title"))
        if hasattr(self, "t_acc"):
            self.t_acc.setText(t("gen_accent_title"))
            self.d_acc.setText(t("gen_accent_invalid") if self._accent_invalid else t("gen_accent_sub"))
            self.accent_edit.setAccessibleName(t("gen_accent_title"))
            self._apply_accent_reset_texts()
            self.accent_entry.relayout()   # largura do botão muda com o idioma
            self.hue_slider.setAccessibleName(t("gen_accent_title"))
        if hasattr(self, "t4"):
            self.t4.setText(t("gen_language_title"))
        if hasattr(self, "_theme_modes"):
            for mode_key, i18n_key in self._theme_modes:
                self._theme_group.set_label(mode_key, t(i18n_key))
        if hasattr(self, "_lang_chips"):
            from app.core.i18n import i18n
            self._current_lang = i18n.current_language
            self._lang_group.set_selected(self._current_lang, animated=False)
        if hasattr(self, "t_update"):
            self.t_update.setText(t("gen_updates_title"))
        if hasattr(self, "d_update"):
            self.d_update.setText(t("gen_updates_installed").format(version=__version__))
        if hasattr(self, "btn_check_update") and self.btn_check_update.isEnabled():
            self.btn_check_update.setText(t("gen_updates_btn_check"))
        if hasattr(self, "btn_apply_update"):
            self.btn_apply_update.setText(t("gen_updates_btn_download"))
        if hasattr(self, "t_auto_update"):
            self.t_auto_update.setText(t("gen_updates_auto_title"))
            self.d_auto_update.setText(t("gen_updates_auto_sub"))

    def set_theme(self, theme: HubTheme):
        super().set_theme(theme)
        if hasattr(self, "sw_auto_update"):
            self.sw_auto_update.set_theme(theme)
            self.d_auto_update.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        if hasattr(self, "s1"):
            self.s1.set_theme(theme)
        if hasattr(self, "s_min"):
            self.s_min.set_theme(theme)
        if hasattr(self, "s2"):
            self.s2.set_theme(theme)
        if hasattr(self, "d_min"):
            self.d_min.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        if hasattr(self, "d_acc"):
            tone = warning_color(theme) if self._accent_invalid else theme.mute
            self.d_acc.setStyleSheet(f"color: {tone}; font-size: 12.5px;")
        if hasattr(self, "hue_slider"):
            self.hue_slider.set_theme(theme)
        if hasattr(self, "accent_edit"):
            self._style_accent_field()
            self._sync_accent_field()
        if hasattr(self, "btn_accent_reset"):
            self.btn_accent_reset.style().unpolish(self.btn_accent_reset)
            self.btn_accent_reset.style().polish(self.btn_accent_reset)
        if hasattr(self, "d_update"):
            self.d_update.setStyleSheet(f"color: {theme.mute}; font-size: 12.5px;")
        if hasattr(self, "lbl_update_status"):
            self.lbl_update_status.setStyleSheet(f"color: {theme.mute}; font-size: 12px;")
        if hasattr(self, "update_progress"):
            self.update_progress.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {theme.line};
                    border-radius: 3px;
                    border: none;
                }}
                QProgressBar::chunk {{
                    background-color: {theme.accent};
                    border-radius: 3px;
                }}
            """)
        self._theme_group.set_theme(theme)
        self._lang_group.set_theme(theme)
