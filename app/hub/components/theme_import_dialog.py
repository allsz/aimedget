"""
Diálogo de verificação antes de importar um tema (.aimskin): mostra o que será aplicado e o que será ignorado
(e por quê), deixa escolher um ou ambos os flyouts e pede confirmação. Nada é instalado aqui: o diálogo só
devolve a escolha (`chosen_containers`, `mode`); quem instala é o chamador.

Substituir é o padrão quando já existe um tema com o mesmo nome; "Instalar como cópia" só vale depois de o
usuário confirmar de forma explícita.

Hierarquia: nome do tema -> onde instalar (uma lista; cada linha carrega o seu aviso) -> ação. Os nomes técnicos dos
ajustes ficam em "Ver detalhes", fechado por padrão.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from app.core.i18n import t
from app.core.theme_package import COPY, REPLACE, PackageReport, TargetReport
from app.hub.theme import HubTheme

TARGET_KEYS = {"keylock": "theme_import_target_keylock", "mixer": "theme_import_target_mixer"}

CONTENT_WIDTH = 500
DETAILS_MAX_HEIGHT = 200
ROW_INDENT = 26   # alinha o texto com o rótulo da caixa de seleção

# Nome técnico de cada ajuste do tema -> categoria que o usuário entende (o que não estiver aqui é cor)
_CATEGORY_OF = {
    "radius": "corners", "button_radius": "corners",
    "scale": "size", "auto_scale": "size", "size": "size",
    "shadow": "shadow", "background": "background",
    "indicator": "layout", "show_icon": "layout", "label_align": "layout", "label_size": "layout",
    "label_case": "layout",
}
_CATEGORY_ORDER = ("colors", "corners", "size", "shadow", "background", "layout")


def _count(key: str, n: int) -> str:
    """Texto no singular (chave com sufixo _one) ou no plural, sem o "(s)" de "figurinha(s)"."""
    return t(f"{key}_one", n=n) if n == 1 else t(key, n=n)


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"• {line}" for line in lines)


def friendly_summary(applied: list[str], sticker_count: int) -> str:
    """O que o tema muda, em palavras do usuário: "Cores, cantos, sombra, fundo e 7 figurinha(s)"."""
    found = {_CATEGORY_OF.get(key, "colors") for key in applied if key != "stickers"}
    parts = [t(f"theme_import_cat_{cat}") for cat in _CATEGORY_ORDER if cat in found]
    if sticker_count:
        parts.append(_count("theme_import_art", sticker_count))
    if not parts:
        return t("theme_import_nothing")
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + t("theme_import_and") + parts[-1]
    return text[0].upper() + text[1:]


def warning_color(theme: HubTheme) -> str:
    """Tom de aviso próprio (o destaque do app é só para ação e seleção). Contraste >= 4,5:1 sobre o painel."""
    return "#F0906E" if theme.is_dark else "#B0431F"


class ThemeImportDialog(QDialog):
    def __init__(self, report: PackageReport, theme: HubTheme, parent: QWidget | None = None):
        super().__init__(parent)
        self._report = report
        self._theme = theme
        self.mode = REPLACE
        self._checks: dict[str, QCheckBox] = {}
        self.setWindowTitle(t("theme_import_title"))
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.bg}; }} QLabel {{ color: {theme.body}; }} "
            f"QCheckBox {{ color: {theme.text}; font-weight: 600; font-size: 13.5px; spacing: 8px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(16)

        # 1. O que está sendo importado
        head = QVBoxLayout()
        head.setSpacing(4)
        self.heading = QLabel(report.name)
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {theme.text};")
        head.addWidget(self.heading)
        head.addWidget(self._muted(t("theme_import_choose")))
        root.addLayout(head)

        # 2. Onde instalar: uma lista só (linhas separadas por filete), cada linha leva o seu próprio aviso
        group = QFrame()
        group.setObjectName("targets")
        group.setStyleSheet(f"QFrame#targets {{ background: {theme.panel}; border: 1px solid {theme.line}; "
                            f"border-radius: 10px; }}")
        group_l = QVBoxLayout(group)
        group_l.setContentsMargins(0, 0, 0, 0)
        group_l.setSpacing(0)
        for i, target in enumerate(report.targets):
            if i:
                rule = QFrame()
                rule.setFixedHeight(1)
                rule.setStyleSheet(f"background: {theme.line}; border: none;")
                group_l.addWidget(rule)
            group_l.addWidget(self._target_row(target))
        root.addWidget(group)

        # 3. Resumo do que fica de fora + "Ver detalhes" (nomes técnicos dos ajustes, itens ignorados, arquivos)
        info = QHBoxLayout()
        info.setSpacing(12)
        if report.ignored_files:
            info.addWidget(self._muted(_count("theme_import_files_summary", len(report.ignored_files))), 1)
        else:
            info.addStretch()
        self.btn_details = QPushButton(t("theme_import_details_show"))
        self.btn_details.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_details.setFlat(True)
        self.btn_details.setStyleSheet(
            f"QPushButton {{ color: {theme.mute}; border: none; padding: 2px; font-size: 12.5px; }}"
            f"QPushButton:hover {{ color: {theme.text}; text-decoration: underline; }}"
            f"QPushButton:focus {{ color: {theme.text}; text-decoration: underline; }}")
        self.btn_details.clicked.connect(self._toggle_details)
        info.addWidget(self.btn_details)
        root.addLayout(info)
        self.details = self._details_area()
        root.addWidget(self.details)

        # 4. Ação: o botão principal diz o que vai acontecer
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        self.btn_cancel = self._button(t("theme_import_cancel"), self.reject)
        buttons.addWidget(self.btn_cancel)
        if report.has_collision:
            self.btn_copy = self._button(t("theme_import_copy"), self._on_copy)
            buttons.addWidget(self.btn_copy)
        self.btn_ok = self._button(
            t("theme_import_replace") if report.has_collision else t("theme_import_install"), self._on_ok, primary=True)
        self.btn_ok.setDefault(True)
        buttons.addWidget(self.btn_ok)
        root.addLayout(buttons)

        self._update_buttons()
        self._fit()

    # --- Construção ---

    def _muted(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {self._theme.mute}; font-size: 12.5px;")
        return label

    def _button(self, text: str, slot, primary: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "Chip")
        if primary:
            btn.setProperty("selected", "true")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _target_row(self, target: TargetReport) -> QWidget:
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(16, 13, 16, 13)
        lay.setSpacing(4)

        check = QCheckBox(t(TARGET_KEYS[target.container]).replace("&", "&&"))   # "&" sozinho vira atalho de teclado
        check.setChecked(target.installable)   # os dois vêm marcados; o usuário desmarca o que não quer
        check.setEnabled(target.installable)
        check.toggled.connect(lambda _c: self._update_buttons())
        self._checks[target.container] = check
        lay.addWidget(check)

        rep = target.report
        if not target.installable:
            lay.addWidget(self._line(t("theme_import_blocked", why=" ".join(rep.errors)), warning_color(self._theme),
                                     indent=ROW_INDENT))
            return row

        lay.addWidget(self._line(friendly_summary(list(rep.applied), rep.sticker_count), self._theme.body,
                                 indent=ROW_INDENT))
        if target.exists:
            lay.addWidget(self._line(t("theme_import_row_exists"), warning_color(self._theme), bold=True,
                                     indent=ROW_INDENT))
        if rep.issues:
            lay.addWidget(self._line(_count("theme_import_row_ignored", len(rep.issues)), self._theme.mute,
                                     indent=ROW_INDENT))
        return row

    def _details_area(self) -> QScrollArea:
        """Versão técnica do que a lista resume: tudo o que o tema aplica, ignora e deixa de fora."""
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(6)
        for target in self._report.targets:
            rep = target.report
            lay.addWidget(self._line(t(TARGET_KEYS[target.container]), self._theme.text, bold=True))
            if not target.installable:
                lay.addWidget(self._line(t("theme_import_blocked", why=" ".join(rep.errors)), self._theme.mute))
                continue
            items = ", ".join(rep.applied) if rep.applied else t("theme_import_nothing")
            if rep.sticker_count:
                items += f" — {_count('theme_import_art', rep.sticker_count)}"
            lay.addWidget(self._line(t("theme_import_applies", items=items), self._theme.body))
            if rep.issues:
                lay.addWidget(self._line(t("theme_import_ignored_head"), self._theme.text, bold=True))
                lay.addWidget(self._line(_bullets(rep.issues), self._theme.mute))
            else:
                lay.addWidget(self._line(t("theme_import_all_ok"), self._theme.mute))
        if self._report.ignored_files:
            lay.addWidget(self._line(t("theme_import_files_head"), self._theme.text, bold=True))
            lay.addWidget(self._line(_bullets([f"{name}: {why}" for name, why in self._report.ignored_files]),
                                     self._theme.mute))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        scroll.setMaximumHeight(DETAILS_MAX_HEIGHT)
        scroll.setStyleSheet("QScrollArea { background: transparent; } "
                             "QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setVisible(False)
        return scroll

    def _line(self, text: str, color: str, bold: bool = False, indent: int = 0) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(f"color: {color}; font-size: 12.5px; padding-left: {indent}px;"
                            f"{' font-weight: 600;' if bold else ''}")
        return label

    def _fit(self):
        """Largura fixa; a altura acompanha o conteúdo (sem espaço morto, e encolhe ao fechar os detalhes)."""
        self.setFixedSize(CONTENT_WIDTH, self.layout().totalHeightForWidth(CONTENT_WIDTH))

    def _toggle_details(self):
        show = not self.details.isVisible()
        self.details.setVisible(show)
        self.btn_details.setText(t("theme_import_details_hide" if show else "theme_import_details_show"))
        self._fit()

    # --- Escolha ---

    @property
    def chosen_containers(self) -> list[str]:
        return [c for c, box in self._checks.items() if box.isChecked() and box.isEnabled()]

    def _update_buttons(self):
        chosen = bool(self.chosen_containers)
        self.btn_ok.setEnabled(chosen)
        if hasattr(self, "btn_copy"):
            self.btn_copy.setEnabled(chosen)

    def _on_ok(self):
        self.mode = REPLACE
        self.accept()

    def _on_copy(self):
        answer = QMessageBox.question(
            self, t("theme_import_title"), t("theme_import_copy_confirm", name=self._report.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.mode = COPY
            self.accept()
