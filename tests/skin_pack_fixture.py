"""
Pacote de skin sintético para os testes: uma pasta temporária com `skin.json`, uma arte e as letras, no formato que o app lê.
Assim os testes não dependem de nenhuma arte real (que é distribuída à parte e fica fora do repositório).

    with fake_skin_pack("minha-skin") as pack:   # as raízes de pacotes passam a ser só a pasta temporária
        ...
"""

import json
import os
import tempfile
from contextlib import contextmanager
from unittest import mock

from PySide6.QtGui import QColor, QImage

from app.core import skin_packs
from app.core.preview_registry import SKIN_REGISTRY

LETTERS = "abcdefghijklmnopqrstuvwxyz"


def pack_data(**overrides) -> dict:
    data = {
        "widget": "timer",
        "name": "Fake",
        "subtitle": {"pt": "Arte de teste", "en": "Test art"},
        "art": {"file": "arte.png", "units": 1624, "origin": [-154, -154], "size": [1932, 1927.6], "tip_overshoot": 154},
        "label": {"letters_dir": "letters", "letters_meta": "letters.json", "cy": 254.65, "unit": 0.45402,
                  "max_width": 724.2},
        "digits": {"cy": 809.8, "font_px": 208.66, "fonts": ["Segoe UI"]},
        "buttons": {"cy": 1121.63, "diameter": 234, "spacing": 381, "ring": 10.6, "shadow": [9.7, 11.6]},
        "colors": {"ink": "#3a0e10", "button": "#c08080", "digits": "#ffeaea", "highlight": "#f6ee3a"},
    }
    data.update(overrides)
    return data


def write_pack(root: str, pack_id: str = "fake", data: dict | None = None, with_art: bool = True,
               with_letters: bool = True) -> str:
    folder = os.path.join(root, pack_id)
    os.makedirs(os.path.join(folder, "letters"), exist_ok=True)
    with open(os.path.join(folder, "skin.json"), "w", encoding="utf-8") as fh:
        json.dump(data if data is not None else pack_data(), fh)
    if with_art:
        art = QImage(40, 40, QImage.Format.Format_ARGB32)
        art.fill(QColor("#aa1122"))
        art.save(os.path.join(folder, "arte.png"))
    if with_letters:
        meta = {}
        for ch in LETTERS:
            for name in (f"lower_{ch}", f"upper_initial_{ch.upper()}"):
                img = QImage(30, 40, QImage.Format.Format_ARGB32)
                img.fill(QColor("#ffffff"))
                img.save(os.path.join(folder, "letters", name + ".png"))
                meta[name] = {"w": 30, "h": 40, "top": 0, "bot": 39, "base": 36}
        with open(os.path.join(folder, "letters.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
    return folder


@contextmanager
def fake_skin_pack(pack_id: str = "fake", data: dict | None = None):
    """Cria o pacote numa pasta temporária, faz o app procurar pacotes só ali e refaz o registro de skins do Timer."""
    from app.widgets.timer.skins import init_timer_skin_specs

    with tempfile.TemporaryDirectory() as root:
        write_pack(root, pack_id, data)
        saved = SKIN_REGISTRY.pop("timer", None)
        with mock.patch.object(skin_packs, "pack_roots", return_value=[root]):
            init_timer_skin_specs()
            try:
                yield skin_packs.discover("timer")[0]
            finally:
                SKIN_REGISTRY.pop("timer", None)
                if saved is not None:
                    SKIN_REGISTRY["timer"] = saved
