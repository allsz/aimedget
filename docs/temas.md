# Temas do Aimedget — guia completo

Este guia ensina a criar **temas visuais** para os flyouts do Aimedget:

- **Caps/Num Lock** (o indicador que aparece ao apertar Caps Lock ou Num Lock) — chamado de `keylock` nos arquivos;
- **Volume e mixer** (o painel de volume com os aplicativos) — chamado de `mixer` nos arquivos.

Um tema **não é programa, é só dados**: um arquivo de texto (`theme.json`) e algumas imagens. Nada é executado.

Como ler este guia:

- **Designer** (você faz a arte e quer ver no app): leia as seções 1 a 5.
- **IA** (você recebe imagens de um designer e devolve o tema pronto): leia a seção 8 primeiro, depois use as
  seções 6 e 7 como referência. As regras duras estão marcadas com **[REGRA]**.

---

## 1. Resumo em um minuto

1. Crie uma pasta com um arquivo `theme.json` e as imagens ao lado dele.
2. Teste: `python tools/validate_theme.py <sua-pasta> --container keylock` (ou `mixer`). Ele diz o que está errado.
3. Para ver no app: junte as pastas num arquivo `.aimskin` (um zip) e use **Importar tema** na página do flyout.
4. Para compartilhar: use **Exportar tema** (gera o `.aimskin`) e envie o arquivo.

Exemplo mínimo (muda só as cores do Caps/Num Lock):

<!-- validar: keylock -->
```json
{
  "name": "Roxo Suave",
  "card_bg": "#3b1d4a",
  "border": "#6a3d82",
  "on_color": "#b46cff",
  "radius": 14
}
```

Tudo é opcional. O que você não escrever fica como o visual Padrão.

---

## 2. Onde ficam os temas e como o app os encontra

Cada tema é uma **pasta** dentro da pasta de temas do usuário:

```
%LOCALAPPDATA%\WindowsRedesign\themes\
  keylock\
    roxo-suave\            <- um tema do Caps/Num Lock
      theme.json
      fundo.png
      estrela.svg
  mixer\
    roxo-suave\            <- um tema do Volume e mixer
      theme.json
      fundo.png
```

- No Hub, em **Lock keys** e em **Volume & mixer**, cada tema vira um cartão com miniatura. Clique para usar.
- O botão **Abrir pasta de temas** abre essa pasta no Explorer.
- Um `theme.json` solto na raiz de `keylock\` ou `mixer\` aparece como "Personalizado" (formato antigo, ainda aceito).
- O nome mostrado no cartão é o campo `"name"` do `theme.json` (aceita espaços e acentos, até 40 letras). Sem `name`,
  aparece o nome da pasta.

---

## 3. O arquivo `theme.json`

Regras do arquivo:

- **[REGRA]** Texto **UTF-8**, formato JSON puro: aspas duplas `"`, **sem comentários**, **sem vírgula depois do último item**.
- **[REGRA]** Tudo é opcional. Valor inválido é **ignorado** (volta ao padrão) e o validador avisa.
- **[REGRA]** Chave com erro de digitação (`card_bgg`) é ignorada, e o validador avisa "chave desconhecida".
- Caminhos de imagem são **só o nome do arquivo** (ou subpasta), relativos à pasta do tema: `"fundo.png"`, `"img/estrela.svg"`.
  Nada de `C:\...`, nada de `..`.

### 3.1 Cores

Formato: `"#rrggbb"` ou `"#aarrggbb"` (com transparência). Também vale `"#rgb"`.

> **Atenção, armadilha:** a transparência vem **primeiro** (`#aarrggbb`), ao contrário do CSS (`#rrggbbaa`).
> `"#80000000"` = preto 50% transparente. `"#000000ff"` **não** é "preto opaco": o primeiro par (`00`) é a transparência,
> então ele é totalmente transparente. Para preto opaco escreva `"#000000"` ou `"#ff000000"`.

Nomes de cor (`"red"`, `"purple"`) **não** funcionam: sempre use `#`.

### 3.2 Chaves do Caps/Num Lock (`keylock`)

