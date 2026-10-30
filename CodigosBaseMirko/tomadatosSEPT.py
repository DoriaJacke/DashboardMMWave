import serial
import pandas as pd
import time
from datetime import datetime

# ============================================================
# CONFIGURACIÓN
# ============================================================

PORT = "COM4"       # CAMBIA ESTO POR TU PUERTO
BAUDRATE = 115200

OUTPUT_FILE = "MR60BHA1_experimento3322.csv"

# ============================================================
# CONEXIÓN
# ============================================================

ser = serial.Serial(
    PORT,
    BAUDRATE,
    timeout=1
)

time.sleep(2)

print("Conectado al ESP32.")
print("Presiona Ctrl+C para detener.")
print()

# ============================================================
# VARIABLES
# ============================================================

data = []

start_time = time.time()

current_hr = None
current_br = None
current_distance = None
current_movement = None

# ============================================================
# CAPTURA
# ============================================================

try:

    while True:

        line = ser.readline().decode(
            "utf-8",
            errors="ignore"
        ).strip()

        if not line:
            continue

        timestamp = time.time() - start_time

        parts = line.split(",")

        # ----------------------------------------------------
        # EVENTO
        # ----------------------------------------------------

        if parts[0] == "EVENT":

            current_movement = parts[1]

        # ----------------------------------------------------
        # DISTANCIA
        # ----------------------------------------------------

        elif parts[0] == "DIST":

            current_distance = float(parts[1])

        # ----------------------------------------------------
        # FRECUENCIA RESPIRATORIA
        # ----------------------------------------------------

        elif parts[0] == "BR":

            current_br = float(parts[1])

        # ----------------------------------------------------
        # FRECUENCIA CARDIACA
        # ----------------------------------------------------

        elif parts[0] == "HR":

            current_hr = float(parts[1])

        # ----------------------------------------------------
        # GUARDAR REGISTRO
        # ----------------------------------------------------

        data.append({

            "timestamp": timestamp,

            "datetime": datetime.now().isoformat(),

            "HR": current_hr,

            "BR": current_br,

            "distance": current_distance,

            "movement": current_movement,

            "raw": line
        })

        print(
            f"{timestamp:8.2f} s | "
            f"HR={current_hr} | "
            f"BR={current_br} | "
            f"D={current_distance} | "
            f"{current_movement}"
        )

except KeyboardInterrupt:

    print("\nDeteniendo adquisición...")

finally:

    ser.close()

    # ========================================================
    # GUARDAR CSV
    # ========================================================

    df = pd.DataFrame(data)

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print()
    print("Datos guardados en:")
    print(OUTPUT_FILE)

    print()
    print(f"Registros: {len(df)}")