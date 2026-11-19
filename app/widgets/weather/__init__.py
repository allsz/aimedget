"""
Módulo Weather Widget - Aimedget.
Cartão de previsão do tempo com 5 dias clicáveis e fundo animado por condição (sol, nuvens, chuva, tempestade,
neve, neblina, noite). Dados da Open-Meteo via app/services/weather_service.py.
"""

from app.widgets.weather.weather_controller import WeatherWidgetController
from app.widgets.weather.specs import init_weather_skin_specs, init_weather_spec

__all__ = ["WeatherWidgetController", "init_weather_spec", "init_weather_skin_specs"]
