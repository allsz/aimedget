# Changelog

Todas as mudanças relevantes do Aimedget ficam registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [1.0.4] - 2026-11-11

### Corrigido
- **Timer**: ao abrir o menu de contexto (clique direito), o widget perdia as cores do tema (destaque, borda e
  botões voltavam ao padrão) e ficava com bordas escuras. O menu agora usa só as cores do Windows/Hub, legível
  também no modo claro, e o widget mantém o tema.
- **Mixer de volume**: o nome do app que aparece ao passar o mouse no ícone podia piscar ao cruzar o espaço
  entre dois ícones. Agora some com um pequeno atraso e só troca o texto ao passar para outro ícone.
- O título da skin do **Timer** ficava em inglês ("Default") depois de trocar o idioma para português, e vice-versa.

### Adicionado
- **Modo Alarme no Timer** (clique direito, Modo): você escolhe um horário e o widget conta até ele, hoje ou
  amanhã se já passou. Funciona pelo relógio do sistema, então toca certo mesmo se o PC dormir. Pausar desarma e
  reiniciar zera o horário, como no Temporizador.
- **Excluir temas pelo Hub** ("Excluir tema..." na galeria de cada widget), com confirmação e a opção de
  exportar antes. Se o tema excluído estava em uso, o visual volta ao Padrão. O Padrão, o Windows e os temas que
  vêm com o app não podem ser excluídos.

### Alterado
- O **Timer**, o menu de contexto do **Music Player** e o texto "sem mídia" agora seguem o idioma do app
  (português e inglês).
- Se o tema escolhido for apagado direto da pasta, o app volta ao padrão e grava a escolha, em vez de repetir o
  aviso no console a cada abertura.

## [1.0.3] - 2026-11-11

### Corrigido
- **Music Player com o Firefox**: músicas tocando no Firefox (ex.: YouTube Music) não eram reconhecidas.
- **Vídeos do YouTube Music** (faixas enviadas por canais, sem capa oficial) eram ignorados e o widget mostrava
  "Nenhuma mídia ativa". Agora aparecem com título e artista; a capa oficial é buscada online e, se não for
  encontrada, fica a capa padrão (em vez do quadro do vídeo ou da capa da música anterior).
- **Barra de progresso** que nascia adiantada ou dava saltos na troca de faixa quando o player envia a posição da
  faixa anterior junto com o título novo (Firefox). Agora ela recomeça do zero até chegar a posição da nova faixa.
- **Importar tema** com um widget aberto por cima: o seletor de arquivos podia ficar atrás do widget, com os cliques
  bloqueados e o som de erro do Windows. Agora o seletor abre na frente, e os widgets continuam clicáveis e
  arrastáveis enquanto ele está aberto.

### Alterado
- Instalações novas seguem o **tema do Windows** (claro ou escuro) em vez de começar no modo claro.
- O seletor de importar/exportar temas **lembra a última pasta usada** também depois de fechar o app.
- Texto da opção de verificar atualizações: "Consulta automática uma vez ao dia, e pergunta antes de atualizar."
- O nome **Aimedget** aparece no preview da barra de tarefas (a janela continua sem título visível) e na dica do
  ícone da bandeja, que antes dizia "Aimedget Suite".

### Adicionado
- **Fechar widget** no menu de contexto do Music Player (clique direito), como já existia no Timer. Fechar assim
  não reabre o widget sozinho enquanto a mesma música continua tocando.
- Ícone **?** na página do **Caps/Num Lock** explicando que alguns notebooks (Lenovo, Dell, HP, ASUS...) mostram um
  indicador próprio do fabricante junto com o do Aimedget, e que ele precisa ser desativado no sistema do notebook.
- Ícone **?** na página do **Music Player** avisando que, com o YouTube Music no **Firefox**, o estado de
  play/pausa e a barra de progresso podem atrasar ou saltar (o Firefox informa esses dados com atraso); no Chrome
  e em players de desktop o widget funciona normalmente.

## [1.0.2] - 2026-11-11

### Corrigido
- **Encerrar** na bandeja às vezes só escondia a janela do Hub e deixava os widgets abertos, exigindo um segundo
  Encerrar. Agora fecha tudo de uma vez.
- O **X** da janela com "Manter na bandeja" desligado fechava só o Hub e deixava os widgets rodando; agora encerra o
  app inteiro. Com a opção ligada, continua só escondendo o Hub.

### Adicionado
- O tema **Keycap Digital** do Caps/Num Lock vem com o app (aparece na galeria de temas na primeira abertura).

## [1.0.1] - 2026-11-11

### Adicionado
- **Verificar atualizações automaticamente** (Geral > Atualizações): ligado por padrão, consulta o GitHub ao abrir o
  app no máximo uma vez por dia e **pergunta antes de atualizar**. Com o Hub na bandeja, avisa por um balão e a
  pergunta aparece ao clicar. "Agora não" não pergunta de novo pela mesma versão. Pode ser desligado; o botão
  "Verificar agora" continua funcionando.

### Alterado
- A skin do Timer e o tema embutido agora se chamam **Padrão** (antes "Aimedget").
- O indicador de Caps/Num Lock tem versão clara do visual embutido quando o app está no modo claro.
- Skin **Ecos da Capa**: ícones de aleatório e repetir redesenhados, nítidos em qualquer escala.

### Corrigido
- Desinstalar com o Aimedget aberto (na bandeja) deixava a pasta do app para trás; agora o desinstalador fecha o
  app antes e remove tudo.

## [1.0.0] - 2026-11-11

Primeira versão pública.

### Adicionado
- **Music Player**: widget com as skins Vinil Retrô, Capa Completa, Ecos da Capa e Capa Empilhada; capa em alta
  resolução, volume do player pela roda do mouse, escala automática conforme a resolução da tela.
- **Volume & mixer**: flyout de volume com mixer por aplicativo e saída/entrada de áudio por app.
- **Caps / Num Lock**: indicador na tela ao alternar as teclas.
- **Timer & Foco**: timer e cronômetro com som de fim.
- **Hub**: temas claro/escuro/OLED/sistema, cor de destaque, português e inglês, iniciar com o Windows, atalhos
  configuráveis e posição de cada flyout em 8 pontos da tela (empilhados quando dividem a mesma posição).
- **Temas visuais** para os flyouts e widgets, importáveis e exportáveis (`.aimskin`).
- **Atualização automática** pelo instalador, com conferência do SHA-256 do download.
- Instalador por usuário (sem administrador) e versão portátil.

[1.0.4]: https://github.com/allsz/aimedget/releases/tag/v1.0.4
[1.0.3]: https://github.com/allsz/aimedget/releases/tag/v1.0.3
[1.0.2]: https://github.com/allsz/aimedget/releases/tag/v1.0.2
[1.0.1]: https://github.com/allsz/aimedget/releases/tag/v1.0.1
[1.0.0]: https://github.com/allsz/aimedget/releases/tag/v1.0.0
