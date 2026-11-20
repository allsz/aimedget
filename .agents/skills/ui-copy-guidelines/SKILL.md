---
name: ui-copy-guidelines
description: Diretrizes de redação concisa (UX Copy) para títulos, descrições, botões, chips, menus e tooltips do Aimedget. Use sempre que adicionar, renomear ou revisar qualquer opção, botão ou texto visível na interface (Hub ou widgets).
---

# Aimedget — UX Copy & Nomenclatura de Opções

Baseado nas diretrizes de clareza do Impeccable (`clarify.md`) e no padrão visual do Aimedget Hub (minimalista, direto, sem ruído).

## Regras obrigatórias ao criar ou revisar uma opção

1. **Diga cada ideia uma única vez:**
   - Se o título + controle (chips, switch, slider) já explicam a opção, deixe o subtítulo **vazio (`""`)**.
   - Exemplos reais no app:
     - `Unidade de temperatura` → subtítulo `""` (os chips `°C` / `°F` já dizem tudo).
     - `Fonte do cartão` → subtítulo `""` + `HelpBadge` (`?`).
     - `Fonte da previsão` → subtítulo `""` + `HelpBadge` (`?`).
2. **Subtítulos ultracurtos (quando realmente agregam algo novo):**
   - Máximo **1 frase curta (3–8 palavras)** que responda a uma consequência prática — nunca repita o título nem comece com "Escolha qual..." ou "Permite ativar...".
   - Bom: `"Reabre onde você o deixou."` / `"Abre ou oculta o widget."` / `"Desativado, abra pelo atalho."`
   - Ruim: `"Escolha qual modelo da Open-Meteo usar. Se a temperatura divergir da sua região..."`
3. **Detalhe secundário vai no `HelpBadge` (`?`), nunca no corpo do cartão:**
   - Dicas condicionais, atalhos extras ou explicações técnicas ficam em `help_key` (`HelpBadge`), mantendo o cartão limpo e escaneável.
4. **Zero jargão interno ou nomes de API/implementação:**
   - Fale na língua do usuário, não do código. Evite expor nomes de serviços/APIs (`Open-Meteo`, `GSMTC`, `DWM`) ou termos técnicos desnecessários nos rótulos principais.
   - Prefira `"Fonte da previsão"` / `"Forecast source"` em vez de `"Modelo de API"`.
5. **Botões, chips e menus:**
   - Chips e botões de ação: **1–2 palavras** no máximo (`Exibir`, `Automático`, `Alinhar`, `Concluir`).
   - Itens da barra superior Fluent Rail: **somente ícone arredondado**, sem rótulo fixo; tooltip conciso no infinitivo ou substantivo curto (`Atualizar agora`, `Lembrar posição`, `Igualar tamanho`).
   - Ações que não abrem submenu viram botões mínimos na barra superior, nunca linhas verbosas.
6. **Paridade `pt-BR` e `en`:**
   - Toda chave nova em `app/core/i18n.py` deve existir em `pt` e `en` com o mesmo nível de concisão e tom natural (não tradução literal dura).
   - Sempre revisar o cartão pronto com o olho de edição: *"Qual palavra posso cortar sem perder significado?"*
