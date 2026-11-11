"""
Temas que vêm com o app (assets/themes/<container>/<tema>/).

Na abertura, cada tema embutido é COPIADO para a pasta de temas do usuário (%LOCALAPPDATA%/Aimedget/themes/...) se
ainda não estiver lá. A partir daí ele é um tema como qualquer outro: aparece na galeria, pode ser editado,
exportado ou apagado. Assim a galeria, o carregamento e a exportação não precisam saber que existem temas embutidos.

Cada tema é semeado UMA vez (fica registrado no config): se o usuário apagar, ele não volta sozinho. Nunca
sobrescreve uma pasta que já existe (o usuário pode ter editado o tema).
"""

import logging
import os
import shutil

from app.core.config_manager import config_manager
from app.core.paths import ASSETS_DIR

logger = logging.getLogger(__name__)

BUNDLED_THEMES_DIR = os.path.join(ASSETS_DIR, "themes")


def seed_bundled_themes(source_dir: str = BUNDLED_THEMES_DIR, user_themes_dir: str | None = None) -> list[str]:
    """Copia os temas embutidos que o usuário ainda não recebeu. Devolve '<container>/<tema>' de cada cópia feita."""
    user_themes_dir = user_themes_dir or os.path.join(config_manager.config_dir, "themes")
    copied: list[str] = []
    try:
        containers = sorted(os.listdir(source_dir))
    except OSError:
        return copied   # build sem temas embutidos
    for container in containers:
        container_src = os.path.join(source_dir, container)
        if not os.path.isdir(container_src):
            continue
        for theme_id in sorted(os.listdir(container_src)):
            src = os.path.join(container_src, theme_id)
            if not os.path.isfile(os.path.join(src, "theme.json")):
                continue
            if config_manager.was_theme_seeded(container, theme_id):
                continue   # já entregue uma vez: se o usuário apagou, a escolha é dele
            dest = os.path.join(user_themes_dir, container, theme_id)
            try:
                if not os.path.exists(dest):
                    shutil.copytree(src, dest)
                    copied.append(f"{container}/{theme_id}")
                config_manager.mark_theme_seeded(container, theme_id)
            except OSError as exc:   # disco cheio, permissão: tenta de novo na próxima abertura
                logger.warning("Não foi possível instalar o tema embutido %s/%s: %s", container, theme_id, exc)
    return copied
