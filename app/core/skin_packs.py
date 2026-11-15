"""
Pacotes de skin: skins com arte própria que vivem em PASTAS, fora do código, e só aparecem se a pasta existir.

Cada pacote é uma pasta com um `skin.json` e a arte ao lado, em qualquer destas raízes (as duas são lidas):

    <app>/assets/skins/<id>/                 (fica de fora da release, a não ser que o build peça)
    %LOCALAPPDATA%/Aimedget/skins/<id>/      (onde um amigo coloca o pacote que recebeu)

O `<id>` é o nome da pasta (minúsculas, números, `-` e `_`). Um pacote só é reconhecido se o `skin.json` for um JSON válido, disser
para qual widget é (`"widget": "timer"`) e apontar para uma arte que existe. Pacote quebrado é ignorado com um aviso no log:
nunca impede o app de abrir. O significado do resto do `skin.json` é de quem desenha a skin do widget (ver
app/widgets/timer/skins/art_skin.py para o do Timer).
"""

import json
import logging
import os
import re
from dataclasses import dataclass

from app.core.paths import ASSETS_DIR, get_app_data_dir

logger = logging.getLogger(__name__)

PACK_FILE = "skin.json"
MAX_NAME_LEN = 40
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
RESERVED_IDS = frozenset({"windows", "default", "custom", "app"})   # ids das skins que já vêm com o app


def pack_roots() -> list[str]:
    return [os.path.join(ASSETS_DIR, "skins"), os.path.join(get_app_data_dir(), "skins")]


@dataclass(frozen=True)
class SkinPack:
    id: str
    folder: str
    widget: str
    name: str
    subtitle: dict[str, str]   # idioma -> texto
    data: dict                 # o skin.json inteiro

    def path(self, *parts: str) -> str:
        return os.path.join(self.folder, *parts)

    def texts(self, language: str) -> tuple[str, str]:
        """(título, subtítulo) no idioma pedido; cai no inglês e depois em qualquer um que o pacote tenha."""
        sub = self.subtitle.get(language) or self.subtitle.get("en") or next(iter(self.subtitle.values()), "")
        return self.name, sub


def _subtitle(raw) -> dict[str, str]:
    if isinstance(raw, str):
        return {"en": raw}
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, str)}
    return {}


def _read(folder: str, widget: str, reserved: frozenset[str]) -> SkinPack | None:
    pack_id = os.path.basename(folder)
    if not _ID_RE.match(pack_id) or pack_id in reserved:
        return None
    file = os.path.join(folder, PACK_FILE)
    if not os.path.isfile(file):
        return None
    try:
        with open(file, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("Pacote de skin %r ignorado: %s não pôde ser lido (%s)", pack_id, PACK_FILE, exc)
        return None
    if not isinstance(data, dict) or data.get("widget") != widget:
        return None
    art = data.get("art")
    art_file = art.get("file") if isinstance(art, dict) else None
    if not isinstance(art_file, str) or os.path.isabs(art_file) or ".." in art_file.replace("\\", "/").split("/"):
        logger.warning("Pacote de skin %r ignorado: falta 'art.file' (a arte, dentro da pasta do pacote)", pack_id)
        return None
    if not os.path.isfile(os.path.join(folder, art_file)):
        logger.info("Pacote de skin %r ignorado: a arte %r não está na pasta", pack_id, art_file)
        return None
    name = data.get("name")
    name = name.strip()[:MAX_NAME_LEN] if isinstance(name, str) and name.strip() else pack_id
    return SkinPack(id=pack_id, folder=folder, widget=widget, name=name, subtitle=_subtitle(data.get("subtitle")),
                    data=data)


def discover(widget: str, roots: list[str] | None = None, reserved: frozenset[str] = RESERVED_IDS) -> list[SkinPack]:
    """Os pacotes de skin de `widget` que estão em disco agora, em ordem de id. Se dois têm o mesmo id, vale o da primeira raiz."""
    found: dict[str, SkinPack] = {}
    for root in roots if roots is not None else pack_roots():
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            pack = _read(os.path.join(root, entry), widget, reserved)
            if pack is not None and pack.id not in found:
                found[pack.id] = pack
    return [found[k] for k in sorted(found)]
