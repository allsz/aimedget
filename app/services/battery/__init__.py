"""
Leitura de bateria de periféricos (Battery Widget).

Fontes escolhidas por estabilidade, sem dependências novas (só ctypes):
- `xinput`: API documentada da Microsoft (controles compatíveis com Xbox sem fio; níveis grossos).
- `sony`: relatório de entrada HID do DualSense / DualShock 4 (formato usado há anos pelo SDL e pelo kernel Linux).
- `switch_pro`: relatório de entrada do Switch Pro Controller (inclui o 8BitDo Pro 3 em modo Switch por Bluetooth);
  4 níveis, então aproximado.
- `logitech`: HID++ 2.0 pelo receptor (Bolt/Unifying/Lightspeed) ou Bluetooth direto (Unified Battery 0x1004 /
  Battery Status 0x1000), o mesmo caminho do Solaar.
- `vxe`: mouses VXE/ATK pelo dongle "Mouse 1K" (relatório de fabricante de 17 bytes, o mesmo do app web da ATK).
- `ajazz`: mouses AJAZZ pelo dongle "2.4G Wireless Receiver" (o pacote dos VXE, pedido por relatório de recurso).
- `bluetooth`: a carga que o Windows guarda para qualquer dispositivo Bluetooth conectado (fones pelo HFP,
  dispositivos LE pelo GATT), sem código por marca. Quem já tem leitor próprio é pulado pelo endereço.

Não há leitura para dongles sem protocolo conhecido (ex.: o 8BitDo pelo dongle 2.4G) nem para o celular do Phone Link
(ele só aparece quando está conectado por Bluetooth). Esquerdo/direito/estojo de fones TWS separados exigiriam o
protocolo de cada marca. Controles que imitam o Xbox por Bluetooth (ex.: GuliKit) ficam sem carga: o Windows.Gaming.Input
foi testado e devolveu um valor parado (10% depois de 2 h carregando).
"""

from app.services.battery.models import BatteryDevice, KIND_CONTROLLER, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE, KIND_OTHER, KIND_PHONE

__all__ = [
    "BatteryDevice",
    "KIND_CONTROLLER",
    "KIND_HEADSET",
    "KIND_KEYBOARD",
    "KIND_MOUSE",
    "KIND_OTHER",
    "KIND_PHONE",
]
