"""
Condições do tempo do Weather Widget e o "cenário" de cada uma (céu, partículas, ícone).

Puro (sem Qt): o código WMO que a Open-Meteo devolve vira uma das condições abaixo, e cada condição aponta para um
`Scene` com as cores e quantidades que o desenho usa. Valores de partida vêm da referência
(`Referências Visuais/Weather Widget/how the weather widget was done - html, css and js.txt`); as condições que a
referência não tinha (noite, parcialmente nublado, neblina, neve, chuva fraca/forte) seguem o mesmo vocabulário.
"""

from dataclasses import dataclass, replace

SUNNY = "sunny"
CLEAR_NIGHT = "clear_night"
PARTLY_CLOUDY = "partly_cloudy"
CLOUDY = "cloudy"
FOG = "fog"
LIGHT_RAIN = "light_rain"
RAIN = "rain"
HEAVY_RAIN = "heavy_rain"
THUNDERSTORM = "thunderstorm"
SNOW = "snow"

# Versões noturnas (a Open-Meteo diz `is_day`; só o céu limpo tinha noite, o resto aparecia com céu e sol de dia)
PARTLY_CLOUDY_NIGHT = "partly_cloudy_night"
CLOUDY_NIGHT = "cloudy_night"
FOG_NIGHT = "fog_night"
LIGHT_RAIN_NIGHT = "light_rain_night"
RAIN_NIGHT = "rain_night"
HEAVY_RAIN_NIGHT = "heavy_rain_night"
THUNDERSTORM_NIGHT = "thunderstorm_night"
SNOW_NIGHT = "snow_night"

# condição de dia -> a mesma à noite (o céu limpo já tem o seu par: SUNNY <-> CLEAR_NIGHT)
NIGHT_OF = {
    SUNNY: CLEAR_NIGHT, PARTLY_CLOUDY: PARTLY_CLOUDY_NIGHT, CLOUDY: CLOUDY_NIGHT, FOG: FOG_NIGHT,
    LIGHT_RAIN: LIGHT_RAIN_NIGHT, RAIN: RAIN_NIGHT, HEAVY_RAIN: HEAVY_RAIN_NIGHT,
    THUNDERSTORM: THUNDERSTORM_NIGHT, SNOW: SNOW_NIGHT,
}
DAY_OF = {night: day for day, night in NIGHT_OF.items()}

# Ordem usada no menu de pré-visualização e nos testes
ALL_CONDITIONS = (
    SUNNY, CLEAR_NIGHT, PARTLY_CLOUDY, CLOUDY, FOG, LIGHT_RAIN, RAIN, HEAVY_RAIN, THUNDERSTORM, SNOW,
    PARTLY_CLOUDY_NIGHT, CLOUDY_NIGHT, FOG_NIGHT, LIGHT_RAIN_NIGHT, RAIN_NIGHT, HEAVY_RAIN_NIGHT,
    THUNDERSTORM_NIGHT, SNOW_NIGHT,
)


def is_night(condition: str) -> bool:
    return condition == CLEAR_NIGHT or condition in DAY_OF


def name_key(condition: str) -> str:
    """Chave do nome na tradução: a noite usa o nome da condição de dia (o céu limpo à noite tem o seu)."""
    return condition if condition == CLEAR_NIGHT else DAY_OF.get(condition, condition)

# WMO 4677 (o que a Open-Meteo usa em `weather_code`)
_WMO = {
    0: SUNNY, 1: SUNNY,
    2: PARTLY_CLOUDY,
    3: CLOUDY,
    45: FOG, 48: FOG,
    51: LIGHT_RAIN, 53: LIGHT_RAIN, 55: LIGHT_RAIN,   # garoa
    56: LIGHT_RAIN, 57: LIGHT_RAIN,                   # garoa congelante
    61: LIGHT_RAIN, 63: RAIN, 65: HEAVY_RAIN,
    66: RAIN, 67: HEAVY_RAIN,                         # chuva congelante
    71: SNOW, 73: SNOW, 75: SNOW, 77: SNOW,
    80: LIGHT_RAIN, 81: RAIN, 82: HEAVY_RAIN,         # pancadas
    85: SNOW, 86: SNOW,
    95: THUNDERSTORM, 96: THUNDERSTORM, 99: THUNDERSTORM,
}