| Chave | Tipo | Padrão | O que muda |
|---|---|---|---|
| `name` | texto | — | Nome mostrado no Hub (até 40 letras) |
| `card_bg` | cor | `#f81e1e1e` | Fundo do cartão |
| `border` | cor | `#373737` | Borda de 1 px do cartão |
| `text` | cor | `#ffffff` | Texto "Caps Lock" / "Num Lock" |
| `icon` | cor | `#ffffff` | O cadeado |
| `off_color` | cor | `#29414d` | Barrinha de baixo com a tecla **desligada** |
| `on_color` | cor | `#4cc2ff` | Barrinha de baixo com a tecla **ligada** (cor de ativação) |
| `text_off` | cor | igual a `text` | Cor do nome com a tecla **desligada** (muda suavemente para `text` ao ligar) |
| `radius` | número 0–25 (até metade da altura, se usar `size`) | 8 | Arredondamento dos cantos (na altura 50, 25 vira pílula) |
| `scale` | número 0.75–3 | 1 | Aumenta o flyout inteiro (cartão, texto, cadeado, figurinhas) |
| `auto_scale` | `true`/`false` | `false` | Com `true`, `scale` vale para uma tela 1440p e se adapta às outras (1080p = 75%, 4K a 100% = 150%) |
| `shadow` | ver 3.4 | sombra original | Sombra suave do cartão |
| `background` | ver 3.5 | nenhum | Imagem de fundo do cartão |
| `stickers` | lista, ver 3.6 | nenhuma | Figurinhas (até 12) |
| `indicator` | `"bar"` ou `"none"` | `"bar"` | `"bar"` = barrinha colorida embaixo; `"none"` = sem barrinha (mostre o estado com uma figurinha `state`, 3.6) |
| `show_icon` | `true`/`false` | `true` | `false` esconde o cadeado |
| `label_align` | `"left"` ou `"center"` | `"left"` | `"left"` = ao lado do cadeado; `"center"` = no meio do cartão |
| `label_size` | número 8–40 | 14 | Tamanho da letra do nome da tecla |
| `label_case` | `"none"`, `"lower"`, `"upper"` | `"none"` | `"lower"` = "caps lock"; `"upper"` = "CAPS LOCK"; `"none"` = como o app escreve |
| `size` | `[largura, altura]` | automático | Tamanho fixo do cartão (largura 60–400, altura 30–200, em px antes de `scale`). Use quando a arte de fundo tem proporção própria |
| `container` | texto | — | Só em pacote com `theme.json` solto (seção 5) |

Medidas do cartão (em px, antes de `scale`): sem `size`, **altura 50** e largura ≈ 130–135 (depende do texto e do tamanho da
letra; um pouco menor sem o cadeado). A barrinha de baixo tem 3 px de altura: 36 px de largura desligada, 60 px ligada. Com `size`,
o cadeado e a barrinha ficam centralizados na altura nova, e o texto acompanha `label_align`.

**Tecla com cara própria (estilo "keycap")** — sem cadeado, sem barrinha, nome no meio e um LED que acende:

<!-- validar: keylock -->
```json
{
  "name": "Exemplo Keycap",
  "text": "#ffffff", "text_off": "#9a9aa0",
  "indicator": "none", "show_icon": false,
  "label_align": "center", "label_size": 18, "label_case": "lower",
  "size": [140, 52]
}
```

O nome continua sendo escrito pelo app (Caps Lock / Num Lock), com a letra, a cor e a caixa definidas pelo tema. Para um LED, use
figurinhas com `state` (veja 3.6): a imagem de fundo mostra o LED apagado e a figurinha `"state": "on"` o acende.

### 3.3 Chaves do Volume e mixer (`mixer`)

O mixer **não** tem `scale` nem `auto_scale` (usar `scale` aqui é "chave desconhecida").

