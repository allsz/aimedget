# Weather Widget — Plan (draft for review)

Reference: `Referências Visuais/Weather Widget/widgets ideas.mp4`, 0:00–~4:00, the blue/slate card ("San Francisco").

## 1. What the reference shows

A square-ish rounded card (~1.15:1), no chrome:

- **Header:** city (semibold, white) + weekday (lighter).
- **Hero:** huge temperature (`24°`, light-weight numerals) on the left, a line-style condition icon on the right (sun with rotating rays, cloud outline).
- **Footer text:** condition label (`Sunny`) + `H:26° L:17°`.
- **Day selector:** translucent pill bar with 4–5 days (icon + `Mon Tue Wed Thu Fri`); the selected day has a lighter "thumb" that slides between days.
- **Motion (the important part):** clicking a day cross-fades the whole card:
  - background gradient morphs (bright blue → desaturated slate → dark storm slate);
  - the temperature number changes (digits roll/blur between values);
  - icon swaps (sun → cloud → cloud with rain → lightning bolt);
  - ambient particles live inside the card (light rain streaks falling, flashes for thunder);
  - the selector thumb glides.

## 2. Conditions (your list + what I'd add)

Yours: **sunny, cloudy, light rain, rain, heavy rain, thunderstorm, snow.**

Missing, in order of importance:

1. **Clear night** (moon + stars). A desktop widget lives all day; sunny at 11pm looks broken. This doubles as day/night variants for sunny and partly cloudy.
2. **Partly cloudy** — the most common real-world state; "sunny" and "cloudy" alone leave a gap.
3. **Fog / mist** — easy to animate (drifting translucent bands), and Open-Meteo returns it.
4. **Sleet / freezing rain** — can be folded into snow v1 (mixed particles).
5. **Unavailable / loading** — offline or no location. Not a weather, but needs a designed state.

Optional later: wind, hail, heat/cold extremes. Suggestion: ship v1 with **9 states** = the 7 + clear night + partly cloudy + fog (+ the unavailable state).

## 3. Where it fits in the app (follows the Timer pattern)

New package `app/widgets/weather/`, split per `modular-architecture`:

```
app/widgets/weather/
  __init__.py
  specs.py                    # WidgetSpec / init_weather_spec  (Hub preview)
  weather_controller.py       # show/hide (AnimatedVisibilityMixin), skin, refresh timer
  conditions.py               # enum + WMO weather-code -> condition mapping (pure, unit-tested)
  skins/
    __init__.py, specs.py     # SkinSpec registry
    base_skin.py              # window shell: frameless, drag, rest_pos, animator
    glass_skin.py             # default skin = the reference
    scenes/                   # one painter per condition (sun.py, rain.py, storm.py, snow.py, fog.py, clouds.py, night.py)
    particles.py              # shared particle system (rain streaks, snowflakes)
    transitions.py            # gradient morph, number roll, icon crossfade
app/services/weather_service.py   # NO UI: fetch + cache + signals (like media_worker)
```

Wiring (same touchpoints the Timer uses):

- `app/hub/service_bridge.py` — create `weather_controller`, hotkey (`Win+Alt+W`), `set_weather_enabled`, `toggle_weather_widget`.
- `app/core/config_manager.py` — enabled, show-on-startup, position/remember, size, location, units (°C/°F), hotkey, active skin.
- `app/hub/pages.py` — Overview card (`WidgetCard`), new `WeatherPage` (position, style, location, units, startup), sidebar entry.
- `app/core/i18n.py` — pt-BR + en strings (condition names, weekdays come from locale).
- `Aimedget.spec` — hidden imports if needed.
- `CHANGELOG.md`, tests.

## 4. Data source (decision needed — see questions)

- **Forecast:** Open-Meteo (free, no API key, no account) `forecast` endpoint: current + daily (5 days, hi/lo, WMO code). Fits "portable .exe, no prerequisites".
- **Location:** user types a city in the Hub (Open-Meteo geocoding API) — works offline-safe and private. Optional "detect automatically" via IP lookup.
- Fetch on a background thread (`QThread`/worker, like `media_worker`), refresh every ~30 min, cache last result in config so the widget paints instantly at startup. Zero network when the widget is off.
- Uses `urllib` (already used by `updater_service`), so no new dependency.

## 5. Rendering approach

Pure `QPainter` inside a `QWidget`, like the other skins (no QML/web — matches PRODUCT.md).

- One `QTimer` at the screen refresh rate **only while visible and a scene has motion**; stopped when hidden, so idle cost stays ~0 (there's already `test_idle_performance.py` to guard this).
- Particles: capped counts (rain ≈ 40/90/180 by intensity, snow ≈ 60), precomputed `QPainterPath`/lines, clipped to the rounded card.
- Lightning: random 4–9 s interval, double flash on the background overlay + brief cloud glow.
- Background: per-condition 3-stop gradients, transition = interpolation of stops (~600 ms, `OutCubic`), icon cross-fade, number roll.
- Icons drawn as vectors (stroke style from reference) so they scale with widget size and recolor with the Hub accent where appropriate.
- Respect Windows "animation effects off" (`animations_enabled()`): static scene, no particles.
- Hub preview: static painter (no timers), like the Timer's `paint_windows_timer`.

## 6. Phases

1. **Foundation:** `conditions.py` + tests, `weather_service.py` (fetch/cache/mock mode), config keys, controller + empty glass skin window with the card layout (static, sunny).
2. **Scenes:** sun, clouds, night, then rain (light/rain/heavy share one particle system, only intensity changes), storm, snow, fog.
3. **Transitions + day selector:** gradient morph, number roll, thumb slide, forecast-day switching.
4. **Hub integration:** overview card, page, settings, hotkey, i18n, tray/startup.
5. **Polish:** perf check, offline state, DPI/size scaling, snapshot tests, CHANGELOG.

A **debug/dev switch** (e.g. `dev_live.py` flag or a hidden Hub option) to force any condition without waiting for real weather — needed to review each scene.

## 7. Design-skill support

- `impeccable` is already installed in `.agents/skills`; its `animate`, `delight`, `polish` and `overdrive` commands cover motion/craft review. It targets web, so I'd use it for *direction* (timing, easing, hierarchy, critique of screenshots) while the implementation stays PySide6.
- Suggest creating a small project skill, `weather-motion`, that records the scene specs (colors, particle counts, durations, easing). That gives every scene a consistent reference across sessions.

## 8. Open questions

1. Location: manual city search only, or also automatic IP-based detection?
2. Units: °C default with a °C/°F toggle?
3. Forecast days: the reference shows 4–5 clickable days — keep this, or "today only" for v1?
4. Skins: only the reference "glass" skin for v1?
5. Hotkey default `Win+Alt+W` OK?
6. v1 scope: the 9 states above, or exactly your 7?