def condition_from_wmo(code: int | None, is_day: bool = True) -> str:
    """Condição para um código WMO. À noite cada condição vira a sua versão noturna; desconhecido cai em CLOUDY."""
    try:
        cond = _WMO.get(int(code), CLOUDY)
    except (TypeError, ValueError):
        cond = CLOUDY
    if not is_day:
        return NIGHT_OF.get(cond, cond)
    return cond


@dataclass(frozen=True)
class Blob:
    """Mancha de luz radial que deriva devagar (a `.wx-blob` da referência), em px do cartão de 300 de largura."""
    x: float          # canto superior esquerdo (pode ser negativo: a mancha passa da borda)
    y: float
    w: float
    h: float
    rgba: tuple       # cor do centro; a borda é a mesma cor com alfa 0
    stop: float = 0.68   # onde o gradiente chega a zero (0..1 do raio)
    slow: float = 1.0    # multiplicador da duração da deriva
    reverse: bool = False


@dataclass(frozen=True)
class Scene:
    sky: tuple                 # paradas do gradiente vertical: ((pos, "#rrggbb"), ...)
    blobs: tuple = ()
    rain: int = 0              # riscos de chuva no fundo
    rain_ms: float = 800.0     # tempo de queda de um risco
    rain_alpha: float = 0.42
    rain_len: tuple = (12, 22)
    flash: bool = False        # relâmpago
    snow: int = 0              # flocos
    fog: int = 0               # faixas de neblina
    stars: int = 0
    icon: str = "sun"          # chave do ícone grande (icons.py)
    drops: int = 0             # gotas/flocos animados sob a nuvem do ícone
    drop_kind: str = "rain"    # "rain" ou "snow"


_CLEAR_BLOBS = (
    Blob(-130, 70, 280, 280, (110, 190, 255, 0.32), 0.68, slow=1.3, reverse=True),
    Blob(170, 130, 240, 240, (255, 200, 120, 0.34), 0.65),
)
_CLOUD_BLOBS = (
    Blob(-90, 110, 300, 170, (255, 255, 255, 0.20)),
    Blob(150, 82, 240, 150, (255, 255, 255, 0.16), slow=1.25, reverse=True),
)

SCENES: dict[str, Scene] = {
    SUNNY: Scene(
        sky=((0.0, "#1f6fd1"), (0.55, "#2f7fdb"), (1.0, "#3b8ae0")),
        blobs=_CLEAR_BLOBS,
        icon="sun",
    ),
    CLEAR_NIGHT: Scene(
        sky=((0.0, "#0e1a38"), (0.6, "#1a2a52"), (1.0, "#26386a")),
        blobs=(
            Blob(150, -60, 260, 220, (170, 190, 255, 0.20), slow=1.2),
            Blob(-120, 120, 280, 240, (80, 110, 200, 0.22), reverse=True),
        ),
        stars=22,
        icon="moon",
    ),
    PARTLY_CLOUDY: Scene(
        sky=((0.0, "#2a68b8"), (1.0, "#6a90bd")),
        blobs=(
            Blob(170, 130, 240, 240, (255, 205, 130, 0.26), 0.65),
            Blob(-90, 110, 300, 170, (255, 255, 255, 0.18)),
        ),
        icon="partly",
    ),
    CLOUDY: Scene(
        sky=((0.0, "#4e6a85"), (1.0, "#7a91a8")),
        blobs=_CLOUD_BLOBS,
        icon="cloud",
    ),
    FOG: Scene(
        sky=((0.0, "#6f7d8b"), (1.0, "#9ea9b3")),
        blobs=(Blob(-60, 40, 340, 200, (230, 236, 242, 0.18), slow=1.4),),
        fog=4,
        icon="fog",
    ),
    LIGHT_RAIN: Scene(
        sky=((0.0, "#48607a"), (1.0, "#6c8299")),
        blobs=(Blob(-60, 102, 320, 200, (170, 200, 230, 0.22)),),
        rain=9, rain_ms=950.0, rain_alpha=0.34, rain_len=(10, 16),
        icon="rain", drops=2,
    ),
    RAIN: Scene(
        sky=((0.0, "#3f5266"), (1.0, "#5f7388")),
        blobs=(Blob(-60, 102, 320, 200, (170, 200, 230, 0.22)),),
        rain=14,
        icon="rain", drops=3,
    ),
    HEAVY_RAIN: Scene(
        sky=((0.0, "#334356"), (1.0, "#52657a")),
        blobs=(Blob(-60, 102, 320, 200, (160, 190, 220, 0.20)), Blob(150, 30, 280, 190, (140, 160, 190, 0.18), reverse=True)),
        rain=30, rain_ms=620.0, rain_alpha=0.5, rain_len=(16, 26),
        icon="rain", drops=4,
    ),
    THUNDERSTORM: Scene(
        sky=((0.0, "#323b47"), (1.0, "#56616e")),
        blobs=(Blob(100, 40, 300, 200, (140, 160, 190, 0.20)),),
        rain=20, flash=True,
        icon="bolt",
    ),
    SNOW: Scene(
        sky=((0.0, "#6a819c"), (1.0, "#a7b8ca")),
        blobs=(Blob(-90, 110, 300, 170, (255, 255, 255, 0.22)), Blob(150, 30, 240, 150, (255, 255, 255, 0.14), reverse=True)),
        snow=28,
        icon="snow", drops=3, drop_kind="snow",
    ),
}



