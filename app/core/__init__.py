"""Módulo Core: caminhos, tipografia, configurações globais e crash reporter."""
from app.core.config_manager import ConfigManager, config_manager
from app.core.paths import BASE_DIR, ASSETS_DIR
from app.core.crash_reporter import (
    install_crash_reporter,
    record_exception,
    get_crash_reports_dir,
)

__all__ = [
    "ConfigManager",
    "config_manager",
    "BASE_DIR",
    "ASSETS_DIR",
    "install_crash_reporter",
    "record_exception",
    "get_crash_reports_dir",
]
