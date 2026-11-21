"""
Leitura de bateria de periféricos (Battery Widget).

Fontes escolhidas por estabilidade, sem dependências novas (só ctypes):
- `xinput`: API documentada da Microsoft (controles compatíveis com Xbox sem fio; níveis grossos).
- `sony`: relatório de entrada HID do DualSense / DualShock 4 (formato usado há anos pelo SDL e pelo kernel Linux).
- `logitech`: HID++ 2.0 pelo receptor (Bolt/Unifying/Lightspeed) ou Bluetooth direto (Unified Battery 0x1004 /
  Battery Status 0x1000), o mesmo caminho do Solaar.

Não há leitura para dongles sem protocolo público (ex.: VXE) nem para o celular do Phone Link.
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