| Chave | Tipo | Padrão | O que muda |
|---|---|---|---|
| `name` | texto | — | Nome mostrado no Hub |
| `card_bg` | cor | `#f81e1e1e` | Fundo do cartão |
| `border` | cor | `#373737` | Borda do cartão |
| `text` | cor | `#ffffff` | Números de volume |
| `muted_text` | cor | `#969696` | Números quando o áudio está mudo |
| `icon` | cor | `#ffffff` | Alto-falante e seta do cabeçalho |
| `accent` | cor | `#54aff4` | **Cor de ativação**: parte preenchida dos sliders, aba ativa (Saída/Entrada), destaque do ícone do app |
| `thumb` | cor | `#4db2ff` (acompanha `accent` se você só definir `accent`) | Miolo do botão do slider |
| `thumb_outer` | cor | `#454545` | Disco externo do botão do slider |
| `thumb_border` | cor | `#363636` | Borda desse disco |
| `track_inactive` | cor | `#999999` | Parte vazia do trilho do slider |
| `button_bg` | cor | `#2c2c2c` | Botão da seta (v / ^) |
| `button_hover` | cor | `#383838` | Idem, com o mouse em cima |
| `button_pressed` | cor | `#242424` | Idem, apertado |
| `button_border` | cor | `#343434` | Borda do botão da seta |
| `button_radius` | número 0–13 | 5 | Arredondamento do botão (13 = redondo) |
| `divider` | cor | `#313131` | Linha entre o cabeçalho e a lista de apps |
| `on_accent` | cor | `#ffffff` | Texto sobre a cor de ativação (aba ativa) |
| `switch_on` | cor | `#54aff4` (acompanha `accent`) | Interruptores de dispositivo ligados |
| `drawer_bg` | cor | `#fa242424` | Gaveta de roteamento (abre ao clicar no ícone de um app) |
| `drawer_border` | cor | `#363636` | Borda da gaveta |
| `tabs_bg` | cor | `#dc191919` | Trilho das abas Saída / Entrada |
| `tabs_border` | cor | `#323232` | Borda das abas |
| `radius` | número 0–25 | 8 | Arredondamento dos cantos do cartão |
| `shadow` | ver 3.4 | sombra original | Sombra suave do cartão |
| `background` | ver 3.5 | nenhum | Imagem de fundo |
| `stickers` | lista, ver 3.6 | nenhuma | Figurinhas (até 12) |
| `container` | texto | — | Só em pacote com `theme.json` solto (seção 5) |

Medidas do cartão (em px): **largura 240**; altura **50** recolhido, crescendo com a lista de apps até **370**. Por isso, no
mixer, prefira âncoras `top-*` e `bottom-*` nas figurinhas (a altura muda; ver 3.6).

Dica: se você só definir `accent`, o botão do slider e os interruptores acompanham. Defina `thumb` e `switch_on` só se quiser
cores diferentes.

### 3.4 Sombra do cartão (`shadow`)

- `true` — sombra discreta padrão.
- `false` ou ausente — a sombra original do app.
- Objeto — `{"color": "#9646198c", "blur": 13, "dy": 5}`:

| Campo | Limite | Significado |
|---|---|---|
| `color` | cor | Cor da sombra (use transparência: `#aarrggbb`) |
| `blur` | 0 a 60 | Quão espalhada/suave |
| `dy` | −60 a 60 | Deslocamento vertical (positivo = para baixo) |

### 3.5 Imagem de fundo (`background`)

```json
"background": {"image": "fundo.png", "fit": "cover", "opacity": 0.9}
```

| Campo | Valores | Significado |
|---|---|---|
| `image` | arquivo `.png`, `.jpg`, `.jpeg` ou `.webp` | **SVG não vale para fundo** |
| `fit` | `"cover"` (padrão) ou `"stretch"` | `cover` preenche e corta o excesso, sem deformar; `stretch` estica |
| `opacity` | 0 a 1 | Transparência da imagem sobre a cor `card_bg` |

A imagem é recortada pelo cartão arredondado. Se o tema usar `size`, o cartão tem proporção fixa: faça a arte **nessa proporção**
(`cover` corta o que sobrar). Como a largura do Caps (sem `size`) varia com o texto e a altura do mixer varia com os
apps, use `cover` e deixe as bordas da arte "sobrando". Tamanhos sugeridos: Caps ≈ 540×200 px; Mixer ≈ 480×740 px.

### 3.6 Figurinhas (`stickers`)

Imagens pequenas posicionadas em volta ou em cima do cartão. **Até 12** (as demais são ignoradas).

```json
"stickers": [
  {"image": "estrela.svg", "anchor": "top-right", "x": -4, "y": -6, "width": 22,
   "rotation": 15, "opacity": 1, "layer": "above", "shadow": true}
]
```

