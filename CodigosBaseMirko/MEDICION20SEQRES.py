import serial
import csv
import time
import os
from datetime import datetime


# ============================================================
# CONFIGURACIÓN
# ============================================================

PORT = "COM4"
BAUDRATE = 115200

OUTPUT_FILE = "MR60BHA1_20mediciones02.csv"

N_MEDICIONES = 20

# Duraciones en segundos
T_NORMAL = 20
T_HOLD = 10
T_RECOVERY = 30

# Cuenta regresiva antes de aguantar
T_COUNTDOWN = 3


# ============================================================
# CONEXIÓN CON ESP32
# ============================================================

print("Conectando al ESP32...")

ser = serial.Serial(
    port=PORT,
    baudrate=BAUDRATE,
    timeout=1
)

time.sleep(2)

print(f"Conectado a {PORT}")
print()
print("Protocolo:")
print(f"  Respiración normal : {T_NORMAL} s")
print(f"  Preparación        : 3 - 2 - 1")
print(f"  Aguantar           : {T_HOLD} s")
print(f"  Descanso           : {T_RECOVERY} s")
print(f"  Mediciones         : {N_MEDICIONES}")
print()

print("Durante la retención realiza solamente un")
print("aguante voluntario y cómodo. No fuerces la respiración.")
print()

input("Presiona ENTER para comenzar...")


# ============================================================
# FUNCIÓN PARA LIMPIAR PANTALLA
# ============================================================

def limpiar_pantalla():

    os.system("cls" if os.name == "nt" else "clear")


# ============================================================
# FUNCIÓN PARA MOSTRAR ESTADO
# ============================================================

def mostrar_estado(medicion, titulo, tiempo=None):

    limpiar_pantalla()

    print()
    print("=" * 60)
    print(f"                 MEDICIÓN {medicion}/{N_MEDICIONES}")
    print("=" * 60)
    print()

    print(f"              {titulo}")

    if tiempo is not None:

        print()
        print(f"                    {tiempo}")

    print()


# ============================================================
# CREAR ARCHIVO CSV
# ============================================================

