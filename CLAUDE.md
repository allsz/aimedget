# Aimedget: instruções para o Claude

## Movimento (obrigatório em toda mudança de interface)

Nada na interface muda de estado "no corte". Toda vez que algo aparece, some, troca de lugar, muda de tamanho ou de
estado (lista, chip, botão, página, cartão, widget), a mudança tem movimento. O usuário não deveria ter que conferir
item por item: antes de dar uma tarefa de UI por terminada, revise cada mudança de estado que ela introduz e anime as
que estiverem secas.

- **Referência:** https://designbookmark.com/motion. Molas no modelo de lá (massa 1, Euler semi-implícito, 4
  subpassos): veja `Spring` em `app/hub/components/city_list.py`. Valores já usados: MORPH 320/20, PRESS 520/20,
  LIFT 260/24, GAP 280/22, LIFT_UP 520/30, SLIDE 420/34, SETTLE 380/30, CLOSE 280/34 (fechar/reabrir fileiras de
  um grupo de ancoragem, sem passar do ponto; `app/core/anchor_manager.py`). Curvas: `app/widgets/weather/motion.py`.
  Troca de área de trabalho virtual: `SlideFadeAnimator.sweep` (sai 24 px com os apps em 144 ms, volta do lado
  oposto com a SLIDE; protótipo `mockups/virtual-desktop-switch.html`, variação B).
- **Troca de tema/aparência:** escolher um tema = `theme_crossfade` (160 ms, saída cúbica). Trocar o MODO claro/escuro
  (manual ou seguindo o Windows) = `mode_crossfade` (300 ms, in-out, sem encolher; cartões flutuantes:
  `begin_skin_crossfade(MODE_DURATION_MS, mode_switch=True)`), com a barra de título nativa do Hub mudando de cor
  junto, quadro a quadro (`app/core/theme_crossfade.py`, protótipo `mockups/theme-mode-transition.html`, variante C).
- **Exemplos prontos no app:** entrada "Unfold and rise", remoção com check, arrastar para reordenar (levanta, as
  vizinhas deslizam, assenta) em `city_list.py`; onda de pontos e assentar do cartão no Weather Widget.
- **Respeite o Windows:** com `animations_enabled()` (app/core/widget_animator.py) falso, tudo acontece na hora.
- **Movimento novo ou de gosto discutível:** primeiro um protótipo HTML em `mockups/` com controles (velocidade,
  variações, câmera lenta) para o usuário escolher; só depois implementar com os valores escolhidos.
- **Vizinhos juntos:** quando algo anima dentro de um layout, tudo o que muda na MESMA atualização (botões que
  aparecem/somem, rótulo de vazio, resultados de busca, contadores) anima na mesma linha do tempo. Um vizinho que
  some "no corte" enquanto a linha ainda abre faz o cartão encolher e crescer de novo (tremida). Antes de terminar,
  confira: a altura total do contêiner deve variar sem dente (só cresce ou só diminui) durante a animação.
- **Teste:** um teste que confirme que anima (não pula) e que termina limpo, mais o caso sem animações. Para listas,
  inclua a altura do contêiner pai ao longo da animação (sem encolher-e-crescer).

## Textos e rótulos de opções (obrigatório em toda opção nova)

O app adota redação minimalista e precisa (veja a skill completa em `.agents/skills/ui-copy-guidelines/SKILL.md`):

- **Sem subtítulo redundante:** se o título + controle (chips, switch, slider) já explicam a opção, deixe o subtítulo
  vazio (`""`), como em `Unidade de temperatura`, `Fonte do cartão` e `Fonte da previsão`.
- **Subtítulo curto quando necessário:** no máximo 1 frase curta (3–8 palavras) dizendo a consequência prática — nunca
  repita o título nem comece com "Escolha qual..." / "Permite...".
- **Detalhes extras no `HelpBadge` (`?`):** dicas condicionais ou explicações adicionais vão em `help_key` (`HelpBadge`),
  nunca inflam o cartão.
- **Zero jargão interno:** não exponha nomes de APIs/bibliotecas (`Open-Meteo`, `GSMTC`, etc.) nem termos de código em
  rótulos voltados ao usuário.
- **Botões e chips:** 1–2 palavras no máximo; paridade natural entre `pt` e `en` em `app/core/i18n.py`.

## Espaçamento e peças padrão do Hub (obrigatório)

- **Nada de número solto:** espaçamentos e margens vêm de `app/hub/ui_tokens.py` (`CARD_MARGINS`, `ROWS_GAP`,
  `INLINE_GAP`, `CHIP_GAP`, `STACK_GAP`, ...). Precisa de um valor novo? Crie o token lá, com comentário dizendo onde
  se usa; nunca um `setSpacing(7)` na página.
- **Peças prontas:** cartão, título+subtítulo, divisor, linha com switch e chip vêm de `BaseHubPage` (`_card`,
  `_info`, `_divider`, `_switch_row`, `_chip`); nunca recopie essas funções numa página. Botões lado a lado sempre em
  `chip_row(...)` (`app/hub/components/chips.py`), que já traz o vão.
- **Um dono por vão:** o espaço entre dois itens pertence ao layout pai. Um item não põe margem em volta de si. Exceção:
  vão que abre/fecha junto com o item (`Fold`, linhas da `CityList`) fica dentro dele, e o vizinho desconta (ex.:
  `STACK_GAP - LIST_ROW_GAP`).

## Armadilhas do Qt já encontradas

- Widget fixado no desktop tem o desktop como janela dona (`desktop_layer.ensure_desktop_owner`). O Qt zera a dona
  ao mostrar a janela (depois do `showEvent`), então o vínculo é refeito logo em seguida pelo `DesktopPinGuard`. E o
  gancho de WM_WINDOWPOSCHANGING só reescreve subidas (HWND_TOP etc.): reescrever o movimento que o Windows faz
  levando o widget junto com o desktop o deixava atrás dele (piscada).
- Nunca `setParent(None)` em widget visível: ele vira uma janela solta por um instante, fora do Hub. Use
  `hide()` + `removeWidget()` + `deleteLater()`.
- Rodar a suíte: `python -m pytest --ignore=tests/test_pack_theme.py` (esse arquivo abre um diálogo nativo). O
  `pytest.ini` limita a coleta a `tests/`: scripts soltos em `scratch/` rodam ao serem importados, e um deles já
  apagou o desenho de `assets/icons/aimedget_icon_clean.svg`. Nunca reescreva assets a partir de script de rascunho.
