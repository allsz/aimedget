"""
Validação "estrita" de um tema: lê a pasta com o MESMO código que o flyout usa (theme_from_dict) e devolve
um relatório com o que foi aplicado e o que foi ignorado (e por quê).

Não há regra de validação aqui: as regras vivem em theme_art / theme_loader, que reportam cada problema por
`report_issue`; este módulo só liga a coleta (`collect_issues`) e organiza o resultado. Serve ao validador de
linha de comando (tools/validate_theme.py) e, depois, à verificação antes de importar um .aimskin.

Precisa de uma QGuiApplication (carregar imagens usa QPixmap); o CLI cria uma.
"""

import json
import os
from dataclasses import dataclass, field, fields

from app.core.theme_art import collect_issues
from app.core.theme_loader import MAX_NAME_LEN

CONTAINERS = ("keylock", "mixer")


@dataclass
class ThemeReport:
    container: str
    folder: str
    name: str = ""
    errors: list[str] = field(default_factory=list)    # impede de usar o tema (arquivo ausente, JSON quebrado)
    issues: list[str] = field(default_factory=list)    # valores ignorados: o tema funciona, mas não como escrito
    applied: list[str] = field(default_factory=list)   # tokens que realmente valeram
    sticker_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors and not self.issues

    @property
    def usable(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"container": self.container, "folder": self.folder, "name": self.name, "ok": self.ok,
                "errors": self.errors, "issues": self.issues, "applied": self.applied,
                "sticker_count": self.sticker_count}


def _container_parts(container: str):
    """(theme_from_dict, DEFAULT_THEME) do container. Importa sob demanda para não criar ciclos."""
    if container == "keylock":
        from app.widgets.keylock_osd import theme as module
    elif container == "mixer":
        from app.widgets.volume_mixer import theme as module
    else:
        raise ValueError(f"container desconhecido: {container!r} (use {' ou '.join(CONTAINERS)})")
    return module.theme_from_dict, module.DEFAULT_THEME


def validate_theme_folder(folder: str, container: str) -> ThemeReport:
    """Valida UMA pasta de tema (com theme.json) de um container."""
    report = ThemeReport(container=container, folder=folder)
    theme_from_dict, default = _container_parts(container)

    theme_file = os.path.join(folder, "theme.json")
    if not os.path.isfile(theme_file):
        report.errors.append(f"não achei o arquivo theme.json em {folder}")
        return report
    try:
        with open(theme_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except UnicodeDecodeError:
        report.errors.append("theme.json precisa ser salvo em UTF-8")
        return report
    except ValueError as exc:
        report.errors.append(f"theme.json não é um JSON válido ({exc}); confira vírgulas e aspas")
        return report
    except OSError as exc:
        report.errors.append(f"não foi possível ler theme.json ({exc})")
        return report
    if not isinstance(data, dict):
        report.errors.append("theme.json precisa ser um objeto { ... } no nível de cima")
        return report

    name = data.get("name")
    if "name" in data and not (isinstance(name, str) and name.strip()):
        report.issues.append("'name' precisa ser um texto não vazio (será usado o nome da pasta)")
    elif isinstance(name, str):
        report.name = name.strip()[:MAX_NAME_LEN]
        if len(name.strip()) > MAX_NAME_LEN:
            report.issues.append(f"'name' passa de {MAX_NAME_LEN} letras e será cortado")

    with collect_issues() as issues:
        theme = theme_from_dict(data, folder)
    report.issues.extend(issues)

    for f in fields(default):
        if getattr(theme, f.name) != getattr(default, f.name):
            report.applied.append(f.name)
    report.sticker_count = len(getattr(theme, "stickers", ()))
    return report


def detect_container(folder: str) -> str | None:
    """Pelo nome da pasta de cima (themes/<container>/<tema>) ou da própria pasta (themes/<container>)."""
    for candidate in (os.path.basename(os.path.dirname(os.path.abspath(folder))),
                      os.path.basename(os.path.abspath(folder))):
        if candidate in CONTAINERS:
            return candidate
    return None


def validate_path(folder: str, container: str | None = None) -> list[ThemeReport]:
    """
    Valida o que houver em `folder`: um tema de um container (informe `container` ou deixe deduzir pelo
    nome das pastas) ou um pacote multi-alvo com as subpastas `keylock/` e/ou `mixer/`.
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"a pasta não existe: {folder}")

    if container is None:
        targets = [c for c in CONTAINERS if os.path.isfile(os.path.join(folder, c, "theme.json"))]
        if targets and not os.path.isfile(os.path.join(folder, "theme.json")):
            return [validate_theme_folder(os.path.join(folder, c), c) for c in targets]
        container = detect_container(folder)
        if container is None:
            raise ValueError("não consegui descobrir de qual flyout é este tema: use --container keylock "
                             "ou --container mixer (ou coloque as pastas keylock/ e mixer/ dentro do pacote)")
    return [validate_theme_folder(folder, container)]