| Campo | Valores | Significado |
|---|---|---|
| `image` | `.png` `.jpg` `.jpeg` `.webp` **ou `.svg`** | **Obrigatório** |
| `anchor` | ver abaixo (padrão `center`) | Ponto do cartão a que a figurinha se prende |
| `x`, `y` | −200 a 200 (px) | Deslocamento a partir da âncora. `x` positivo = direita, `y` positivo = **para baixo** |
| `width`, `height` | 1 a 200 (px) | Tamanho. Informe **só um** para manter a proporção. Nenhum = tamanho original (limitado a 200) |
| `rotation` | −360 a 360 (graus) | Rotação no sentido horário |
| `opacity` | 0 a 1 | Transparência |
| `layer` | `"above"`, `"below"`, `"behind"` | Camada (veja abaixo) |
| `state` | `"always"`, `"on"`, `"off"` | **Só no Caps/Num Lock.** `"on"` = aparece só com a tecla ligada; `"off"` = só desligada; `"always"` (padrão) = sempre. A troca é suave (a figurinha aparece/some junto com a animação) |
| `shadow` | `true`, `false` ou `{"color","blur","dy"}` | Sombra de contato da própria figurinha (blur 0–20) |

**Âncoras** — o **centro** da figurinha fica no ponto da âncora, mais `(x, y)`:

```
top-left      top      top-right
left        center        right
bottom-left  bottom  bottom-right
```

A âncora acompanha o tamanho do cartão (largura variável no Caps; altura variável no mixer). A figurinha **pode passar da borda**
do cartão: o app aumenta a janela transparente sozinho para não cortar.

**Camadas:**

- `behind` — **atrás** do cartão (só a parte que sai pelas bordas aparece);
- `below` — por cima do fundo, **por baixo** do texto e dos controles;
- `above` — por cima de **tudo**, inclusive do texto (padrão).

Cuidado com `above` cobrindo o texto ou o slider: o app não evita isso.

**Figurinha por estado (LED, luz, brilho):** no Caps/Num Lock, uma figurinha com `"state": "on"` só aparece com a tecla ligada.
Desenhe o LED apagado no fundo e um LED aceso (com brilho) como figurinha `on`, na mesma posição:

```json
{"image": "led-aceso.svg", "anchor": "top-left", "x": 14, "y": 13, "width": 22, "state": "on", "layer": "above"}
```

`state` no mixer é ignorado e o validador avisa (o mixer não tem tecla ligada/desligada).

### 3.7 O que ainda **não** é possível (diga isso em vez de improvisar)

- **Mudar o formato do cartão além de tamanho e cantos** (formas irregulares, cartão fora do retângulo arredondado).
- **Arte diferente por tecla** (uma para Caps, outra para Num): o tema vale para as duas. O nome da tecla é sempre escrito pelo
  app; a imagem de fundo não deve conter o nome.
- **Trocar o cadeado por outro ícone animado**: dá para esconder (`show_icon`), ou desenhar outro como figurinha, mas sem a
  animação de abrir/fechar.
- **Fonte própria**: a letra é sempre a do app (só tamanho, cor e caixa mudam).
- **Animações novas** ou sons.
- **Mixer**: não tem `scale`, `size`, nem figurinhas por estado.

Se o desenho do designer pede algo desta lista, **avise** o que não dá para fazer e entregue a melhor aproximação, em vez de
entregar um tema "válido" que não se parece com o desenho.

---

## 4. Regras e limites dos arquivos

| Item | Regra |
|---|---|
| Tipos de arquivo | `.json`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`. Qualquer outro é ignorado (e listado na importação) |
| Imagem (png/jpg/webp) | até **5 MB** e **2048 px** de lado |
| SVG | até **1 MB**, tamanho declarado até **4096 px**, e precisa ter `width`/`height` ou `viewBox` |
| `theme.json` | até 256 KB |
| Pacote `.aimskin` | até **40 MB** (arquivo) e **40 MB** descompactado, até **120 arquivos**, subpastas até 4 níveis |
| Nomes de arquivo | sem `..`, sem `C:\`, sem `:`, sem `< > " | ? *`, sem nomes reservados do Windows (`CON`, `NUL`, `COM1`...), sem terminar em ponto ou espaço |

### Segurança do SVG

O SVG só pode referenciar **ele mesmo** (`#id`). É **recusado** (o validador diz "SVG recusado…") se tiver:

- `<script>`, `<foreignObject>` ou `<!ENTITY>`;
- `href`/`xlink:href` ou `url()` apontando para arquivo, internet ou **imagem embutida** (`data:...`).

**Armadilha comum:** Illustrator, Figma e Inkscape podem **embutir imagens bitmap** dentro do SVG (`<image href="data:image/png;base64,...">`).
Isso é recusado. Solução: exporte essa figurinha como **PNG**, ou converta tudo em curvas/formas vetoriais antes de exportar.
Converta também os **textos em curvas** (contornos), pois a fonte pode não existir em outro computador. Efeitos como
filtros e desfoque podem não aparecer: teste.

