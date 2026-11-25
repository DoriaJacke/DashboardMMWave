# ============================================================
# FUNCIONES OPCIONALES DEL DASHBOARD
#
# La placa CMAE (ECG, oxímetro, presión) queda aislada del
# dashboard del radar mientras se revisa con el profesor guía.
# Apagada: el backend no carga backend/cmae/ (ni Bluetooth), no
# expone /api/cmae/* ni /ws/cmae, no graba <archivo>_cmae.csv, y
# la interfaz oculta la pestaña, las tarjetas y la conexión.
#
# Para encenderla, antes de iniciar el backend:
#   PowerShell:  $env:MMWAVE_CMAE = "1"
#   cmd:         set MMWAVE_CMAE=1
# ============================================================

import os


def _activa(nombre: str, por_defecto: bool = False) -> bool:
    valor = os.environ.get(nombre)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "on"}


CMAE_HABILITADA = _activa("MMWAVE_CMAE")
