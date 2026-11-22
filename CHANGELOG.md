# Changelog

Todas as mudanças relevantes do Aimedget ficam registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [1.1.1] - 2026-11-22

### Adicionado
- Bateria: novos dispositivos. **Switch Pro Controller** por Bluetooth (inclui o 8BitDo Pro 3 no modo Switch; 4
  níveis, então aproximado), **mouses VXE/ATK** pelo dongle ou pelo cabo (porcentagem exata e carregando) e
  **qualquer dispositivo Bluetooth** que informe a carga ao Windows (fones, dispositivos LE).
- Bateria: com algo carregando, a leitura passa a cada 15 s (antes 60 s), então a carga sobe na tela e o "cheio"
  aparece logo.
- Item **Configurar** no menu de todos os widgets: abre o Hub na página do widget.
- Atalhos: aviso antes de usar uma combinação que o Windows já usa ("Usado pelo Windows: ..."); só é salva depois
  de "Substituir".
- Cronômetro mostra MM:SS:cc e passa a HH:MM:SS em 1 h, com transição animada.

### Alterado
- Bateria: dispositivos ligados ou desligados aparecem e somem em poucos segundos (antes até 1 minuto). O ponto de
  carregando cresce e some com movimento, e o nome desliza junto.
- Bateria: um mouse VXE dormindo sai do cartão, como os da Logitech, em vez de ficar cinza.
- O atalho padrão da Bateria passa a ser **Win+Alt+E** (Win+Alt+B liga e desliga o HDR do Windows).
- Capas de música ficam guardadas por álbum: as faixas de um álbum não baixam a mesma imagem de novo, e capas iguais
  aparecem na hora.
- O mixer de volume fica sempre branco, com um halo suave que o mantém legível em qualquer fundo.
- Clima no Hub: as opções da previsão ficam juntas num cartão só.
- O tamanho dos widgets sai do menu de contexto e fica só no Hub.

### Corrigido
- Bateria: carga que ia e voltava entre dois níveis, ou piscava entre "carregando" e "cheio" no fim da carga.
- Música: um quadro de clipe enviado pelo player podia virar a capa do álbum inteiro; a capa da busca online agora
  tem prioridade.
- O mixer de volume abria por cima do painel do Windows ao trocar para um fone Bluetooth.
- Ancoragem: o brilho segue o contorno real do cartão (quadrado, estrela, skins em imagem), e um widget que sai do
  meio de um grupo não deixa mais um buraco nele.
- Skins em imagem podiam fechar o app ao abrir.

## [1.1.0] - 2026-11-20

### Adicionado
- **Widget de Clima** (Win+Alt+W): previsão de 5 dias clicáveis com céu animado para 10 condições (ensolarado,
  céu limpo à noite, parcialmente nublado, nublado, neblina, chuva fraca, chuva, chuva forte, tempestade e neve).
  Trocar de dia anima o fundo, o ícone, os números e o nome do dia. Dados da Open-Meteo, com local automático
  (pela conexão) ou cidade buscada no Hub, °C ou °F e skins por fonte (`assets/fonts/weather`).
- Clima: redimensionar arrastando o canto (o tamanho fica salvo) e **Fixar na área de trabalho**, que deixa o
  cartão no nível do papel de parede, atrás de qualquer janela. A troca passa por uma onda de pontos na diagonal
  e o cartão "assenta" com uma sombra menor, sem o quadro preto de antes. Fixado, o cartão continua na tela depois
  do Win+D e do "espiar a área de trabalho", como as skins do Rainmeter, e convive com elas. Sem fixar, o Win+D o
  esconde junto com as janelas e ele volta quando a área de trabalho é recolhida.
- Clima: até **5 cidades** (incluindo "Minha localização"). A roda do mouse sobre o cartão troca de cidade (dá a
  volta na lista), Ctrl+roda muda o tamanho, ↑/↓ também trocam, e o menu tem "Cidade". Pontos ao lado do nome
  mostram a posição; o dia escolhido é mantido. No Hub, a lista de cidades se reordena arrastando. Uma única
  consulta atualiza todas as cidades. Remover uma cidade vira um check na cor de destaque antes de ela subir e
  sumir; uma cidade nova entra abrindo espaço e subindo de um desfoque.

- Novos widgets de **Desempenho**, **Armazenamento** e **Bateria**, com skin Nothing Dot e temas; **ancoragem** entre
  widgets (rede de proximidade, ímã e alinhador) e **Fixar na área de trabalho** em todos os widgets.

### Alterado
- Esconder um widget de um grupo ancorado (atalho, menu, Hub) fecha o espaço: os outros deslizam para junto e,
  quando ele volta, o lugar reabre igual. O lado do grupo junto à borda da tela fica parado.
- Trocar de tema agora tem a mesma transição curta e discreta em todo o app (a do Clima): música, timer, mixer e o
  claro/escuro do Hub dissolvem em vez de mudar no corte.

### Corrigido
- Ao abrir o app, dezenas de janelas pequenas piscavam na tela antes do Hub aparecer.
- Desligar o mixer de volume agora devolve as teclas de volume ao Windows (o painel nativo volta a aparecer).
- Escolher a posição de um widget ancorado no Hub agora o tira do grupo: arrastá-lo depois não leva mais os
  outros junto.
- Mixer de volume com tema de número em imagem: a gaveta de dispositivos abre abaixo do número, sem cobri-lo.
- Cor de destaque: o anel do círculo de tema não ganha mais só um arco novo antes do resto; ele muda inteiro, na onda.
- O brilho do modo ancorado podia ficar levemente aceso depois de desancorar.
- Filtrar a Visão geral não solta mais os cartões como janelas por um instante.

### Desempenho
- Um relógio de quadros único move todas as animações (de ~600 para ~120 despertares por segundo com 5 widgets
  animando); as skins de música seguem a taxa do monitor e só redesenham quando a barra ou o tempo mudam.
- A página Música abre sem travar na primeira visita (108 ms para 27 ms).
- Com o indicador de Lock Keys desligado, o app deixa de consultar o teclado 40 vezes por segundo.

## [1.0.5] - 2026-11-15

### Adicionado
- **Cor de destaque do Hub** com seletor em onda: a colina acompanha o botão ao arrastar e a cor nova é "pintada"
  pela janela, como uma barra de progresso. O ícone do app e da bandeja seguem a cor escolhida.
- **Mixer de volume com tema**: temas podem mudar a forma do painel (inclinação, placas, barras e algarismos em
  imagem), e as miniaturas da galeria ficam mais nítidas.
- Movimento mais suave: widgets deslizam ao mudar de posição, o Timer aparece e some com fade e os efeitos
  usam a taxa de atualização do monitor.

### Alterado
- **Music Player**: só música confirmada abre o widget sozinha. Vídeos, lives e abas ambíguas ainda aparecem se
  você abrir o widget, mas não o abrem por conta própria.
- Botões de ação do Hub mais curtos (só o verbo), com a frase completa na dica e na acessibilidade.
- A galeria de temas expande e recolhe de forma mais lenta e suave.
- Skins do Timer agora são pacotes genéricos encontrados na pasta, não uma skin embutida com nome fixo.

### Corrigido
- **Mixer de volume**: sem o flash ao expandir, a roda do mouse funciona sobre os controles dos apps e clicar
  fora recolhe o painel. O nome "Sons do Sistema" na dica do ícone agora segue o idioma.
- **Seletor de cor**: a onda continuava parada se você pausasse o mouse no meio do arrasto.
- **Music Player**: um sinal atrasado da capa não causa mais erro depois de o visual ser trocado.

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