---

## 5. Pacote `.aimskin` (para importar e compartilhar)

Um `.aimskin` é um **zip** com outra extensão. Três formatos aceitos:

**A. Pacote para os dois flyouts** — duas pastas na raiz do zip:

```
meu-tema.aimskin
  keylock/theme.json  (+ imagens)
  mixer/theme.json    (+ imagens)
```

**B. Só um flyout** — apenas a pasta dele: `keylock/...` **ou** `mixer/...`.

**C. `theme.json` solto**, dizendo o flyout com `"container"`:

<!-- validar: mixer -->
```json
{
  "name": "Só Mixer",
  "container": "mixer",
  "accent": "#b46cff",
  "on_accent": "#ffffff"
}
```

Uma única pasta de embrulho em volta de tudo (`MeuTema/keylock/...`) também é aceita. **[REGRA]** Não misture o formato C com
as pastas `keylock/` e `mixer/` no mesmo pacote.

### Como criar o `.aimskin`

- **Recomendado, em um comando** (valida, empacota e confere que o pacote importa):

```
python tools/pack_theme.py <pasta> [-o meu-tema.aimskin] [--container keylock|mixer]
```

  `<pasta>` é a pasta do tema, ou a que contém `keylock/` e/ou `mixer/`. Se a validação achar erro **ou item ignorado**, nada
  é gerado (use `--allow-issues` só para empacotar assim mesmo). Ele avisa de imagens que o `theme.json` não usa e lista o que
  ficou de fora do pacote (tipos não permitidos, arquivos ocultos).
- **Manual, no Windows:** entre nas pastas, selecione **`keylock`** e/ou **`mixer`** (não a pasta de fora), clique com o botão direito →
  *Compactar para arquivo ZIP*, e renomeie de `.zip` para `.aimskin`.
- **Manual, em Python** (qualquer sistema):

```python
import zipfile, pathlib
raiz = pathlib.Path("meu-tema")          # contém as pastas keylock/ e/ou mixer/
with zipfile.ZipFile("meu-tema.aimskin", "w", zipfile.ZIP_DEFLATED) as z:
    for arq in raiz.rglob("*"):
        if arq.is_file():
            z.write(arq, arq.relative_to(raiz).as_posix())
```

### O que acontece ao importar

1. O app **analisa o pacote** sem instalar nada e mostra: o nome, o que será **aplicado**, o que será **ignorado e por quê**,
   e os arquivos que não serão instalados.
2. Você marca **um ou os dois** flyouts.
3. Se já existir um tema com o mesmo nome, o padrão é **Substituir e aplicar**. **Instalar como cópia** só vale depois de
   uma confirmação (o novo ganha o nome "Nome (2)").
4. O tema é instalado, selecionado e o flyout aparece para você testar.

O **id** do tema (nome da pasta) vem do `name`, sem acento e em minúsculas (`"Pôr do Sol"` → `por-do-sol`). Ele não aparece
para o usuário; mudar o `name` e importar de novo cria outro tema em vez de substituir.

Um pacote é **recusado inteiro** se tiver caminho absoluto, `..`, atalho/link, arquivo com senha, nomes repetidos, arquivos
demais, tamanho demais ou zip corrompido.

### Exportar

**Exportar tema** (na página do flyout) gera um `.aimskin` do tema **em uso** (marcado "EM USO"). Se existir um tema de mesmo
id no outro flyout, ele vai junto no mesmo pacote. O visual Padrão não se exporta.

---

## 6. O validador (linha de comando)

```
python tools/validate_theme.py <pasta> [--container keylock|mixer] [--json]
```

- `<pasta>`: a pasta do tema, ou a pasta que contém `keylock/` e `mixer/`.
- O flyout é deduzido pelo nome da pasta (`themes\keylock\meu-tema`); senão use `--container`.
- **Código de saída:** `0` tudo certo · `1` há problemas · `2` uso incorreto.
- `--json` imprime o relatório para máquinas (seção 8).

Saída de exemplo:

```
=== Caps/Num Lock — Roxo Suave ===
  Aplicado: card_bg, border, on_color, radius (2 figurinha(s))
  [IGNORADO] cor inválida em 'card_bg': 'azul' (use #rrggbb ou #aarrggbb; usando o padrão)
  [IGNORADO] figurinha 3: SVG recusado por referenciar arquivo externo, imagem embutida ou script: 'x.svg' (...)
  Resultado: o tema abre, mas 2 item(ns) acima foram ignorados.
```

