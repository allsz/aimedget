# Windows Redesign · Caps Lock Flyout Specification

Referência visual e especificações de design para o popup de Caps Lock (substituição do OSD quadrado do Logitech Options+).

---

## 🎨 Especificações Visuais

- **Proporção:** ~4:3 (quase quadrado: `160px` largura × `144px` altura).
- **Raio de Borda (Border Radius):** `24px` (Squircle / Curvatura Fluent do Windows 11).
- **Fundo do Card:**
  - Cor base: `rgba(26, 26, 30, 0.75)`
  - Efeito: Acrílico translúcido com `backdrop-filter: blur(28px) saturate(180%)`
  - Borda externa: `1px solid rgba(255, 255, 255, 0.12)`
  - Sombra: `0 20px 40px -10px rgba(0, 0, 0, 0.65)`

---

## 🔒 Elementos & Hierarquia

1. **Ícone de Cadeado:**
   - **Sem container/fundo**: O SVG repousa diretamente sobre a transparência do card.
   - **Caps Ativo (Locked):** Cadeado fechado branco puro (`#FFFFFF`) com leve drop shadow.
   - **Caps Inativo (Unlocked):** Cadeado aberto em tom cinza suave (`#A3A3A3`).

2. **Tipografia:**
   - Texto: `CAPS LOCK` (sem texto redundante de on/off).
   - Fonte: Segoe UI Variable / Inter / Sans-serif.
   - Tamanho: `12px` (estilo sub-caption Windows 11), peso semi-bold (`600`), tracking sutil (`wider`).

3. **Indicador de Status (Barra LED):**
   - Dimensões: `44px` largura × `6px` altura com cantos totalmente arredondados (`border-radius: 9999px`).
   - **Ativo:** Azul elétrico (`#38BDF8`) com brilho sutil em neon (`box-shadow: 0 0 12px rgba(56, 189, 248, 0.9)`).
   - **Inativo:** Cinza escuro transparente (`rgba(255, 255, 255, 0.14)`), sem brilho.

---

## 📁 Arquivos do Projeto

- [caps_lock_fluent_design.html](<file:///C:/Users/Matthew/Projects%20(Studying)/Windows_Redesign/caps_lock_fluent_design.html>): Prévia interativa completa em HTML/CSS/Tailwind que responde ao toque da tecla física no teclado.
