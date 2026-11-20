# Handoff (2026-11-19)

## Branch stack (cada uma parte da anterior; a ponta `docs/handoff-1.0.5` tem tudo)
`dev/1.0.5` -> `feature/core/desktop-layer` -> `feature/hub/motion-components` -> `feature/widgets/performance`
-> `feature/widgets/weather` -> `feature/hub/widget-integration` -> `chore/dev-tooling` -> `docs/handoff-1.0.5`

Só a ponta roda inteira: i18n, service_bridge, hub_window, pages e config_manager misturam as duas features, então
a fiação ficou numa branch própria (`widget-integration`) em cima das demais. Nas branches intermediárias, o Hub
ainda não conhece as páginas novas.

## A fazer
1. **Ancoragem** (pendente): os cartões Clima/Desempenho ainda não ancoram como o Music/Timer
   (`ConfigManager.get_osd_anchor`/`set_osd_anchor`, `app/core/osd_anchor.py`, `position_picker.py`).
2. **Refinar animações** antes de gerar release (ver CLAUDE.md, seção Movimento).
3. Corrigir os achados abaixo.

## Testes (`python -m pytest --ignore=tests/test_pack_theme.py`): 911 passam, 3 falham
- `test_accent_motion::HueSliderWaveTests::test_the_knob_ring_is_never_clipped_at_the_ends_of_the_bar`
  (anel toca a borda em y=0; rodado em `QT_QPA_PLATFORM=offscreen`, ver se também falha no modo normal).
- `test_weather::TestShowDesktopGuard::test_card_left_above_an_app_goes_back_down` e
  `TestResizeAndDesktopLayer::test_desktop_mode_keeps_card_under_other_windows`: esperam o estilo
  WS_EX_TOPMOST/camada do desktop, que vem 0 no offscreen. Provável limitação do ambiente; confirmar numa sessão normal.

## Varredura de bugs e custo (parcial: leitura dirigida, não auditoria completa)
- **fps_service (`_read_loop`)**: a thread leitora de um PresentMon antigo grava em `self._samples` sem checar se
  `proc` ainda é o atual. Depois de trocar de jogo, linhas restantes do processo antigo podem sujar as amostras do novo
  alvo (`_stop_reader.clear()` reabre a porta). Corrigir comparando `self._proc is proc` dentro do lock.
- **fps_service**: `except Exception: pass` no laço de leitura engole o erro e a leitura para em silêncio;
  logar e/ou reiniciar.
- **Dois timers de 250 ms por cartão** (`desktop_pin_guard` + `show_desktop_watcher`) chamando Win32 mesmo com o
  cartão parado. Dá para unificar num só timer (e pausar quando o cartão está oculto).
- **Weather `card_painter`**: o pixmap de texto é redesenhado a cada quadro durante qualquer troca (`force`); a camada
  "soft" do céu é repintada a cada quadro. Conferir uso de CPU com animações longas e, se alto, limitar a taxa.
- **Hub**: `page_transition` e `city_list` usam `grab()` de widgets inteiros por navegação/arraste (custo pontual,
  aceitável; revisar em telas 4K).
- Não revisados ainda: `weather_service` (rede, cache, tratamento de offline), `performance_service`, `i18n` das novas
  chaves, vazamentos de widgets em `city_list`.