- **`[ERRO]`**: o tema não pode ser usado (sem `theme.json`, JSON quebrado).
- **`[IGNORADO]`**: o tema abre, mas aquele valor **não vale** (volta ao padrão). Para um tema final, corrija **todos**.
- **Importante:** o validador confere **regras**, não **beleza**. Ele não vê se o texto está legível sobre a imagem nem se uma
  figurinha cobre o slider. Isso só se confere abrindo o tema no app.

---

## 7. Erros comuns: mensagem → causa → correção

| Mensagem (resumo) | Causa | Correção |
|---|---|---|
| `theme.json não é um JSON válido` | Vírgula sobrando no fim, aspas simples, comentário, aspas faltando | Corrija a sintaxe; teste em um validador de JSON |
| `precisa ser salvo em UTF-8` | Arquivo salvo em outra codificação | Salve como UTF-8 (sem ser "ANSI") |
| `cor inválida em 'X'` | Faltou `#`, nome de cor, tamanho errado | Use `#rrggbb` ou `#aarrggbb` |
| `'X' precisa ser um número` | Número entre aspas (`"14"`) | Escreva `14`, sem aspas |
| `'X' fora do limite … usando N` | Valor acima/abaixo do permitido | Use um valor dentro do limite da tabela |
| `chave desconhecida 'X'` | Erro de digitação, ou chave de outro flyout (ex.: `scale` no mixer) | Confira o nome na seção 3 |
| `imagem não encontrada: 'X'` | Nome diferente do arquivo (maiúsculas, extensão), arquivo fora da pasta | Confira o nome exato e se o arquivo está na pasta do tema |
| `formato não suportado em fundo` | SVG usado como fundo, ou extensão não permitida | Fundo só aceita png/jpg/jpeg/webp |
| `a imagem precisa ficar dentro da pasta do tema` | Caminho com `..` | Copie a imagem para a pasta do tema |
| `caminho absoluto não é permitido` | Caminho `C:\...` | Use só o nome do arquivo |
| `imagem muito grande` / `dimensões demais` | Mais de 5 MB ou 2048 px | Reduza e exporte de novo |
| `SVG recusado por referenciar arquivo externo, imagem embutida ou script` | SVG com `<image>`, `data:`, script | Exporte a figurinha como PNG, ou converta tudo em curvas |
| `SVG inválido ou sem tamanho definido` | Falta `width`/`height` ou `viewBox` | Adicione `viewBox="0 0 48 48" width="48" height="48"` |
| `figurinha N: 'anchor' inválido` | Âncora com nome errado | Use uma das 9 âncoras (seção 3.6) |
| `figurinha N: 'layer' inválido` | Camada errada | `above`, `below` ou `behind` |
| `figurinha N: 'state' inválido` | Valor diferente de `always`/`on`/`off` | Use um dos três |
| `'state' ... só existe no Caps/Num Lock` | `state` usado em figurinha do mixer | Tire o `state` ou use o tema do Caps |
| `'indicator'/'label_align'/'label_case' inválido` | Valor fora da lista | Veja as opções na tabela 3.2 |
| `'size' precisa ser [largura, altura]` | Formato errado (`"140x52"`, um número só) | Escreva `[140, 52]` |
| `no máximo 12 figurinhas` | Mais de 12 | Remova ou junte figurinhas |
| `'fit' inválido` | Valor diferente de `cover`/`stretch` | Use um dos dois |
| `'name' passa de 40 letras` | Nome comprido | Encurte |
| (importar) `o theme.json solto precisa dizer o flyout` | Formato C sem `container` | Adicione `"container": "keylock"` ou `"mixer"` |
| (importar) `não achei nenhum tema no pacote` | Faltam as pastas `keylock/` ou `mixer/` | Confira a estrutura da seção 5 |

---

## 8. Instruções para uma IA que recebe imagens de um designer

Objetivo: transformar as imagens do designer em um tema **válido e agradável**, entregue como pasta (e/ou `.aimskin`), sem
ignorar nada. Você **não vê o app**, então use o validador para as regras e peça ao humano para conferir a aparência.

### 8.1 Antes de começar, pergunte (se não estiver claro)