def _mix_hex(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


_NIGHT_SKY = "#0e1a38"


def _night_scene(day: Scene, mix: float = 0.62, **changes) -> Scene:
    """O céu do dia escurecido em direção ao azul-noite; as manchas de luz quente viram frias."""
    sky = tuple((pos, _mix_hex(color, _NIGHT_SKY, mix)) for pos, color in day.sky)
    blobs = tuple(
        replace(b, rgba=(round(b.rgba[0] * 0.55 + 80 * 0.45), round(b.rgba[1] * 0.55 + 110 * 0.45),
                         round(b.rgba[2] * 0.55 + 200 * 0.45), b.rgba[3] * 0.8))
        for b in day.blobs)
    return replace(day, sky=sky, blobs=blobs, **changes)


SCENES.update({
    PARTLY_CLOUDY_NIGHT: _night_scene(SCENES[PARTLY_CLOUDY], 0.7, stars=12, icon="partly_night"),
    CLOUDY_NIGHT: _night_scene(SCENES[CLOUDY]),
    FOG_NIGHT: _night_scene(SCENES[FOG]),
    LIGHT_RAIN_NIGHT: _night_scene(SCENES[LIGHT_RAIN]),
    RAIN_NIGHT: _night_scene(SCENES[RAIN]),
    HEAVY_RAIN_NIGHT: _night_scene(SCENES[HEAVY_RAIN], 0.5),
    THUNDERSTORM_NIGHT: _night_scene(SCENES[THUNDERSTORM], 0.5),
    SNOW_NIGHT: _night_scene(SCENES[SNOW], 0.55),
})

# Ícone pequeno da aba: a de hoje à noite mostra a lua; as dos outros dias são sempre de dia
TAB_ICON = {
    SUNNY: "sun", CLEAR_NIGHT: "moon", PARTLY_CLOUDY: "partly", CLOUDY: "cloud", FOG: "fog",
    LIGHT_RAIN: "rain", RAIN: "rain", HEAVY_RAIN: "rain", THUNDERSTORM: "bolt", SNOW: "snow",
    PARTLY_CLOUDY_NIGHT: "partly_night", CLOUDY_NIGHT: "cloud", FOG_NIGHT: "fog", LIGHT_RAIN_NIGHT: "rain",
    RAIN_NIGHT: "rain", HEAVY_RAIN_NIGHT: "rain", THUNDERSTORM_NIGHT: "bolt", SNOW_NIGHT: "snow",
}

# Ícones grandes que ficam amarelos (o resto é branco), como `.wx-big .t-icon[data-key="sun"|"bolt"]`
WARM_ICONS = frozenset({"sun", "bolt"})


def scene_for(condition: str) -> Scene:
    return SCENES.get(condition, SCENES[CLOUDY])


# Estado sem dados (sem internet / sem local): céu ardósia neutro, sem partículas
UNAVAILABLE_SCENE = Scene(sky=((0.0, "#4b5866"), (1.0, "#6b7886")), blobs=_CLOUD_BLOBS, icon="cloud")
