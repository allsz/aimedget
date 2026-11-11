# Changelog

Todas as mudanças relevantes do Aimedget ficam registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

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

[1.0.1]: https://github.com/allsz/aimedget/releases/tag/v1.0.1
[1.0.0]: https://github.com/allsz/aimedget/releases/tag/v1.0.0
