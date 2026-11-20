# Aimedget: instruções para o Claude

## Movimento (obrigatório em toda mudança de interface)

Nada na interface muda de estado "no corte". Toda vez que algo aparece, some, troca de lugar, muda de tamanho ou de
estado (lista, chip, botão, página, cartão, widget), a mudança tem movimento. O usuário não deveria ter que conferir
item por item: antes de dar uma tarefa de UI por terminada, revise cada mudança de estado que ela introduz e anime as
que estiverem secas.

- **Referência:** https://designbookmark.com/motion. Molas no modelo de lá (massa 1, Euler semi-implícito, 4
  subpassos): veja `Spring` em `app/hub/components/city_list.py`. Valores já usados: MORPH 320/20, PRESS 520/20,
  LIFT 260/24, GAP 280/22, LIFT_UP 520/30, SLIDE 420/34, SETTLE 380/30. Curvas: `app/widgets/weather/motion.py`.
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

## Armadilhas do Qt já encontradas

- Nunca `setParent(None)` em widget visível: ele vira uma janela solta por um instante, fora do Hub. Use
  `hide()` + `removeWidget()` + `deleteLater()`.
- Rodar a suíte: `python -m pytest --ignore=tests/test_pack_theme.py` (esse arquivo abre um diálogo nativo). O
  `pytest.ini` limita a coleta a `tests/`: scripts soltos em `scratch/` rodam ao serem importados, e um deles já
  apagou o desenho de `assets/icons/aimedget_icon_clean.svg`. Nunca reescreva assets a partir de script de rascunho.
