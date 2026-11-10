"""
Qual sessão de áudio representa um aplicativo no mixer quando ele tem sessões em VÁRIOS dispositivos de saída
(lógica pura, sem COM, para ser testável sem áudio real).

Por que existe: o Windows cria uma sessão por dispositivo. Ao rotear o Chrome das caixas para o fone, ficam duas
sessões do Chrome: a das caixas (sem som) e a do fone (a que toca). Antes o mixer só olhava o dispositivo padrão e
mostrava/alterava a sessão errada (o volume "não mexia").

Regra para o volume/mudo MOSTRADO:
1. A sessão que está TOCANDO (se houver mais de uma, a do dispositivo roteado, depois a do padrão).
2. Senão, a do dispositivo para onde o app foi roteado.
3. Senão, a do dispositivo padrão do Windows.
4. Senão, a primeira encontrada.

Para ALTERAR volume/mudo, o serviço aplica em todas as sessões do app (todos os dispositivos), então o app soa igual
onde quer que esteja tocando e trocar a rota de volta não "herda" um volume antigo esquecido.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionReading:
    device_id: str
    volume: int          # 0 a 100
    muted: bool
    active: bool         # AudioSessionStateActive: está tocando agora


def choose_primary(readings: list[SessionReading], default_device_id: str,
                   routed_device_id: str | None = None) -> SessionReading:
    """A sessão que representa o app (ver a regra no topo do módulo). `readings` não pode ser vazia."""
    if not readings:
        raise ValueError("sem sessões para escolher")

    def preference(r: SessionReading) -> tuple[int, int]:
        # Menor = melhor: primeiro o dispositivo roteado, depois o padrão, depois os demais
        if routed_device_id and r.device_id == routed_device_id:
            return (0, 0)
        if r.device_id == default_device_id:
            return (1, 0)
        return (2, 0)

    active = [r for r in readings if r.active]
    if active:
        return min(active, key=preference)          # min é estável: empate fica com a primeira encontrada
    if routed_device_id:
        for r in readings:
            if r.device_id == routed_device_id:
                return r
    for r in readings:
        if r.device_id == default_device_id:
            return r
    return readings[0]
