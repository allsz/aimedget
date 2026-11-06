# Roteiro de Implementação · Music Widget (Vinyl Edition)

Este documento registra o planejamento modular de 5 passos para o desenvolvimento do widget de música baseado no design `wide_vynil(eu)`.

---

## 📌 Visão Geral do Projeto
- **Referência:** [wide_vynil(eu).webp](file:///C:/Users/Matthew/Projects%20(Studying)/Windows_Redesign/Refer%C3%AAncias%20Visuais/Music%20Widget/wide_vynil(eu).webp)
- **Plataforma:** Windows 10 / 11
- **Arquitetura:** Python + PyQt6 / QML (compilado para `.exe` com PyInstaller)
- **Integração:** Windows Media Session Manager (`winsdk` / GSMTC) para leitura de títulos, artistas, capas e controle de mídia.

---

## 🚀 Os 5 Passos de Desenvolvimento

### ✅ Passo 1: A Janela Flutuante & O Design Fiel (Concluído)
- **Objetivo:** Criar a janela flutuante no Windows sem molduras de sistema, com cantos arredondados, fundo translúcido/acrílico escuro e todo o esqueleto visual do layout:
  - Título e artista no topo esquerdo.
  - Controles minimalistas sem background.
  - Barra de progresso de tempo na base.
  - Toca-discos à direita com vinil centralizado, base e braço da agulha.
- **Critério de Teste:** Executar o script inicial e validar dimensões, tipografia, proporções e enquadramento visual na tela.

---

### ✅ Passo 2: A Física do Toca-Discos & Scrubbing Interativo (Concluído)
- **Objetivo:** Implementar toda a lógica de animações mecânicas:
  - Agulha se move suavemente da base de repouso para o vinil ao dar Play, e volta ao dar Pause.
  - Vinil gira continuamente a velocidade constante enquanto toca.
  - **Scrubbing de DJ:** Ao arrastar a barra de progresso com o mouse:
    - Arrastar para a esquerda (retroceder) ➔ Vinil gira no sentido anti-horário na velocidade do arrasto.
    - Arrastar para a direita (avançar) ➔ Vinil gira no sentido horário proporcionalmente à puxada.
    - Clique estático na barra ➔ Mantém a rotação estável sem trancos.
- **Critério de Teste:** Interagir com o mouse sobre os controles e a barra de tempo para validar a resposta tátil e a suavidade dos giros.

---

### ✅ Passo 3: Conexão Real com o Windows (GSMTC) (Concluído)
- **Objetivo:** Conectar o widget às APIs nativas de mídia do Windows (`GlobalSystemMediaTransportControlsSessionManager`):
  - Ler sessões ativas (Spotify, Chrome, Edge, YouTube, Apple Music, Deezer, etc.).
  - Obter capa em alta resolução para colocar no centro do disco.
  - Obter nome da faixa e nome do artista em tempo real.
  - Fazer os botões controlarem a reprodução de fato no sistema (com listener `tonearm_landed` exclusivo da skin de Vinil e sincronia de tempo via `last_updated_time`).
- **Critério de Teste:** Tocar uma música em qualquer aplicativo do computador e ver o widget atualizar as informações e capas automaticamente.

---

### 🟩 Passo 4: Colorimetria Dinâmica (Gradiente Baseado na Capa) (Em Teste)
- **Objetivo:** Implementar o algoritmo de extração de paleta cromática da arte do álbum:
  - Identificar a cor dominante do disco.
  - Gerar gradiente suave adaptativo, garantindo que os tons escuros fiquem sempre na parte inferior para contraste legível com os botões e barra branca.
- **Critério de Teste:** Alternar músicas com capas de cores contrastantes e verificar a transição fluida do fundo.

---

### ⏳ Passo 5: Executável Portátil (`.exe`) & Bandeja do Sistema
- **Objetivo:** Empacotar a aplicação em executável autônomo:
  - Criar ícone na System Tray (bandeja perto do relógio).
  - Permitir arrastar a janela livremente ou fixá-la na tela preferida do usuário.
  - Opções de inicialização automática com o Windows e seleção de skins.
- **Critério de Teste:** Rodar o `.exe` diretamente com duplo clique sem precisar de terminal ou dependências externas.

