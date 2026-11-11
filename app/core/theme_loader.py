"""
Carregamento de temas de container (flyout do Caps, Mixer, ...), compartilhado.

Cada container tem uma pasta em  %LOCALAPPDATA%/Aimedget/themes/<container>/  com:

    <container>/
      theme.json              <- tema solto na raiz (formato inicial; aparece como "Personalizado")
      lavanda/                <- um tema = uma pasta com theme.json + imagens ao lado
        theme.json
        fundo.png
        estrela.svg

O tema ativo fica na config (escolhido no Hub). Sem escolha salva, vale o `theme.json` da raiz se existir,
senão o visual padrão. Um tema quebrado nunca impede o flyout de abrir: cada valor inválido volta ao padrão.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

from PySide6.QtGui import QColor

from app.core.config_manager import config_manager
from app.core.theme_art import (
    dir_signature,
    issue_scope,
    parse_background,
    parse_card_shadow,
    parse_color,
    parse_stickers,
    report_issue,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Chaves que existem em todo container (as demais dependem do container)
COMMON_KEYS = ("name", "container", "shadow", "background", "stickers")   # `container`: só para pacotes .aimskin

DEFAULT_ID = "default"   # visual original, sem arquivos
CUSTOM_ID = "custom"     # theme.json solto na raiz da pasta do container
APP_ID = "app"           # tema embutido "Aimedget": herda a aparência do app (ver app/core/app_theme.py)
APP_NAME = "Aimedget"    # nome próprio: não é traduzido
MAX_NAME_LEN = 40


def color_field(r: int, g: int, b: int, a: int = 255):
    """Valor padrão de um campo de cor (QColor é mutável, então o dataclass exige uma fábrica)."""
    return field(default_factory=lambda: QColor(r, g, b, a))


def parse_tokens(
    data: dict,
    base_dir: str | None,
    label: str,
    color_keys: tuple[str, ...],
    radius_range: tuple[float, float] | None = None,
    scale_range: tuple[float, float] | None = None,
    extra_numbers: dict[str, tuple[float, float]] | None = None,
    render_boost: float = 1.0,
    extra_keys: tuple[str, ...] = (),
    sticker_states: bool = False,
) -> dict:
    """
    Converte o dict do JSON em {campo: valor} para `dataclasses.replace`, descartando o que for inválido
    (com aviso no log; dentro de `collect_issues()` os avisos também vão para uma lista). `base_dir` é a pasta
    do tema; sem ela, fundo e figurinhas são ignorados.
    Chaves comuns a todos os containers: cores, `radius`, `shadow`, `background`, `stickers`.
    `scale` (só se `scale_range` for dado) aumenta o container inteiro. `render_boost` é um fator extra
    (ex.: escala automática pela tela) que as figurinhas levam em conta para serem preparadas já na
    resolução necessária. `extra_keys` são chaves que o chamador trata por conta própria (ex.: `auto_scale`).
    """
    with issue_scope(label=label):
        return _parse_tokens(data, base_dir, color_keys, radius_range, scale_range, extra_numbers,
                             render_boost, extra_keys, sticker_states)


def _parse_tokens(data, base_dir, color_keys, radius_range, scale_range, extra_numbers, render_boost,
                  extra_keys, sticker_states=False) -> dict:
    changes: dict = {}
    numbers = dict(extra_numbers or {})
    if radius_range is not None:
        numbers["radius"] = radius_range
    if scale_range is not None:
        numbers["scale"] = scale_range

    known = set(color_keys) | set(numbers) | set(extra_keys) | set(COMMON_KEYS)
    for key in data:
        if key not in known:
            report_issue("chave desconhecida '%s' (ignorada); as válidas aqui são: %s", key, ", ".join(sorted(known)))

    for key in color_keys:
        if key not in data:
            continue
        color = parse_color(data[key])
        if color is None:
            report_issue("cor inválida em '%s': %r (use #rrggbb ou #aarrggbb; usando o padrão)", key, data[key])
        else:
            changes[key] = color

    def number(key: str, lo: float, hi: float):
        raw = data[key]
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            clamped = max(lo, min(hi, float(raw)))
            if clamped != float(raw):
                report_issue("'%s' fora do limite (%s; permitido de %s a %s): usando %s", key, raw, lo, hi, clamped)
            changes[key] = clamped
        else:
            report_issue("'%s' precisa ser um número, mas veio %r (usando o padrão)", key, raw)

    for key, (lo, hi) in numbers.items():
        if key in data:
            number(key, lo, hi)

    if "shadow" in data:
        shadow = parse_card_shadow(data["shadow"])
        if shadow is not None:
            changes["shadow"] = shadow

    if base_dir is not None:
        background = parse_background(data.get("background"), base_dir)
        if background is not None:
            changes["background"] = background
        stickers = parse_stickers(data.get("stickers"), base_dir, render_scale=changes.get("scale", 1.0) * render_boost,
                                  allow_state=sticker_states)
        if stickers:
            changes["stickers"] = stickers
    return changes


@dataclass(frozen=True)
class ThemeInfo:
    id: str
    name: str


class ThemeLoader(Generic[T]):
    """
    Descobre e carrega os temas de um container. `load()` é barato de chamar a cada exibição do flyout:
    só relê quando o tema escolhido ou algum arquivo dele muda. Devolve sempre o MESMO objeto enquanto
    nada mudar, então `theme is outro` serve para detectar "o tema mudou".
    """

    def __init__(self, container_id: str, default: T, parse: Callable[[dict, str], T], label: str,
                 context: Callable[[], object] | None = None, app_theme: Callable[[], T] | None = None):
        # `context` devolve algo que, quando muda, invalida o cache (ex.: a razão de escala da tela)
        self._context = context
        # `app_theme` calcula o tema embutido "Aimedget" (sem arquivos). Deve devolver o MESMO objeto enquanto a
        # aparência do app não mudar. Sem ele, o loader não oferece esse tema.
        self._app_theme = app_theme
        self.container_id = container_id
        self.default = default
        self._parse = parse
        self._label = label
        self._cache: tuple[tuple, T] | None = None
        self._preview_cache: dict[str, tuple[tuple, T]] = {}   # só para miniaturas (ver `theme_for`)

    # --- Caminhos ---

    def themes_dir(self) -> str:
        return os.path.join(config_manager.config_dir, "themes", self.container_id)

    def path(self) -> str:
        """`theme.json` solto na raiz (tema "Personalizado")."""
        return os.path.join(self.themes_dir(), "theme.json")

    def _theme_file_and_dir(self, theme_id: str) -> tuple[str, str] | None:
        if theme_id == CUSTOM_ID:
            return self.path(), self.themes_dir()
        if not theme_id or os.path.basename(theme_id) != theme_id or theme_id.startswith("."):
            return None  # nada de caminhos: o id é só o nome de uma pasta dentro de themes/<container>/
        folder = os.path.join(self.themes_dir(), theme_id)
        return os.path.join(folder, "theme.json"), folder

    def reset(self):
        self._cache = None

    # --- Descoberta ---

    @staticmethod
    def _display_name(theme_file: str, fallback: str) -> str:
        try:
            with open(theme_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("name") if isinstance(data, dict) else None
            if isinstance(name, str) and name.strip():
                return name.strip()[:MAX_NAME_LEN]
        except (OSError, ValueError):
            pass
        return fallback

    def list_themes(self) -> list[ThemeInfo]:
        """Aimedget, Windows (visual original), o tema solto da raiz (se houver) e cada subpasta com um theme.json."""
        themes = [ThemeInfo(DEFAULT_ID, "")]  # o visual original do Windows; o nome é traduzido pela interface
        if self._app_theme is not None:
            themes.insert(0, ThemeInfo(APP_ID, APP_NAME))   # o Aimedget vem primeiro
        if os.path.isfile(self.path()):
            themes.append(ThemeInfo(CUSTOM_ID, self._display_name(self.path(), "")))
        try:
            entries = sorted(os.listdir(self.themes_dir()), key=str.lower)
        except OSError:
            entries = []
        for name in entries:
            if name.startswith(".") or (name == APP_ID and self._app_theme is not None):
                continue   # uma pasta chamada "app" não pode esconder o tema embutido
            theme_file = os.path.join(self.themes_dir(), name, "theme.json")
            if os.path.isfile(theme_file):
                themes.append(ThemeInfo(name, self._display_name(theme_file, name)))
        return themes

    def active_id(self) -> str:
        """Escolha salva; sem escolha, o tema solto da raiz (comportamento anterior), senão o "Aimedget".
        Quem escolheu o Padrão na galeria tem "default" salvo e continua nele."""
        choice = config_manager.get_theme_choice(self.container_id)
        if choice:
            return choice
        if os.path.isfile(self.path()):
            return CUSTOM_ID
        return APP_ID if self._app_theme is not None else DEFAULT_ID

    def is_builtin(self, theme_id: str) -> bool:
        """Temas sem pasta (Padrão e Aimedget): não há arquivos para exportar."""
        return theme_id == DEFAULT_ID or (theme_id == APP_ID and self._app_theme is not None)

    def set_active(self, theme_id: str):
        config_manager.set_theme_choice(self.container_id, theme_id)
        self.reset()

    # --- Carregamento ---

    def load(self) -> T:
        theme_id = self.active_id()
        if theme_id == APP_ID and self._app_theme is not None:
            return self._app_theme()
        located = None if theme_id == DEFAULT_ID else self._theme_file_and_dir(theme_id)
        if located is None or not os.path.isfile(located[0]):
            if theme_id != DEFAULT_ID:
                logger.warning("Tema do %s: '%s' não encontrado; usando o padrão", self._label, theme_id)
            key = (DEFAULT_ID, ())
            if self._cache is None or self._cache[0] != key:
                self._cache = (key, self.default)
            return self._cache[1]

        theme_file, base_dir = located
        # O tema da raiz só enxerga os arquivos soltos (as subpastas são outros temas)
        signature = (theme_id, dir_signature(base_dir, recursive=(theme_id != CUSTOM_ID)),
                     self._context() if self._context else None)
        if self._cache is not None and self._cache[0] == signature:
            return self._cache[1]

        theme = self._read(theme_file, base_dir)
        self._cache = (signature, theme)
        return theme

    def _read(self, theme_file: str, base_dir: str) -> T:
        """Lê e interpreta um theme.json; qualquer falha devolve o visual padrão (nunca levanta)."""
        theme = self.default
        try:
            with open(theme_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                theme = self._parse(data, base_dir)
            else:
                with issue_scope(label=self._label):
                    report_issue("o theme.json precisa ser um objeto { ... } (%s)", theme_file)
        except (OSError, ValueError) as exc:
            with issue_scope(label=self._label):
                report_issue("não foi possível ler %s (%s); o JSON pode ter vírgula sobrando ou aspas faltando", theme_file, exc)
        return theme

    def theme_for(self, theme_id: str) -> T:
        """
        O tema `theme_id` carregado SEM mexer no tema ativo nem no cache do flyout (`load`): serve às miniaturas
        do Hub. Guarda o resultado por assinatura de arquivos, então chamar de novo é barato e devolve o mesmo
        objeto enquanto nada mudar (o PreviewCard usa a identidade do objeto para saber se deve repintar).
        """
        if theme_id == APP_ID and self._app_theme is not None:
            return self._app_theme()
        located = None if theme_id == DEFAULT_ID else self._theme_file_and_dir(theme_id)
        if located is None or not os.path.isfile(located[0]):
            return self.default
        theme_file, base_dir = located
        signature = (dir_signature(base_dir, recursive=(theme_id != CUSTOM_ID)),
                     self._context() if self._context else None)
        cached = self._preview_cache.get(theme_id)
        if cached is not None and cached[0] == signature:
            return cached[1]
        theme = self._read(theme_file, base_dir)
        self._preview_cache[theme_id] = (signature, theme)
        return theme
