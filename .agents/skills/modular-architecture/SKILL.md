---
name: modular-architecture
description: >-
  Diretrizes de arquitetura modular, separação de responsabilidades e organização
  de pastas para o projeto Windows Redesign (Music Widget e skins, Caps/NumLock OSD,
  Volume Mixer por aplicativo e Hub do executável). Use esta skill sempre que for
  refatorar código monolítico, criar novas skins, adicionar novos módulos do sistema
  ou estruturar o pacote para compilação em .exe.
---

# Arquitetura Modular · Windows Redesign Suite

Esta skill define o padrão de organização de código para garantir **legibilidade humana**, **manutenibilidade** e **escalabilidade** à medida que o projeto cresce de um único widget para uma suíte completa do Windows controlada por um `.exe`.

---

## 1. Princípios Fundamentais (Anti-Monolito)

1. **Proibido misturar API Nativa do Windows com Renderização (`QPainter`):**
   - Workers que conversam com WinRT (GSMTC), Win32 (`ctypes`/`user32`) ou Core Audio (`pycaw`/COM) **nunca** devem ficar no mesmo arquivo que desenha janelas (`paintEvent`).
   - Os serviços de sistema emitem apenas sinais do Qt (`Signal`) e recebem comandos simples.
2. **Tamanho e Escopo de Arquivo para Visualização Humana:**
   - Mantenha cada arquivo focado em **uma única responsabilidade** (meta ideal: **120 a 300 linhas** por arquivo).
   - Se um arquivo ultrapassar ~350 linhas, avalie extrair subcomponentes visuais, cálculos de física ou serviços para módulos próprios.
3. **Isolamento de Skins (Padrão Strategy/View):**
   - Comportamentos mecânicos exclusivos de uma skin — como a animação da agulha e o listener `tonearm_landed` da skin de Vinil — devem existir **exclusivamente** dentro da classe daquela skin (`skins/vinyl_skin.py`), nunca no controlador geral ou nas outras skins.

---

## 2. Estrutura de Diretórios Padrão (`app/`)

Ao separar o monolito ou criar novos recursos, siga exatamente esta árvore de pacotes:

```text
app/
├── main.py                      # Entrypoint único do .exe (QApplication, Fontes, Tray e Hub)
├── core/                        # Utilitários base e configuração
│   ├── paths.py                 # Resolução segura de caminhos (compatível com PyInstaller sys._MEIPASS)
│   ├── config_manager.py        # Leitura/gravação de preferências (JSON: módulos ativos, skins, posições)
│   └── colorimetry.py           # Extração de cor dominante da capa e geração de gradientes
├── services/                    # Workers em background (Zero código de UI)
│   ├── media_worker.py          # Integração Windows GSMTC (Spotify, navegadores, etc.)
│   ├── audio_mixer_service.py   # Controle de volume Master e por App (CoreAudio / pycaw + ícones de processos)
│   └── keylock_service.py       # Monitoramento de estado e eventos de Caps Lock e Num Lock (Win32)
├── ui_components/               # Peças visuais reutilizáveis entre vários widgets
│   ├── fluent_Window.py         # Classe base de janela flutuante sem bordas (arraste, acrílico/clip arredondado)
│   ├── pill_button.py           # Botões estilo pílula translúcida (.pill)
│   └── fluent_slider.py         # Sliders horizontais (usados tanto no Volume Mixer quanto em configurações)
├── widgets/                     # Módulos independentes da suíte
│   ├── music/                   # Módulo 1: Music Widget
│   │   ├── music_controller.py  # Gerencia a skin ativa e conecta ao MediaWorker
│   │   └── skins/
│   │       ├── base_skin.py     # Interface comum a todas as skins de música
│   │       └── vinyl_skin.py    # Skin de Vinil (disco 33 RPM, scrubbing DJ, física do tonearm e tonearm_landed)
│   ├── keylock_osd/             # Módulo 2: Flyout de Caps Lock & Num Lock
│   │   └── keylock_flyout.py    # Card 160x144 Fluent com cadeado SVG, barra LED neon e fade-out automático
│   └── volume_mixer/            # Módulo 3: Flyout de Mixer de Volume (estilo Windows 11)
│       ├── mixer_flyout.py      # Janela retrátil com slider Master no topo e lista de apps abaixo
│       └── app_volume_row.py    # Linha individual (ícone do app + slider azul Fluent + percentual numérico)
└── hub/                         # Interface de Controle do .exe
    ├── tray_icon.py             # Ícone na bandeja do sistema (System Tray) com menu rápido
    └── settings_window.py       # Painel principal para ativar/desativar widgets, trocar skins e configurar boot
```

---

## 3. Fluxo de Trabalho ao Refatorar ou Criar Módulos

Sempre que o usuário pedir para modularizar ou adicionar um dos novos recursos (Caps/NumLock, Volume Mixer, novas Skins ou Hub do `.exe`), siga estes passos:

1. **Verifique o `core/paths.py`:**
   Garanta que todos os carregamentos de SVGs e fontes (`assets/`) passem por uma função central que suporte tanto execução em desenvolvimento quanto empacotado via PyInstaller (`getattr(sys, '_MEIPASS', BASE_DIR)`).
2. **Crie ou atualize o Serviço primeiro (`app/services/`):**
   Teste se o worker emite os sinais esperados de forma isolada antes de acoplar à interface gráfica.
3. **Construa a View/Widget usando componentes de `app/ui_components/`:**
   Evite duplicar código de sombra, sliders ou botões entre o Music Widget, o Volume Mixer e o OSD de teclado.
4. **Validação:**
   Execute `python -m py_compile` nos módulos criados e teste a inicialização sem quebrar os widgets já funcionais.