1. Para qual flyout: **Caps/Num Lock**, **Volume e mixer**, ou os **dois**?
2. Quais imagens são o **fundo** e quais são **figurinhas**? Onde cada figurinha deve ficar (cantos, topo, base)?
3. O clima: claro ou escuro? Cor principal? O nome do tema?
4. Se houver SVG: ele tem bitmap embutido? (Se sim, peça PNG.)

### 8.2 Passo a passo

1. Crie `keylock/` e/ou `mixer/`, cada uma com `theme.json`. Copie as imagens para dentro delas (nomes simples, minúsculos, sem
   espaços: `fundo.png`, `estrela.svg`).
2. Escreva o `theme.json` com **somente chaves da seção 3** (as do flyout certo).
3. Rode: `python tools/validate_theme.py <pasta> --container <keylock|mixer> --json` (ou aponte a pasta do pacote com as duas).
4. **Laço de autocorreção:** leia o JSON. Se `errors` ou `issues` não estiverem vazios, corrija **cada mensagem** usando a
   tabela da seção 7 e rode de novo. Repita até `"ok": true` em todos os alvos. Não entregue com `issues` pendentes.
5. Gere o `.aimskin` com `python tools/pack_theme.py <pasta> -o <saida>.aimskin` (ele valida de novo, recusa se sobrar
   qualquer `issue` e confere que o pacote importa). Se precisar montar o zip à mão, `keylock/` e `mixer/` ficam **na raiz do zip**.
6. Entregue e peça ao humano: *Importar tema → conferir a aparência → dizer o que ajustar*.

Saída do `--json` (uma lista, um item por flyout):

```json
[{"container": "keylock", "folder": "...", "name": "Roxo Suave", "ok": false,
  "errors": [], "issues": ["cor inválida em 'card_bg': 'azul' (...)"],
  "applied": ["card_bg", "radius"], "sticker_count": 2}]
```

`ok` só é `true` com `errors` **e** `issues` vazios. `applied` lista o que realmente valeu (se estiver vazio, o tema ficaria
igual ao padrão: algo está errado).

### 8.3 Regras duras

- **[REGRA]** Use **apenas** as chaves e valores da seção 3. Não invente chaves.
- **[REGRA]** Cores sempre `#rrggbb` ou `#aarrggbb` (**alfa primeiro**). Nunca nomes de cor, nunca `rgba()`.
- **[REGRA]** Números sem aspas. Respeite todos os limites. Máximo 12 figurinhas.
- **[REGRA]** Caminhos de imagem relativos, só o nome do arquivo ou subpasta. Nunca `..` nem `C:\`.
- **[REGRA]** Fundo: png/jpg/jpeg/webp (nunca SVG). Figurinha: também aceita SVG.
- **[REGRA]** Se o SVG do designer tiver bitmap embutido, script ou referência externa, **não o use**: peça PNG.
- **[REGRA]** O mixer **não** tem `scale`/`auto_scale`/`size`, e `state` em figurinha só vale no Caps/Num Lock.
- **[REGRA]** Se o desenho pedir algo da seção 3.7, avise em vez de inventar chave.
- **[REGRA]** Não coloque no pacote nada além de `theme.json` e as imagens usadas. Não inclua arte que você não recebeu.
- **[REGRA]** Sempre inclua `"name"` (o nome que o usuário verá).
- **[REGRA]** Não afirme que ficou bonito sem o humano ver: o validador não mede aparência.

### 8.4 Como escolher valores (heurísticas)

- **Contraste:** `text` e `icon` contra `card_bg` (ou contra a imagem de fundo) com razão ≥ 4,5:1. Fundo claro → texto escuro;
  fundo escuro → texto claro. Se há `background`, escolha as cores olhando para a **imagem**, pois ela cobre o `card_bg`.
- **Cor de ativação:** use a cor mais viva/saturada da arte para `on_color` (Caps) e `accent` (mixer). `off_color` deve ser
  claramente mais apagada que `on_color` (a barrinha tem só 3 px: precisa dar para distinguir ligado de desligado).
- **Bordas:** `border` um pouco mais clara ou mais escura que `card_bg`; com fundo de imagem, costuma ficar bom uma borda
  semitransparente (`#33ffffff`).
- **Mixer completo:** além de `accent`, ajuste `track_inactive` (trilho vazio), `thumb_outer`/`thumb_border`, `button_*`,
  `divider`, `drawer_*`, `tabs_*` e `on_accent` para combinar. Texto sobre `accent` (`on_accent`) precisa de contraste.
