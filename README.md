# Aimedget

Widgets e flyouts para o Windows 10 e 11, com a cara do Windows 11 e personalização de verdade: um player de música
na área de trabalho, um mixer de volume por aplicativo, o indicador de Caps/Num Lock e um timer, todos configurados
por um único app, o **Hub**.

## O que vem nele

- **Music Player** — widget que mostra e controla o que está tocando (Spotify, navegador, qualquer player que apareça
  nos controles de mídia do Windows). Quatro skins: Vinil Retrô, Capa Completa, Ecos da Capa e Capa Empilhada.
  Capa em alta resolução, volume do player pela roda do mouse e posição/escala que se adaptam à tela.
- **Volume & mixer** — substitui o flyout de volume do Windows: volume geral, volume e mudo por aplicativo e saída
  ou entrada de áudio diferente para cada app.
- **Caps / Num Lock** — indicador na tela ao alternar Caps Lock e Num Lock.
- **Timer & Foco** — timer, cronômetro e alarme sempre à mão, com som de fim.
- **Hub** — temas claro, escuro e OLED (ou o do Windows), cor de destaque, português e inglês, iniciar com o
  Windows, posição de cada flyout na tela (8 posições) e atualização automática.
- **Temas** — cada flyout e widget aceita temas visuais (cores, fundo, figurinhas), importáveis, exportáveis e excluíveis em um
  arquivo `.aimskin`. Guia completo em [docs/temas.md](docs/temas.md).

### Atalhos

| Atalho | Ação |
|---|---|
| `Win` + `Alt` + `M` | Mostra/esconde o Music Player |
| `Win` + `Alt` + `V` | Abre o mixer de volume |
| `Win` + `Alt` + `T` | Mostra/esconde o Timer |
| `Win` + `Alt` + `K` | Testa o indicador de Caps Lock |

Todos podem ser trocados no Hub.

## Download

Baixe na página de [Releases](https://github.com/allsz/aimedget/releases):

- **`Aimedget-Setup-<versão>.exe`** — instalador (recomendado). Não pede administrador, cria o atalho no Menu
  Iniciar e se atualiza sozinho pelo Hub (Geral > Atualizações).
- **`Aimedget-<versão>-portable.zip`** — versão portátil: extraia e abra `Aimedget\Aimedget.exe`. Para atualizar,
  baixe a versão nova.
- **`SHA256SUMS.txt`** — os hashes SHA-256 dos arquivos, para conferir o download
  (`Get-FileHash .\arquivo -Algorithm SHA256` no PowerShell).

Requisitos: Windows 10 ou 11, 64 bits.

> **Aviso do Windows (SmartScreen):** o executável ainda não tem assinatura digital, então o Windows pode mostrar
> "O Windows protegeu o computador" na primeira vez. Clique em **Mais informações → Executar assim mesmo**. Se
> preferir, confira o hash do arquivo com o `SHA256SUMS.txt` antes.

As configurações, temas e capas salvas ficam em `%LOCALAPPDATA%\Aimedget`. O desinstalador pergunta se você quer
apagá-los também.

## Desenvolvimento

Requisitos: Python 3.11+ no Windows.

```powershell
pip install -r requirements.txt -r requirements-dev.txt
python -m app.main          # abre o app (use --minimized para começar só na bandeja)
python -m pytest tests -q   # testes (com $env:QT_QPA_PLATFORM="offscreen" para não abrir janelas)
```

### Gerar uma release

Requer também o [Inno Setup](https://jrsoftware.org/isinfo.php) (6 ou 7).

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1
```

O script roda os testes, gera o executável (PyInstaller, em pasta), a versão portátil, o instalador e o
`SHA256SUMS.txt` em `dist\release`. A versão vem de um lugar só: [app/core/version.py](app/core/version.py).

### Estrutura

```
app/
  core/       configuração, caminhos, i18n, temas, tipografia, relatório de erros
  services/   serviços do Windows sem interface: mídia, áudio, teclas, atalhos, atualização
  widgets/    os widgets e flyouts (music, volume_mixer, keylock_osd, timer)
  hub/        o app de configuração (janela, páginas e componentes)
installer/    script do instalador (Inno Setup)
tools/        build da release e ferramentas de temas
tests/        testes automatizados (pytest)
```

## Licença

O Aimedget é software livre, distribuído sob a [GNU General Public License v3.0](LICENSE): você pode usar, estudar,
modificar e redistribuir; quem distribuir uma versão modificada precisa disponibilizar o código dela sob a mesma
licença.

Componentes de terceiros (Qt/PySide6, Python, fontes, som do timer) têm as próprias licenças, listadas em
[THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).