with open(
    OUTPUT_FILE,
    mode="w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.writer(file)

    writer.writerow([
        "timestamp",
        "medicion",
        "fase",
        "condicion",
        "flag_hold",
        "tipo",
        "valor_1",
        "valor_2",
        "valor_3",
        "valor_4",
        "valor_5"
    ])

    file.flush()


    # ========================================================
    # FUNCIÓN PARA REGISTRAR CAMBIO DE FASE
    # ========================================================

    def registrar_fase(
        medicion,
        fase,
        condicion,
        flag_hold
    ):

        timestamp = datetime.now().isoformat(
            timespec="milliseconds"
        )

        writer.writerow([
            timestamp,
            medicion,
            fase,
            condicion,
            flag_hold,
            "PHASE",
            "",
            "",
            "",
            "",
            ""
        ])

        file.flush()


    # ========================================================
    # FUNCIÓN PARA LEER Y GUARDAR DATOS DEL ESP32
    # ========================================================

    def procesar_dato(
        line,
        medicion,
        fase,
        condicion,
        flag_hold
    ):

        if not line:
            return


        # ----------------------------------------------------
        # Timestamp
        # ----------------------------------------------------

        timestamp = datetime.now().isoformat(
            timespec="milliseconds"
        )


        # ----------------------------------------------------
        # Separar campos
        # ----------------------------------------------------

        data = line.split(",")

        tipo = data[0]


        # ====================================================
        # START
        # ====================================================

        if tipo == "START":

            writer.writerow([
                timestamp,
                medicion,
                fase,
                condicion,
                flag_hold,
                "START",
                "",
                "",
                "",
                "",
                ""
            ])


        # ====================================================
        # EVENT
        # ====================================================

        elif tipo == "EVENT":

            if len(data) >= 2:

                writer.writerow([
                    timestamp,
                    medicion,
                    fase,
                    condicion,
                    flag_hold,
                    "EVENT",
                    data[1],
                    "",
                    "",
                    "",
                    ""
                ])


        # ====================================================
        # DISTANCIA
        # ====================================================

        elif tipo == "DIST":

            if len(data) >= 2:

                writer.writerow([
                    timestamp,
                    medicion,
                    fase,
                    condicion,
                    flag_hold,
                    "DIST",
                    data[1],
                    "",
                    "",
                    "",
                    ""
                ])


        # ====================================================
        # HEART RATE
        # ====================================================

        elif tipo == "HR":

            if len(data) >= 2:

                writer.writerow([
                    timestamp,
                    medicion,
                    fase,
                    condicion,
                    flag_hold,
                    "HR",
                    data[1],
                    "",
                    "",
                    "",
                    ""
                ])


        # ====================================================
        # BREATHING RATE
        # ====================================================

        elif tipo == "BR":

            if len(data) >= 2:

                writer.writerow([
                    timestamp,
                    medicion,
                    fase,
                    condicion,
                    flag_hold,
                    "BR",
                    data[1],
                    "",
                    "",
                    "",
                    ""
                ])


        # ====================================================
        # BREATHING WAVEFORM
        # ====================================================

        elif tipo == "BW":

            if len(data) >= 6:

                writer.writerow([
                    timestamp,
                    medicion,
                    fase,
                    condicion,
                    flag_hold,
                    "BW",
                    data[1],
                    data[2],
                    data[3],
                    data[4],
                    data[5]
                ])


        # ----------------------------------------------------
        # Guardar inmediatamente
        # ----------------------------------------------------

        file.flush()


    # ========================================================
    # FUNCIÓN PARA LEER DATOS DURANTE UN INTERVALO
    # ========================================================

    def adquirir_durante(
        duracion,
        medicion,
        fase,
        condicion,
        flag_hold
    ):

        inicio = time.monotonic()

        while (time.monotonic() - inicio) < duracion:

            # --------------------------------------------
            # Leer ESP32
            # --------------------------------------------

            raw_line = ser.readline()

            if raw_line:

                line = raw_line.decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

                if line:

                    procesar_dato(
                        line,
                        medicion,
                        fase,
                        condicion,
                        flag_hold
                    )


    # ========================================================
    # ADQUISICIÓN DE LAS 20 MEDICIONES
    # ========================================================

    try:

        for medicion in range(
            1,
            N_MEDICIONES + 1
        ):

            # =================================================
            # ESPERA PARA POSICIONARSE
            # =================================================

            limpiar_pantalla()

            print()
            print("=" * 60)
            print(f"                 MEDICIÓN {medicion}/{N_MEDICIONES}")
            print("=" * 60)
            print()
            print("Colócate en posición.")
            print()
            print("Cuando estés listo, presiona ENTER.")
            print()

            input()


            # =================================================
            # FASE 1
            # RESPIRACIÓN NORMAL
            # =================================================

            registrar_fase(
                medicion,
                "NORMAL",
                "RESPIRACION_NORMAL",
                0
            )

            mostrar_estado(
                medicion,
                "RESPIRACIÓN NORMAL"
            )

            adquirir_durante(
                T_NORMAL,
                medicion,
                "NORMAL",
                "RESPIRACION_NORMAL",
                0
            )


            # =================================================
            # FASE 2
            # PREPÁRATE
            # =================================================

            registrar_fase(
                medicion,
                "PREP",
                "PREPARACION",
                0
            )

            mostrar_estado(
                medicion,
                "PREPÁRATE"
            )

            time.sleep(1)


            # =================================================
            # CUENTA REGRESIVA
            # =================================================

            for cuenta in [3, 2, 1]:

                mostrar_estado(
                    medicion,
                    "PREPÁRATE",
                    cuenta
                )

                time.sleep(1)


            # =================================================
            # FASE 3
            # AGUANTAR RESPIRACIÓN
            # =================================================

            registrar_fase(
                medicion,
                "HOLD",
                "RETENCION",
                1
            )

            mostrar_estado(
                medicion,
                "AGUANTA LA RESPIRACIÓN"
            )

            adquirir_durante(
                T_HOLD,
                medicion,
                "HOLD",
                "RETENCION",
                1
            )


            # =================================================
            # FASE 4
            # DESCANSO
            # =================================================

            registrar_fase(
                medicion,
                "RECOVERY",
                "RECUPERACION",
                0
            )

            mostrar_estado(
                medicion,
                "DESCANSO"
            )

            adquirir_durante(
                T_RECOVERY,
                medicion,
                "RECOVERY",
                "RECUPERACION",
                0
            )


            # =================================================
            # FIN DE MEDICIÓN
            # =================================================

            timestamp = datetime.now().isoformat(
                timespec="milliseconds"
            )

            writer.writerow([
                timestamp,
                medicion,
                "END",
                "FIN",
                0,
                "END",
                "",
                "",
                "",
                "",
                ""
            ])

            file.flush()


            # =================================================
            # DESCANSO ENTRE MEDICIONES
            # =================================================

            if medicion < N_MEDICIONES:

                mostrar_estado(
                    medicion,
                    "DESCANSO"
                )

                time.sleep(3)


        # ====================================================
        # FIN DE LAS 20 MEDICIONES
        # ====================================================

        limpiar_pantalla()

        print()
        print("=" * 60)
        print("              MEDICIONES COMPLETADAS")
        print("=" * 60)
        print()
        print(f"Se realizaron {N_MEDICIONES} mediciones.")
        print()
        print(f"Archivo: {OUTPUT_FILE}")
        print()


    # ========================================================
    # CTRL+C
    # ========================================================

    except KeyboardInterrupt:

        limpiar_pantalla()

        print()
        print("Adquisición detenida manualmente.")
        print()


    # ========================================================
    # CERRAR PUERTO
    # ========================================================

    finally:

        ser.close()

        print("Puerto serial cerrado.")
        print(f"Datos guardados en: {OUTPUT_FILE}")