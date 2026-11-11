import json
import logging
import os
from typing import Any, Optional, Tuple

from app.core.paths import get_app_data_dir
from app.core.screen_metrics import (
    get_auto_music_scale,
    get_auto_timer_size,
)

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Gerenciador centralizado de preferências e configurações persistentes (JSON).
    Salva preferências do usuário em %LOCALAPPDATA%/Aimedget/settings.json.
    Compatível com empacotamento PyInstaller e execução direta.
    """

    def __init__(self, filename: str = "settings.json"):
        self.config_dir = get_app_data_dir()
        self.config_path = os.path.join(self.config_dir, filename)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        # Padrão de fábrica: se active_widget_skins não estiver configurado, inicializa todas as skins como ativas
                        music_cfg = loaded.setdefault("music_widget", {})
                        if "active_widget_skins" not in music_cfg and "active_widget_skins" not in loaded:
                            default_skins = ["vinyl", "fullcover", "ripple", "capa_empilhada"]
                            music_cfg["active_widget_skins"] = list(default_skins)
                            loaded["active_widget_skins"] = list(default_skins)
                        return loaded
            except Exception as e:
                logger.warning("Falha ao carregar configurações de %s: %s", self.config_path, e)
        return self._default_config()

    def _default_config(self) -> dict[str, Any]:
        default_skins = ["vinyl", "fullcover", "ripple", "capa_empilhada"]
        return {
            "active_widget_skins": list(default_skins),
            "music_widget": {
                "enabled": True,
                "remember_position": False,
                "position": None,  # [x, y]
                "active_skin": "vinyl",
                "active_widget_skins": list(default_skins),
                "scale": None,  # None = detecção automática de resolução (proporcional à tela)
                "launch_mode": "auto",  # 'auto' (detecção de música) ou 'manual'
                "auto_hide_on_stop": False,  # recolher após ausência prolongada de música
                "hotkey": "Win+Alt+M",
            },
            "timer_widget": {
                "enabled": True,
                "remember_position": False,
                "position": None,  # [x, y]
                "size": None,  # None = detecção automática de resolução (proporcional à tela)
                "active_skin": "windows",
                "mode": "timer",  # 'timer' ou 'stopwatch'
                "duration": 300,  # 5 minutos padrão
                "theme_mode": "hub",  # 'hub', 'dark', 'light'
                "alarm_sound": True,  # toca o som ao zerar a contagem regressiva
                "smart_hover": True,  # scroll nos dígitos digitais (HH:MM:SS)
                "show_on_startup": False,  # exibir o widget ao iniciar o app (senão, só pelo atalho)
                "hotkey": "Win+Alt+T",
            },
            "hub": {
                "theme": "system",  # segue o tema do Windows
                "keep_in_tray": True,
                "start_with_windows": False,
                "start_minimized": True,
                "language": "pt",
            }
        }

    def _save(self):
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            tmp_path = self.config_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            if os.path.exists(self.config_path):
                os.replace(tmp_path, self.config_path)
            else:
                os.rename(tmp_path, self.config_path)
        except Exception as e:
            logger.error("Erro ao salvar configurações em %s: %s", self.config_path, e)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value
        self._save()

    # --- Helpers de Configuração: Music Widget ---

    def is_music_position_remembered(self) -> bool:
        music_cfg = self._data.setdefault("music_widget", {})
        return bool(music_cfg.get("remember_position", False))

    def set_music_position_remembered(
        self, enabled: bool, x: Optional[int] = None, y: Optional[int] = None
    ):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["remember_position"] = bool(enabled)
        if enabled and x is not None and y is not None:
            music_cfg["position"] = [int(x), int(y)]
        self._save()

    def get_music_saved_position(self) -> Optional[Tuple[int, int]]:
        music_cfg = self._data.get("music_widget", {})
        pos = music_cfg.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            try:
                return (int(pos[0]), int(pos[1]))
            except (ValueError, TypeError):
                return None
        return None

    def save_music_position(self, x: int, y: int):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["position"] = [int(x), int(y)]
        self._save()

    def get_music_scale(self) -> Optional[float]:
        """Retorna a escala customizada definida pelo usuário (ou None para cálculo automático)."""
        music_cfg = self._data.get("music_widget", {})
        val = music_cfg.get("scale")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        return None

    def get_effective_music_scale(self, screen=None) -> float:
        """
        Retorna a escala efetiva a ser aplicada ao Music Widget:
        - Se o usuário escolheu uma escala específica, usa a preferência do usuário.
        - Caso contrário, calcula proporcionalmente com base na resolução da tela atual.
        """
        user_scale = self.get_music_scale()
        if user_scale is not None:
            return user_scale
        return get_auto_music_scale(screen=screen)

    def set_music_scale(self, scale: Optional[float]):
        """Define a escala customizada do Music Widget (ou None para restaurar o modo automático)."""
        music_cfg = self._data.setdefault("music_widget", {})
        if scale is not None:
            music_cfg["scale"] = round(float(scale), 4)
        else:
            music_cfg["scale"] = None
        self._save()

    def is_music_scale_auto(self) -> bool:
        """Indica se a escala do Music Widget está no modo de detecção automática."""
        return self.get_music_scale() is None

    def get_active_skin(self, default: str = "vinyl") -> str:
        music_cfg = self._data.get("music_widget", {})
        return str(music_cfg.get("active_skin", default))

    def set_active_skin(self, skin_name: str):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["active_skin"] = str(skin_name)
        self._save()

    def get_active_widget_skins(self) -> list[str]:
        """
        Retorna a lista de skins ativas do Music Widget (disponíveis para troca rápida).
        Padrão de fábrica: todas as skins disponíveis vêm marcadas como ativas.
        """
        music_cfg = self._data.setdefault("music_widget", {})
        skins = music_cfg.get("active_widget_skins")
        if skins is None:
            skins = self._data.get("active_widget_skins")
        if not isinstance(skins, list) or len(skins) == 0:
            default_skins = ["vinyl", "fullcover", "ripple", "capa_empilhada"]
            music_cfg["active_widget_skins"] = list(default_skins)
            self._data["active_widget_skins"] = list(default_skins)
            self._save()
            return list(default_skins)
        return list(skins)

    def set_active_widget_skins(self, skins: list[str]) -> bool:
        """
        Persiste a lista de skins ativas.
        Garante validação para impedir desmarcar todas (mínimo de 1 skin sempre ativa).
        """
        if not skins:
            logger.warning("Tentativa de salvar active_widget_skins vazio. Rejeitado: mínimo de 1 skin exigida.")
            return False
        clean = [str(s) for s in skins]
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["active_widget_skins"] = clean
        self._data["active_widget_skins"] = clean

        # Se a skin ativa em uso foi removida da lista, redefine para a primeira ativa restante
        curr_skin = self.get_active_skin("vinyl")
        if curr_skin not in clean:
            self.set_active_skin(clean[0])

        self._save()
        return True

    def is_skin_active(self, skin_id: str) -> bool:
        """Verifica se uma skin específica do Music Widget está na lista de ativas."""
        return skin_id in self.get_active_widget_skins()

    def set_skin_active(self, skin_id: str, active: bool) -> bool:
        """
        Marca ou desmarca uma skin específica como ativa.
        Retorna True se a operação foi aceita, ou False se bloqueada pela regra do mínimo de 1 ativa.
        """
        current = self.get_active_widget_skins()
        if active:
            if skin_id not in current:
                current.append(skin_id)
                return self.set_active_widget_skins(current)
            return True
        else:
            if skin_id in current:
                if len(current) <= 1:
                    logger.warning("Validação: impossível desmarcar '%s'. Deve haver no mínimo 1 skin ativa.", skin_id)
                    return False
                current.remove(skin_id)
                return self.set_active_widget_skins(current)
            return True

    def get_stacked_cover_effect(self, default: str = "ripple") -> str:
        music_cfg = self._data.get("music_widget", {})
        return str(music_cfg.get("stacked_cover_effect", default))

    def set_stacked_cover_effect(self, effect: str):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["stacked_cover_effect"] = str(effect)
        self._save()


    def is_music_enabled(self) -> bool:
        music_cfg = self._data.get("music_widget", {})
        return bool(music_cfg.get("enabled", True))

    def set_music_enabled(self, enabled: bool):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["enabled"] = bool(enabled)
        self._save()

    def get_music_launch_mode(self, default: str = "auto") -> str:
        music_cfg = self._data.get("music_widget", {})
        return str(music_cfg.get("launch_mode", default))

    def set_music_launch_mode(self, mode: str):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["launch_mode"] = str(mode)
        self._save()

    def is_auto_launch_enabled(self) -> bool:
        return self.get_music_launch_mode() == "auto"

    def set_auto_launch_enabled(self, enabled: bool):
        self.set_music_launch_mode("auto" if enabled else "manual")

    def is_auto_hide_enabled(self) -> bool:
        music_cfg = self._data.get("music_widget", {})
        return bool(music_cfg.get("auto_hide_on_stop", False))

    def set_auto_hide_enabled(self, enabled: bool):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["auto_hide_on_stop"] = bool(enabled)
        self._save()

    def is_music_wheel_volume_enabled(self) -> bool:
        """Se rolar a roda do mouse sobre o Music Widget ajusta o volume (padrão: ativado)."""
        music_cfg = self._data.get("music_widget", {})
        return bool(music_cfg.get("wheel_volume", True))

    def set_music_wheel_volume_enabled(self, enabled: bool):
        music_cfg = self._data.setdefault("music_widget", {})
        music_cfg["wheel_volume"] = bool(enabled)
        self._save()

    # --- Helpers de Configuração: Timer Widget ---

    def is_timer_enabled(self) -> bool:
        timer_cfg = self._data.get("timer_widget", {})
        return bool(timer_cfg.get("enabled", True))

    def set_timer_enabled(self, enabled: bool):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["enabled"] = bool(enabled)
        self._save()

    def is_timer_show_on_startup(self) -> bool:
        timer_cfg = self._data.get("timer_widget", {})
        return bool(timer_cfg.get("show_on_startup", False))

    def set_timer_show_on_startup(self, enabled: bool):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["show_on_startup"] = bool(enabled)
        self._save()

    def is_timer_position_remembered(self) -> bool:
        timer_cfg = self._data.setdefault("timer_widget", {})
        return bool(timer_cfg.get("remember_position", False))

    def set_timer_position_remembered(
        self, enabled: bool, x: Optional[int] = None, y: Optional[int] = None
    ):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["remember_position"] = bool(enabled)
        if enabled and x is not None and y is not None:
            timer_cfg["position"] = [int(x), int(y)]
        self._save()

    def get_timer_saved_position(self) -> Optional[Tuple[int, int]]:
        timer_cfg = self._data.get("timer_widget", {})
        pos = timer_cfg.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            try:
                return (int(pos[0]), int(pos[1]))
            except (ValueError, TypeError):
                return None
        return None

    def save_timer_position(self, x: int, y: int):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["position"] = [int(x), int(y)]
        self._save()

    def get_timer_saved_size(self, screen=None) -> Tuple[int, int]:
        timer_cfg = self._data.get("timer_widget", {})
        size = timer_cfg.get("size")
        if isinstance(size, (list, tuple)) and len(size) >= 2:
            try:
                return (int(size[0]), int(size[1]))
            except (ValueError, TypeError):
                pass
        return get_auto_timer_size(screen=screen)

    def save_timer_size(self, w: int, h: int):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["size"] = [int(w), int(h)]
        self._save()

    def get_timer_mode(self, default: str = "timer") -> str:
        timer_cfg = self._data.get("timer_widget", {})
        return str(timer_cfg.get("mode", default))

    def set_timer_mode(self, mode: str):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["mode"] = str(mode)
        self._save()

    def get_timer_duration(self, default: int = 300) -> int:
        timer_cfg = self._data.get("timer_widget", {})
        try:
            return int(timer_cfg.get("duration", default))
        except (ValueError, TypeError):
            return default

    def set_timer_duration(self, duration: int):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["duration"] = int(duration)
        self._save()

    def get_timer_alarm_time(self) -> Optional[int]:
        """Horário do modo Alarme em segundos desde a meia-noite; None = nunca definido."""
        value = self._data.get("timer_widget", {}).get("alarm_time")
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value % 86400

    def set_timer_alarm_time(self, seconds: int):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["alarm_time"] = int(seconds) % 86400
        self._save()

    def get_timer_theme_mode(self, default: str = "hub") -> str:
        timer_cfg = self._data.get("timer_widget", {})
        return str(timer_cfg.get("theme_mode", default))

    def set_timer_theme_mode(self, theme_mode: str):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["theme_mode"] = str(theme_mode)
        self._save()

    def get_timer_active_skin(self, default: str = "windows") -> str:
        timer_cfg = self._data.get("timer_widget", {})
        return str(timer_cfg.get("active_skin", default))

    def set_timer_active_skin(self, skin_name: str):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["active_skin"] = str(skin_name)
        self._save()

    def is_timer_alarm_sound_enabled(self) -> bool:
        timer_cfg = self._data.get("timer_widget", {})
        return bool(timer_cfg.get("alarm_sound", True))

    def set_timer_alarm_sound_enabled(self, enabled: bool):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["alarm_sound"] = bool(enabled)
        self._save()

    def is_timer_smart_hover_enabled(self) -> bool:
        timer_cfg = self._data.get("timer_widget", {})
        return bool(timer_cfg.get("smart_hover", True))

    def set_timer_smart_hover_enabled(self, enabled: bool):
        timer_cfg = self._data.setdefault("timer_widget", {})
        timer_cfg["smart_hover"] = bool(enabled)
        self._save()

    # --- Helpers de Configuração: Hub & Sistema ---

    def get_hub_theme(self, default: str = "system") -> str:
        hub_cfg = self._data.get("hub", {})
        return str(hub_cfg.get("theme", default))

    def set_hub_theme(self, theme_name: str):
        hub_cfg = self._data.setdefault("hub", {})
        hub_cfg["theme"] = str(theme_name)
        self._save()

    def get_last_theme_dir(self) -> str:
        """Última pasta usada ao importar/exportar temas ("" = nunca)."""
        value = self._data.get("hub", {}).get("last_theme_dir")
        return value if isinstance(value, str) else ""

    def set_last_theme_dir(self, path: str):
        hub_cfg = self._data.setdefault("hub", {})
        if hub_cfg.get("last_theme_dir") != path:
            hub_cfg["last_theme_dir"] = str(path)
            self._save()

    def get_hub_accent(self):
        """Cor de destaque escolhida: '#RRGGBB' (cor exata), int 0-359 (matiz) ou None (âmbar padrão do app)."""
        hub_cfg = self._data.get("hub", {})
        color = hub_cfg.get("accent_color")
        if isinstance(color, str):
            import re
            if re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                return color.upper()
        value = hub_cfg.get("accent_hue")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value) % 360

    def set_hub_accent(self, accent):
        hub_cfg = self._data.setdefault("hub", {})
        hub_cfg.pop("accent_hue", None)
        hub_cfg.pop("accent_color", None)
        if isinstance(accent, str):
            hub_cfg["accent_color"] = accent.upper()
        elif accent is not None:
            hub_cfg["accent_hue"] = int(accent) % 360
        self._save()

    def get_language(self, default: str = "pt") -> str:
        hub_cfg = self._data.get("hub", {})
        lang = hub_cfg.get("language")
        if lang in ("pt", "en"):
            return str(lang)
        return default

    def set_language(self, lang: str):
        if lang not in ("pt", "en"):
            lang = "pt"
        hub_cfg = self._data.setdefault("hub", {})
        hub_cfg["language"] = str(lang)
        self._save()

    def is_keep_in_tray_enabled(self) -> bool:
        hub_cfg = self._data.get("hub", {})
        return bool(hub_cfg.get("keep_in_tray", True))

    def set_keep_in_tray_enabled(self, enabled: bool):
        hub_cfg = self._data.setdefault("hub", {})
        hub_cfg["keep_in_tray"] = bool(enabled)
        self._save()

    def is_start_with_windows_enabled(self) -> bool:
        hub_cfg = self._data.get("hub", {})
        return bool(hub_cfg.get("start_with_windows", False))

    def set_start_with_windows_enabled(self, enabled: bool):
        hub_cfg = self._data.setdefault("hub", {})
        hub_cfg["start_with_windows"] = bool(enabled)
        self._save()
        self.sync_windows_startup()

    def is_start_minimized_enabled(self) -> bool:
        hub_cfg = self._data.get("hub", {})
        return bool(hub_cfg.get("start_minimized", True))

    def set_start_minimized_enabled(self, enabled: bool):
        hub_cfg = self._data.setdefault("hub", {})
        hub_cfg["start_minimized"] = bool(enabled)
        self._save()
        if self.is_start_with_windows_enabled():
            self.sync_windows_startup()

    def sync_windows_startup(self):
        """
        Sincroniza a chave de inicialização no Registro do Windows:
        HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run -> 'Aimedget'
        Compatível com .exe empacotado (PyInstaller) e ambiente de desenvolvimento.
        """
        import sys
        if sys.platform != "win32":
            return
        try:
            import winreg
            reg_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_reg_name = "Aimedget"

            start_enabled = self.is_start_with_windows_enabled()
            minimized = self.is_start_minimized_enabled()

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
                if start_enabled:
                    if getattr(sys, "frozen", False):
                        cmd = f'"{sys.executable}"'
                    else:
                        from app.core.paths import BASE_DIR
                        main_script = os.path.join(BASE_DIR, "app", "main.py")
                        pythonw_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                        exec_bin = pythonw_exe if os.path.exists(pythonw_exe) else sys.executable
                        cmd = f'"{exec_bin}" "{main_script}"'

                    if minimized:
                        cmd += " --minimized"

                    winreg.SetValueEx(key, app_reg_name, 0, winreg.REG_SZ, cmd)
                    logger.info("Aimedget registrado no arranque do Windows: %s", cmd)
                else:
                    try:
                        winreg.DeleteValue(key, app_reg_name)
                        logger.info("Aimedget removido do arranque do Windows.")
                    except FileNotFoundError:
                        pass
        except Exception as e:
            logger.warning("Falha ao sincronizar registro de inicialização do Windows: %s", e)

    def get_hub_geometry(self) -> Optional[Tuple[int, int, int, int]]:
        """Retorna (x, y, width, height) da última posição e tamanho do Hub."""
        hub_cfg = self._data.get("hub", {})
        geo = hub_cfg.get("geometry")
        if isinstance(geo, (list, tuple)) and len(geo) == 4:
            try:
                return (int(geo[0]), int(geo[1]), int(geo[2]), int(geo[3]))
            except (ValueError, TypeError):
                return None
        return None

    def save_hub_geometry(self, x: int, y: int, w: int, h: int):
        """Salva a geometria do Hub."""
        hub_cfg = self._data.setdefault("hub", {})
        hub_cfg["geometry"] = [int(x), int(y), int(w), int(h)]
        self._save()

    # --- Atalhos Globais de Teclado (Hotkeys) ---

    def get_music_hotkey(self, default: str = "Win+Alt+M") -> str:
        cfg = self._data.get("music_widget", {})
        return str(cfg.get("hotkey", default))

    def set_music_hotkey(self, hotkey: str):
        cfg = self._data.setdefault("music_widget", {})
        cfg["hotkey"] = str(hotkey)
        self._save()

    def get_timer_hotkey(self, default: str = "Win+Alt+T") -> str:
        cfg = self._data.get("timer_widget", {})
        return str(cfg.get("hotkey", default))

    def set_timer_hotkey(self, hotkey: str):
        cfg = self._data.setdefault("timer_widget", {})
        cfg["hotkey"] = str(hotkey)
        self._save()

    def get_keylock_hotkey(self, default: str = "Win+Alt+K") -> str:
        cfg = self._data.get("keylock_osd", {})
        return str(cfg.get("hotkey", default))

    def set_keylock_hotkey(self, hotkey: str):
        cfg = self._data.setdefault("keylock_osd", {})
        cfg["hotkey"] = str(hotkey)
        self._save()

    # --- Temas que vêm com o app (app/core/bundled_themes.py) ---

    def was_theme_seeded(self, container_id: str, theme_id: str) -> bool:
        seeded = self._data.get("themes_seeded", {})
        ids = seeded.get(container_id) if isinstance(seeded, dict) else None
        return isinstance(ids, list) and theme_id in ids

    def mark_theme_seeded(self, container_id: str, theme_id: str):
        seeded = self._data.get("themes_seeded")
        if not isinstance(seeded, dict):
            seeded = self._data["themes_seeded"] = {}
        ids = seeded.get(container_id)
        if not isinstance(ids, list):
            ids = seeded[container_id] = []
        if theme_id not in ids:
            ids.append(theme_id)
            self._save()

    # --- Verificação automática de atualizações ---

    def is_auto_update_check_enabled(self) -> bool:
        """Consultar o GitHub sozinho ao abrir o app (no máximo 1x por dia). Padrão: ligado."""
        value = self._data.get("updates", {}).get("auto_check")
        return value if isinstance(value, bool) else True

    def set_auto_update_check_enabled(self, enabled: bool):
        self._data.setdefault("updates", {})["auto_check"] = bool(enabled)
        self._save()

    def get_last_update_check(self) -> float:
        """Quando a última consulta automática deu certo (segundos desde 1970); 0 = nunca."""
        value = self._data.get("updates", {}).get("last_check")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    def set_last_update_check(self, timestamp: float):
        self._data.setdefault("updates", {})["last_check"] = float(timestamp)
        self._save()

    def get_declined_update_version(self) -> str:
        """Versão que o usuário respondeu 'agora não': a consulta automática não pergunta de novo por ela."""
        value = self._data.get("updates", {}).get("declined_version")
        return value if isinstance(value, str) else ""

    def set_declined_update_version(self, version: str):
        self._data.setdefault("updates", {})["declined_version"] = str(version)
        self._save()

    def get_osd_anchor(self, flyout: str) -> str:
        """
        Âncora na tela de um flyout ('keylock' ou 'mixer'); 'bc' = acima da barra de tarefas.
        A chave antiga "anchor" (quando a posição era compartilhada) vale para os dois até cada um ser escolhido.
        """
        from app.core.osd_anchor import normalize
        cfg = self._data.get("osd", {})
        return normalize(cfg.get(f"{flyout}_anchor", cfg.get("anchor")))

    def set_osd_anchor(self, flyout: str, anchor: str):
        from app.core.osd_anchor import normalize
        cfg = self._data.setdefault("osd", {})
        cfg[f"{flyout}_anchor"] = normalize(anchor)
        self._save()

    def is_keylock_key_enabled(self, key_name: str) -> bool:
        """Se o indicador de uma tecla ('Caps Lock' / 'Num Lock') deve aparecer ao alternar. Padrão: ligado."""
        keys = self._data.get("keylock_osd", {}).get("keys")
        value = keys.get(key_name) if isinstance(keys, dict) else None
        return value if isinstance(value, bool) else True

    def set_keylock_key_enabled(self, key_name: str, enabled: bool):
        cfg = self._data.setdefault("keylock_osd", {})
        keys = cfg.get("keys")
        if not isinstance(keys, dict):
            keys = cfg["keys"] = {}
        keys[key_name] = bool(enabled)
        self._save()

    def get_volume_hotkey(self, default: str = "Win+Alt+V") -> str:
        cfg = self._data.get("volume_mixer", {})
        return str(cfg.get("hotkey", default))

    def set_volume_hotkey(self, hotkey: str):
        cfg = self._data.setdefault("volume_mixer", {})
        cfg["hotkey"] = str(hotkey)
        self._save()

    def get_theme_choice(self, container_id: str) -> Optional[str]:
        """Tema visual escolhido para um container (ex.: 'keylock', 'mixer'); None = nunca escolheu."""
        themes = self._data.get("themes")
        value = themes.get(container_id) if isinstance(themes, dict) else None
        return value if isinstance(value, str) and value else None

    def set_theme_choice(self, container_id: str, theme_id: str):
        themes = self._data.get("themes")
        if not isinstance(themes, dict):
            themes = self._data["themes"] = {}
        themes[container_id] = str(theme_id)
        self._save()


# Instância global reutilizável
config_manager = ConfigManager()