- **Figurinhas:** tamanhos úteis ficam entre 14 e 40 px. No Caps (altura 50), figurinhas de 18–30 px nos cantos funcionam
  bem. Use `top-*`/`bottom-*` no mixer. Para a figurinha "espiar" por cima do canto: âncora do canto, `x`/`y` pequenos e
  negativos para o lado de fora (`top-right` com `x: -4, y: -6`).
- **Não cubra o conteúdo:** no Caps, o cadeado fica à esquerda e o texto no meio; no mixer, os sliders ocupam o centro. Prefira
  `behind`/`below` ou cantos/bordas para figurinhas grandes.
- **Sombra:** cor com alfa (`#aarrggbb`), `blur` 8–24, `dy` 3–9 combina com cartões flutuantes. Tom da sombra pode seguir a
  cor da arte (ex.: roxo escuro translúcido em vez de preto).
- **Tecla sem cadeado e sem barrinha:** use `indicator: "none"`, `show_icon: false`, `label_align: "center"` e `size` com a
  **mesma proporção** da imagem de fundo (ex.: arte 1080×400 → `[140, 52]`). Desenhe o LED/luz **apagado** no fundo e entregue o
  LED **aceso** como figurinha `"state": "on"` (SVG ou PNG com brilho). `text_off` mais apagado que `text` reforça o estado.
- **Escala no Caps:** `scale` 1.2–1.5 com `auto_scale: true` deixa o flyout maior e proporcional em qualquer tela.

### 8.5 Exemplo completo — Caps/Num Lock com arte

<!-- validar: keylock -->
```json
{
  "name": "Lavanda",
  "card_bg": "#3b1d4a",
  "border": "#6a3d82",
  "text": "#ffffff",
  "icon": "#ffffff",
  "off_color": "#8a6aa8",
  "on_color": "#ffffff",
  "radius": 14,
  "scale": 1.4,
  "auto_scale": true,
  "shadow": {"color": "#9646198c", "blur": 13, "dy": 5},
  "background": {"image": "fundo.png", "fit": "cover", "opacity": 0.9},
  "stickers": [
    {"image": "estrela.svg", "anchor": "top-right", "x": -4, "y": -6, "width": 22, "layer": "above", "shadow": true},
    {"image": "estrela.svg", "anchor": "bottom-left", "x": 6, "y": 6, "width": 16, "rotation": -15, "layer": "above"},
    {"image": "personagem.png", "anchor": "left", "x": -8, "width": 34, "layer": "behind"}
  ]
}
```

### 8.6 Exemplo completo — Volume e mixer

<!-- validar: mixer -->
```json
{
  "name": "Lavanda",
  "card_bg": "#3b1d4a",
  "border": "#6a3d82",
  "text": "#ffffff",
  "muted_text": "#b9a3c9",
  "icon": "#ffffff",
  "accent": "#b46cff",
  "thumb_outer": "#ffffff",
  "thumb_border": "#6a3d82",
  "track_inactive": "#7d5a96",
  "button_bg": "#4d2a5e",
  "button_hover": "#5c3571",
  "button_pressed": "#3b1d4a",
  "button_border": "#6a3d82",
  "button_radius": 8,
  "divider": "#69ffffff",
  "on_accent": "#2b0f3a",
  "drawer_bg": "#e65a2d96",
  "drawer_border": "#8a5aa8",
  "tabs_bg": "#cc2b0f3a",
  "tabs_border": "#6a3d82",
  "radius": 14,
  "shadow": {"color": "#9646198c", "blur": 22, "dy": 9},
  "background": {"image": "fundo.png", "fit": "cover"},
  "stickers": [
    {"image": "estrela.svg", "anchor": "top-right", "x": -4, "y": -6, "width": 22, "shadow": true},
    {"image": "personagem.png", "anchor": "bottom-left", "x": 10, "y": 8, "width": 36, "layer": "above"}
  ]
}
```

### 8.7 Checklist final (antes de entregar)

- [ ] Validador com `"ok": true` em todos os alvos.
- [ ] `"name"` presente, com até 40 letras.
- [ ] Só `theme.json` + imagens usadas em cada pasta; nenhum arquivo extra, nenhum SVG com bitmap embutido.
- [ ] `.aimskin` com `keylock/` e/ou `mixer/` na **raiz** do zip.
- [ ] Você avisou que a aparência (contraste, figurinha cobrindo o conteúdo) precisa ser conferida no app.
