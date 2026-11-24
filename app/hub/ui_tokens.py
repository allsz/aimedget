"""
Medidas de espaçamento do Hub: fonte única. Páginas e componentes importam daqui em vez de escrever números soltos.

Regra de dono único: quem é DONO de um espaço é o contêiner (setSpacing / addSpacing do layout pai). Um item nunca
acrescenta margem em volta de si mesmo, porque aí dois donos somam o mesmo vão (foi assim que o botão "Adicionar
minha localização" ficou com 16 px em cima e 10 px embaixo). A única exceção é um vão que precisa abrir e fechar
junto com o item (Fold, linhas da CityList): esse fica DENTRO do item, e o vizinho desconta.
"""

# Página
PAGE_GAP = 18          # entre os cartões de uma página

# Cartão
CARD_MARGINS = (18, 14, 18, 14)   # esquerda, topo, direita, base
ROWS_GAP = 12          # entre as linhas de um cartão (opção, divisor, opção)
INLINE_GAP = 16        # entre o bloco de texto e o controle ao lado dele

# Texto
INFO_GAP = 2           # entre título e subtítulo
BADGE_GAP = 6          # entre um título e o "?" (HelpBadge) ao lado

# Botões
CHIP_GAP = 8           # entre chips/botões lado a lado

# Listas empilhadas (cidades, pastas)
STACK_GAP = 10         # entre itens empilhados de um cartão de lista (lista, botão, busca)
LIST_ROW_GAP = 6       # folga sob cada linha da lista; fica dentro da linha para fechar junto com ela
